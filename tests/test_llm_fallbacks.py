"""Fallback models behind a tier's own model (llm_fallbacks)."""
from __future__ import annotations

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import tool

import tradingagents.default_config as default_config_module
from tradingagents.llm_clients import factory
from tradingagents.llm_clients.factory import create_tier_llm, parse_llm_fallbacks


class _Model(BaseChatModel):
    """Answers ``reply``, or raises like a spent quota when ``reply`` is None."""

    name_: str
    reply: str | None = None

    @property
    def _llm_type(self) -> str:
        return "test"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.reply is None:
            raise RuntimeError(f"{self.name_}: 429 quota exceeded")
        tools = kwargs.get("tool_names")
        text = f"{self.reply} tools={tools}" if tools else self.reply
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    # The return hint is what makes RunnableWithFallbacks bind every fallback too.
    def bind_tools(self, tools, **kwargs) -> Runnable:
        return self.bind(tool_names=[t.name for t in tools])


class _Client:
    def __init__(self, llm):
        self._llm = llm

    def get_llm(self):
        return self._llm


@tool
def get_price(ticker: str) -> str:
    """Price of a ticker."""
    return "1"


def _patch(monkeypatch, primary, models, built):
    """Serve ``primary`` as the tier model and ``models[(provider, model)]`` as fallbacks."""
    monkeypatch.setattr(factory, "create_tier_client", lambda config, tier, **extra: _Client(primary))

    def create(provider, model, base_url=None, **kwargs):
        built.append((provider, model, kwargs))
        found = models[(provider, model)]
        if isinstance(found, Exception):
            raise found
        return _Client(found)

    monkeypatch.setattr(factory, "create_llm_client", create)


_CONFIG = {"llm_provider": "google", "quick_think_llm": "gemini-3.8-flash", "deep_think_llm": "gemini-3.8-flash"}


@pytest.mark.unit
@pytest.mark.parametrize("value,expected", [
    (None, []),
    ("", []),
    ("openrouter:openrouter/free", [("openrouter", "openrouter/free")]),
    (" OpenRouter:nvidia/nemotron-3-ultra-550b-a55b:free , google:gemini-3.8-flash ,",
     [("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free"), ("google", "gemini-3.8-flash")]),
    (["xai:grok-5", ("openai", "gpt-6-luna"), {"provider": "google", "model": "gemini-3.8-flash"}],
     [("xai", "grok-5"), ("openai", "gpt-6-luna"), ("google", "gemini-3.8-flash")]),
])
def test_parse_llm_fallbacks(value, expected):
    assert parse_llm_fallbacks(value) == expected


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["openrouter", ":model", "openrouter:", ["x"], [("a", "b", "c")]])
def test_parse_llm_fallbacks_rejects_entries_without_provider_and_model(bad):
    with pytest.raises(ValueError, match="provider:model"):
        parse_llm_fallbacks(bad)


@pytest.mark.unit
def test_env_var_sets_llm_fallbacks(monkeypatch):
    for key in default_config_module._ENV_OVERRIDES:
        monkeypatch.delenv(key, raising=False)
    assert default_config_module.build_default_config()["llm_fallbacks"] is None
    monkeypatch.setenv("TRADINGAGENTS_LLM_FALLBACKS", "openrouter:openrouter/free")
    assert default_config_module.build_default_config()["llm_fallbacks"] == "openrouter:openrouter/free"


@pytest.mark.unit
def test_no_fallbacks_returns_the_tier_model_itself(monkeypatch):
    primary = _Model(name_="gemini", reply="from gemini")
    _patch(monkeypatch, primary, {}, [])
    assert create_tier_llm(_CONFIG, "quick") is primary


