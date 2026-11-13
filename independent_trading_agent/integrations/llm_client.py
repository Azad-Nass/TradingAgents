"""Optional LLM client over OpenAI-compatible chat endpoints (stdlib only).

Used for two narrow jobs: classifying headline sentiment and phrasing a
Persian summary of evidence that is already decided. Models are tried in the
configured order; a call budget caps the run. Keys are read from
``INDEPENDENT_AGENT_<PROVIDER>_API_KEY`` and never logged.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request

from ..config.settings import secret
from ..core.runtime import redact

logger = logging.getLogger(__name__)

PROVIDERS = {
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
}


class LLMUnavailable(RuntimeError):
    pass


def parse_chain(chain: str) -> list[tuple[str, str]]:
    pairs = []
    for entry in chain.split(","):
        provider, sep, model = entry.strip().partition(":")
        if sep and provider.strip().lower() in PROVIDERS and model.strip():
            pairs.append((provider.strip().lower(), model.strip()))
    return pairs


class LLMClient:
    def __init__(self, chain: str, max_calls: int, timeout: float):
        self.chain = [(p, m) for p, m in parse_chain(chain) if secret(PROVIDERS[p][1])]
        self.max_calls = max_calls
        self.timeout = timeout
        self.calls = 0
        self.used_models: list[str] = []
        self.errors: list[str] = []

    @property
    def available(self) -> bool:
        return bool(self.chain) and self.calls < self.max_calls

    def chat(self, system: str, user: str, *, max_tokens: int = 800, temperature: float = 0.2) -> str:
        if not self.chain:
            raise LLMUnavailable("no LLM provider with a key is configured")
        for provider, model in self.chain:
            if self.calls >= self.max_calls:
                raise LLMUnavailable(f"LLM call budget of {self.max_calls} used up")
            self.calls += 1
            base, key_name = PROVIDERS[provider]
            body = json.dumps({"model": model, "temperature": temperature, "max_tokens": max_tokens,
                               "messages": [{"role": "system", "content": system},
                                            {"role": "user", "content": user}]}).encode()
            req = urllib.request.Request(f"{base}/chat/completions", data=body, method="POST", headers={
                "Content-Type": "application/json", "Authorization": f"Bearer {secret(key_name)}",
                "User-Agent": "independent-trading-agent/0.1"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
                if text.strip():
                    self.used_models.append(f"{provider}:{model}")
                    return text
                self.errors.append(f"{provider}:{model}: empty answer")
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                detail = exc.read().decode("utf-8", "replace")[:200] if isinstance(exc, urllib.error.HTTPError) else ""
                msg = redact(f"{provider}:{model}: {type(exc).__name__} {exc} {detail}")
                self.errors.append(msg)
                logger.info("LLM call failed, trying next model: %s", msg)
        raise LLMUnavailable("every configured model failed")


def _json_block(text: str):
    match = re.search(r"\[.*\]|\{.*\}", text, re.S)
    if not match:
        raise ValueError("no JSON in answer")
    return json.loads(match.group(0))



def rate_report_sentiment(llm: LLMClient, subject: str, text: str) -> dict | None:
    """Sentiment of a news report for ``subject``: {"sentiment": -1..1, "reason_fa": str}; None on failure."""
    if not text.strip() or not llm.available:
        return None
    system = ("You rate the market sentiment that a news report implies for one instrument. Answer with JSON only: "
              '{"sentiment": number from -1 (clearly bearish) to 1 (clearly bullish), '
              '"reason_fa": "one short sentence in Persian naming the main driver"}. '
              "Use only what the report says; if it is mixed or unclear, answer close to 0.")
    try:
        prompt = f"Instrument: {subject}\n\nReport:\n{text[:6000]}"
        data = _json_block(llm.chat(system, prompt, max_tokens=400))
        return {"sentiment": max(-1.0, min(1.0, float(data["sentiment"]))),
                "reason_fa": str(data.get("reason_fa", ""))[:300]}
    except (LLMUnavailable, ValueError, KeyError, TypeError) as exc:
        logger.info("report sentiment unavailable: %s", redact(str(exc)))
        return None
