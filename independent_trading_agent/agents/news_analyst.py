"""News Intelligence Analyst and Market Sentiment Analyst.

Headlines come from the provider with their publish time; anything older
than the configured age is dropped, never shown as fresh. Sentiment is either
an LLM's classification of the headlines (when enabled) or a small keyword
lexicon, and the method used is always stated.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from .base import AgentOpinion, AnalysisContext, Evidence

NEWS, NEWS_ROLE = "news_analyst", "تحلیلگر هوشمند اخبار"
SENT, SENT_ROLE = "sentiment_analyst", "تحلیلگر احساسات بازار"

_POS = {"surge", "surges", "rally", "rallies", "beat", "beats", "record", "upgrade", "upgraded", "gain",
        "gains", "jump", "jumps", "soar", "soars", "strong", "bullish", "rise", "rises", "rebound",
        "outperform", "growth", "higher", "boost", "approval", "wins"}
_NEG = {"plunge", "plunges", "fall", "falls", "drop", "drops", "miss", "misses", "downgrade", "downgraded",
        "loss", "losses", "slump", "weak", "bearish", "cut", "cuts", "lawsuit", "probe", "recall", "decline",
        "declines", "lower", "selloff", "sell-off", "tumble", "tumbles", "warning", "fears", "slips", "risk"}


def recent_news(items: list[dict], now: datetime, max_age_days: int) -> list[dict]:
    cutoff = now - timedelta(days=max_age_days)
    fresh = []
    for item in items:
        try:
            published = datetime.fromisoformat(item["published_utc"])
        except (KeyError, ValueError):
            continue
        if cutoff <= published <= now + timedelta(minutes=5):
            fresh.append(item)
    return sorted(fresh, key=lambda i: i["published_utc"], reverse=True)


def lexicon_score(title: str) -> int:
    words = set(re.findall(r"[a-z\-]+", title.lower()))
    pos, neg = len(words & _POS), len(words & _NEG)
    return (pos > neg) - (neg > pos)


def analyze_news(ctx: AnalysisContext) -> AgentOpinion:
    items = ctx.news
    if not items:
        return AgentOpinion(NEWS, NEWS_ROLE, True, 0.0, 0.0, [], ["خبر تازه‌ای در بازه تعیین‌شده یافت نشد"],
                            "خبری برای ارزیابی وجود ندارد")
    ev = []
    for item in items[:8]:
        sent = item.get("sentiment")
        stance = 0 if sent is None else (1 if sent > 0.2 else -1 if sent < -0.2 else 0)
        ev.append(Evidence(f"«{item['title']}» — {item['publisher']}", stance, 0.5 * (item.get("relevance") or 1.0),
                           sent, item.get("source", ""), item["published_utc"]))
    return AgentOpinion(NEWS, NEWS_ROLE, True, 0.0, 0.3, ev,
                        ["عنوان خبر به‌تنهایی جزئیات و اثر واقعی رویداد را نشان نمی‌دهد"],
                        f"{len(items)} خبر تازه؛ اثر جهت‌دار در تحلیلگر احساسات محاسبه می‌شود")


def analyze_sentiment(ctx: AnalysisContext) -> AgentOpinion:
    scored = [i for i in ctx.news if i.get("sentiment") is not None]
    if not scored:
        return AgentOpinion(SENT, SENT_ROLE, True, 0.0, 0.0, [], ["احساسات بازار قابل سنجش نبود (خبر کافی نیست)"],
                            "احساسات: ناموجود")
    weights = [(i.get("relevance") or 1.0) for i in scored]
    avg = sum(i["sentiment"] * w for i, w in zip(scored, weights, strict=True)) / sum(weights)
    method = ctx.news_sentiment_method
    method_fa = ("طبقه‌بندی عنوان‌ها با مدل زبانی" if method == "llm"
                 else "روش ساده واژه‌محور (heuristic) — اعتبار پایین")
    label = "مثبت" if avg > 0.15 else "منفی" if avg < -0.15 else "خنثی"
    ev = [Evidence(f"میانگین احساسات {len(scored)} عنوان خبری: {avg:+.2f} ({label})",
                   1 if avg > 0.15 else -1 if avg < -0.15 else 0, 1.0, avg, method_fa)]
    conf = 0.4 if method == "llm" else 0.2
    return AgentOpinion(SENT, SENT_ROLE, True, round(max(-1, min(1, avg)), 3), conf, ev,
                        [f"روش سنجش: {method_fa}"], f"احساسات بازار: {label}")
