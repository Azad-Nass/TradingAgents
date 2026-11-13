"""Market Sentiment Analyst: Gemini (or the next model in the chain) rates the
news report that the TradingAgents News Analyst wrote for this run."""
from __future__ import annotations

from ..integrations.llm_client import LLMClient, rate_report_sentiment
from .base import AgentOpinion, Evidence

NAME, ROLE = "sentiment_analyst", "تحلیلگر احساسات بازار (Gemini)"


def analyze(llm: LLMClient | None, subject: str, ta_result: dict | None) -> AgentOpinion:
    reports = (ta_result or {}).get("reports") or {}
    text = "\n\n".join(t for t in (reports.get("news_report"), reports.get("sentiment_report")) if t)
    if not text:
        return AgentOpinion(NAME, ROLE, True, 0.0, 0.0, [], ["گزارش خبری TradingAgents در دسترس نبود"],
                            "احساسات: ناموجود")
    if llm is None:
        return AgentOpinion(NAME, ROLE, True, 0.0, 0.0, [], ["مدل زبانی برای سنجش احساسات فعال نیست"],
                            "احساسات: ناموجود")
    rated = rate_report_sentiment(llm, subject, text)
    if rated is None:
        return AgentOpinion(NAME, ROLE, True, 0.0, 0.0, [], ["مدل زبانی پاسخ قابل استفاده نداد"], "احساسات: ناموجود")
    s = rated["sentiment"]
    label = "مثبت" if s > 0.15 else "منفی" if s < -0.15 else "خنثی"
    model = llm.used_models[-1] if llm.used_models else "LLM"
    ev = [Evidence(f"احساسات گزارش خبری: {s:+.2f} ({label}) — {rated['reason_fa']}",
                   1 if s > 0.15 else -1 if s < -0.15 else 0, 1.0, s, f"{model} روی گزارش خبری TradingAgents",
                   (ta_result or {}).get("trade_date"))]
    return AgentOpinion(NAME, ROLE, True, round(s, 3), 0.4, ev,
                        ["برداشت مدل زبانی از یک گزارش متنی است، نه شمارش مستقیم اخبار"], f"احساسات: {label}")