@pytest.mark.unit
def test_failing_model_hands_over_to_the_next_in_order(monkeypatch):
    built = []
    _patch(monkeypatch, _Model(name_="gemini"), {
        ("openrouter", "nvidia/nemotron:free"): _Model(name_="nemotron"),
        ("openrouter", "openrouter/free"): _Model(name_="router", reply="from router"),
    }, built)
    config = {**_CONFIG, "llm_fallbacks": "openrouter:nvidia/nemotron:free,openrouter:openrouter/free"}

    llm = create_tier_llm(config, "quick")

    assert llm.invoke("hi").content == "from router"
    assert [(p, m) for p, m, _ in built] == [("openrouter", "nvidia/nemotron:free"),
                                              ("openrouter", "openrouter/free")]


@pytest.mark.unit
def test_tool_binding_reaches_the_fallback(monkeypatch):
    _patch(monkeypatch, _Model(name_="gemini"),
           {("openrouter", "openrouter/free"): _Model(name_="router", reply="ok")}, [])
    llm = create_tier_llm({**_CONFIG, "llm_fallbacks": "openrouter:openrouter/free"}, "quick")

    assert llm.bind_tools([get_price]).invoke("hi").content == "ok tools=['get_price']"


@pytest.mark.unit
def test_primary_repeated_in_fallbacks_is_not_tried_twice(monkeypatch):
    built = []
    _patch(monkeypatch, _Model(name_="gemini", reply="g"),
           {("openrouter", "openrouter/free"): _Model(name_="router", reply="r")}, built)
    config = {**_CONFIG, "llm_fallbacks": "google:gemini-3.8-flash,openrouter:openrouter/free"}

    create_tier_llm(config, "quick")

    assert [(p, m) for p, m, _ in built] == [("openrouter", "openrouter/free")]


@pytest.mark.unit
def test_fallback_that_cannot_be_built_is_skipped(monkeypatch, caplog):
    _patch(monkeypatch, _Model(name_="gemini"), {
        ("xai", "grok-5"): ValueError("XAI_API_KEY is not set"),
        ("openrouter", "openrouter/free"): _Model(name_="router", reply="from router"),
    }, [])
    config = {**_CONFIG, "llm_fallbacks": "xai:grok-5,openrouter:openrouter/free"}

    llm = create_tier_llm(config, "deep")

    assert llm.invoke("hi").content == "from router"
    assert "xai:grok-5 skipped" in caplog.text


@pytest.mark.unit
def test_each_fallback_gets_its_own_provider_settings(monkeypatch):
    built = []
    _patch(monkeypatch, _Model(name_="gemini"),
           {("openrouter", "openrouter/free"): _Model(name_="router", reply="r")}, built)
    config = {**_CONFIG, "google_thinking_level": "high", "max_tokens": 4096,
              "llm_fallbacks": "openrouter:openrouter/free"}

    create_tier_llm(config, "quick")

    (_, _, kwargs), = built
    assert kwargs == {"max_tokens": 4096}  # no Gemini thinking level, OpenAI's name for the cap


@pytest.mark.unit
@pytest.mark.parametrize("value,expected", [(180, 180.0), ("90", 90.0), ("2.5", 2.5)])
def test_llm_timeout_is_forwarded_in_seconds(value, expected):
    assert factory.build_llm_kwargs({"llm_provider": "openrouter", "llm_timeout": value})["timeout"] == expected


@pytest.mark.unit
def test_llm_timeout_unset_leaves_the_client_default():
    assert "timeout" not in factory.build_llm_kwargs({"llm_provider": "google", "llm_timeout": None})


@pytest.mark.unit
@pytest.mark.parametrize("bad", [0, "-5", "soon", True])
def test_llm_timeout_rejects_non_positive_or_non_numeric(bad):
    with pytest.raises(ValueError, match="llm_timeout"):
        factory.build_llm_kwargs({"llm_provider": "google", "llm_timeout": bad})


@pytest.mark.unit
def test_env_var_sets_llm_timeout(monkeypatch):
    for key in default_config_module._ENV_OVERRIDES:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TRADINGAGENTS_LLM_TIMEOUT", "180")
    assert default_config_module.build_default_config()["llm_timeout"] == "180"
