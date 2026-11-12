
import logging
from typing import Any

from .base_client import BaseLLMClient

logger = logging.getLogger(__name__)


def create_llm_client(
    provider: str,
    model: str,
    base_url: str | None = None,
    **kwargs,
) -> BaseLLMClient:
    """Create an LLM client for the specified provider.

    Provider modules are imported lazily so that simply importing this
    factory (e.g. during test collection) does not pull in heavy LLM SDKs
    or fail when their API keys are absent.

    Args:
        provider: LLM provider name
        model: Model name/identifier
        base_url: Optional base URL for API endpoint
        **kwargs: Additional provider-specific arguments

    Returns:
        Configured BaseLLMClient instance

    Raises:
        ValueError: If provider is not supported
    """
    provider_lower = provider.lower()

    # Native (non-OpenAI) APIs are matched first so their string check doesn't
    # import the OpenAI client. Everything else is OpenAI-compatible and routes
    # through the provider registry (single source of truth).
    if provider_lower == "anthropic":
        from .anthropic_client import AnthropicClient
        return AnthropicClient(model, base_url, **kwargs)

    if provider_lower == "google":
        from .google_client import GoogleClient
        return GoogleClient(model, base_url, **kwargs)

    if provider_lower == "azure":
        from .azure_client import AzureOpenAIClient
        return AzureOpenAIClient(model, base_url, **kwargs)

    if provider_lower == "bedrock":
        from .bedrock_client import BedrockClient
        return BedrockClient(model, base_url, **kwargs)

    from .openai_client import OpenAIClient, is_openai_compatible
    if is_openai_compatible(provider_lower):
        return OpenAIClient(model, base_url, provider=provider_lower, **kwargs)

    raise ValueError(f"Unsupported LLM provider: {provider}")


def _coerce_max_retries(value):
    """Validate an ``llm_max_retries`` value to a non-negative int.

    Accepts an int or a numeric string (env vars arrive as strings). Rejects
    booleans and negatives loudly so a misconfiguration fails at startup rather
    than silently disabling retries.
    """
    if isinstance(value, bool):
        raise ValueError(f"llm_max_retries must be an integer, not a boolean: {value!r}")
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"llm_max_retries must be an integer, got {value!r}") from exc
    if n < 0:
        raise ValueError(f"llm_max_retries must be >= 0, got {n}")
    return n


def _coerce_max_tokens(value):
    """Validate a ``max_tokens`` value to a positive int (env vars are strings)."""
    if isinstance(value, bool):
        raise ValueError(f"max_tokens must be an integer, not a boolean: {value!r}")
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"max_tokens must be an integer, got {value!r}") from exc
    if n <= 0:
        raise ValueError(f"max_tokens must be > 0, got {n}")
    return n


def _coerce_timeout(value):
    """Validate an ``llm_timeout`` value to positive seconds (env vars are strings)."""
    if isinstance(value, bool):
        raise ValueError(f"llm_timeout must be a number of seconds, not a boolean: {value!r}")
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"llm_timeout must be a number of seconds, got {value!r}") from exc
    if seconds <= 0:
        raise ValueError(f"llm_timeout must be > 0, got {seconds}")
    return seconds


# Providers that take OpenAI's ``openai_reasoning_effort``.
REASONING_EFFORT_PROVIDERS = ("openai", "chatgpt")


def build_llm_kwargs(config: dict) -> dict[str, Any]:
    """Keyword arguments for ``create_llm_client`` from a TradingAgents config."""
    kwargs = {}
    provider = config.get("llm_provider", "").lower()

    if provider == "google":
        thinking_level = config.get("google_thinking_level")
        if thinking_level:
            kwargs["thinking_level"] = thinking_level

    elif provider in REASONING_EFFORT_PROVIDERS:
        reasoning_effort = config.get("openai_reasoning_effort")
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort

    elif provider == "anthropic":
        effort = config.get("anthropic_effort")
        if effort:
            kwargs["effort"] = effort

    # Sampling temperature is cross-provider: forward it whenever set.
    # float() here so a value coming from a TRADINGAGENTS_TEMPERATURE env
    # string ("0.2") works the same as a programmatic float.
    temperature = config.get("temperature")
    if temperature is not None and temperature != "":
        kwargs["temperature"] = float(temperature)

    # SDK retry budget is cross-provider. Forward it only when explicitly set
    # so each provider keeps its own default (usually 2) otherwise (#1091).
    max_retries = config.get("llm_max_retries")
    if max_retries is not None and max_retries != "":
        kwargs["max_retries"] = _coerce_max_retries(max_retries)

    # Per-request timeout in seconds. None leaves each client's own (600 s);
    # a lower one hands a stalled call to the next llm_fallbacks model sooner.
    timeout = config.get("llm_timeout")
    if timeout is not None and timeout != "":
        kwargs["timeout"] = _coerce_timeout(timeout)

    # Output-token cap is cross-provider, but Gemini names it
    # ``max_output_tokens``; forward under the right key when set (#1204).
    max_tokens = config.get("max_tokens")
    if max_tokens is not None and max_tokens != "":
        key = "max_output_tokens" if provider == "google" else "max_tokens"
        kwargs[key] = _coerce_max_tokens(max_tokens)

    return kwargs


