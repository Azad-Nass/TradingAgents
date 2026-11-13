"""Crypto analyst: strength against BTC, volatility regime and 24/7 risk."""
from __future__ import annotations

from ..agents.base import AgentOpinion, AnalysisContext, Evidence, not_applicable

NAME, ROLE = "crypto_analyst", "تحلیلگر رمزارز"


def analyze(ctx: AnalysisContext) -> AgentOpinion:
    if ctx.market.key != "crypto":
        return not_applicable(NAME, ROLE, "فقط برای رمزارزها")
    s, src, asof = ctx.snap, ctx.data_source, ctx.snap["date"]
    ev: list[Evidence] = []
    unc = ["بازار ۲۴ ساعته است؛ حرکت‌های شدید آخر هفته و ریسک صرافی/قانون‌گذاری وجود دارد"]

    bench = ctx.benchmark
    if bench is not None and ctx.yahoo != "BTC-USD" and len(bench) > 30 and s.get("ret20") is not None:
        b = float(bench["close"].iloc[-1] / bench["close"].iloc[-21] - 1)
        rel = s["ret20"] - b
        ev.append(Evidence(f"قدرت نسبی ۲۰ روزه در برابر BTC: {rel:+.1%}", 1 if rel > 0.03 else -1 if rel < -0.03 else 0,
                           1.0, rel, src, asof))
    if s.get("vol20") is not None:
        ev.append(Evidence(f"نوسان سالانه‌شده ۲۰ روزه: {s['vol20']:.0%}", 0, 0, s["vol20"], src, asof))
        if s["vol20"] > 1.0:
            unc.append("نوسان بسیار بالا (بیش از ۱۰۰٪ سالانه)")
    directional = [e for e in ev if e.stance]
    score = sum(e.stance for e in directional) / len(directional) if directional else 0.0
    return AgentOpinion(NAME, ROLE, True, round(score * 0.6, 3), 0.3, ev, unc, "قدرت نسبی در برابر BTC و رژیم نوسان")
