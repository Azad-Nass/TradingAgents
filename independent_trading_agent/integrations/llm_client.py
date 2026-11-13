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


def classify_headlines(llm: LLMClient, subject: str, headlines: list[str]) -> list[dict] | None:
    """Per-headline sentiment in [-1, 1] and relevance in [0, 1] for ``subject``; None on failure."""
    if not headlines or not llm.available:
        return None
    listing = "\n".join(f"{i}. {h}" for i, h in enumerate(headlines))
    system = ("You rate financial news headlines. Answer with JSON only: a list of objects "
              '{"i": index, "sentiment": number from -1 (bearish) to 1 (bullish), "relevance": 0..1}. '
              "Judge only what the headline says about the given instrument; unrelated headlines get relevance 0.")
    try:
        rows = _json_block(llm.chat(system, f"Instrument: {subject}\nHeadlines:\n{listing}", max_tokens=600))
        out = []
        for row in rows:
            i = int(row["i"])
            if 0 <= i < len(headlines):
                out.append({"i": i, "sentiment": max(-1.0, min(1.0, float(row["sentiment"]))),
                            "relevance": max(0.0, min(1.0, float(row.get("relevance", 1))))})
        return out
    except (LLMUnavailable, ValueError, KeyError, TypeError) as exc:
        logger.info("headline classification unavailable: %s", redact(str(exc)))
        return None


def persian_narrative(llm: LLMClient, facts: dict) -> str | None:
    """A short Persian summary of decided facts; None when no model answers."""
    if not llm.available:
        return None
    system = ("تو یک تحلیلگر مالی هستی. فقط بر اساس داده JSON داده‌شده، یک خلاصه فارسی روان در حداکثر ۱۲۰ کلمه بنویس. "
              "هیچ عدد، قیمت، خبر یا ادعایی که در JSON نیست اضافه نکن. تصمیم نهایی را تغییر نده. "
              "توصیه قطعی یا تضمین سود نده. نماد و اصطلاحات فنی را انگلیسی نگه دار.")
    try:
        text = llm.chat(system, json.dumps(facts, ensure_ascii=False), max_tokens=500, temperature=0.3)
        return text.strip()
    except LLMUnavailable as exc:
        logger.info("narrative unavailable: %s", exc)
        return None