def tier_provider(config: dict, tier: str) -> str:
    """The provider of the ``quick`` or ``deep`` model tier: its own, else ``llm_provider``."""
    return (config.get(f"{tier}_think_provider") or config["llm_provider"]).lower()


def create_tier_client(config: dict, tier: str, **extra) -> BaseLLMClient:
    """The client for the ``quick`` or ``deep`` model tier (#1440).

    A tier on its own provider gets that provider's settings (thinking level,
    reasoning effort, the name of the output-token cap) and its own endpoint,
    else the provider's default: ``backend_url`` belongs to ``llm_provider``.
    """
    provider = tier_provider(config, tier)
    if provider == config["llm_provider"].lower():
        base_url = config.get(f"{tier}_think_backend_url") or config.get("backend_url")
    else:
        base_url = config.get(f"{tier}_think_backend_url")
    kwargs = build_llm_kwargs({**config, "llm_provider": provider})
    return create_llm_client(provider=provider, model=config[f"{tier}_think_llm"], base_url=base_url,
                             **kwargs, **extra)


def parse_llm_fallbacks(value) -> list[tuple[str, str]]:
    """The ``(provider, model)`` pairs of an ``llm_fallbacks`` value, in order.

    Takes a comma-separated string (the ``TRADINGAGENTS_LLM_FALLBACKS`` form) or
    a list of ``"provider:model"`` strings, ``(provider, model)`` pairs or
    ``{"provider": ..., "model": ...}`` dicts. Only the first colon separates
    provider from model, since model ids carry colons (``...:free``).
    """
    if not value:
        return []
    entries = value.split(",") if isinstance(value, str) else list(value)
    pairs = []
    for entry in entries:
        if isinstance(entry, dict):
            provider, model = entry.get("provider"), entry.get("model")
        elif isinstance(entry, (tuple, list)) and len(entry) == 2:
            provider, model = entry
        elif isinstance(entry, str):
            entry = entry.strip()
            if not entry:
                continue
            provider, sep, model = entry.partition(":")
            if not sep:
                model = None
        else:
            provider = model = None
        provider, model = (provider or "").strip().lower(), (model or "").strip()
        if not provider or not model:
            raise ValueError(f"llm_fallbacks entries must be 'provider:model', got {entry!r}")
        pairs.append((provider, model))
    return pairs


def create_tier_llm(config: dict, tier: str, **extra) -> Any:
    """The chat model of the ``quick`` or ``deep`` tier, with ``llm_fallbacks`` behind it."""
    return with_llm_fallbacks(create_tier_client(config, tier, **extra).get_llm(), config, tier, **extra)


def with_llm_fallbacks(llm: Any, config: dict, tier: str, **extra) -> Any:
    """``llm`` (the ``tier``'s own model) with the configured ``llm_fallbacks`` behind it.

    Each fallback runs on its provider's default endpoint with that provider's
    settings, and is tried in order when the model before it raises (a spent
    quota, a rate limit, an outage). A fallback that cannot be built, such as
    one whose API key is not set, is skipped with a warning.
    """
    primary = (tier_provider(config, tier), config[f"{tier}_think_llm"])
    fallbacks = []
    for provider, model in parse_llm_fallbacks(config.get("llm_fallbacks")):
        if (provider, model) == primary:
            continue
        kwargs = build_llm_kwargs({**config, "llm_provider": provider})
        try:
            fallbacks.append(create_llm_client(provider=provider, model=model, **kwargs, **extra).get_llm())
        except Exception as exc:
            logger.warning("LLM fallback %s:%s skipped for the %s tier: %s", provider, model, tier, exc)
    return llm.with_fallbacks(fallbacks) if fallbacks else llm
