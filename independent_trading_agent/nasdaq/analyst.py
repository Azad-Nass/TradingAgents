"""Stock-market analyst for NASDAQ (and NYSE, TSX, TSXV): liquidity, earnings
proximity and relative strength against the market's benchmark ETF."""
from __future__ import annotations

from datetime import date

from ..agents.base import AgentOpinion, AnalysisContext, Evidence, not_applicable

NAME, ROLE = "stock_market_analyst", "تحلیلگر بازار سهام (NASDAQ/NYSE/TSX)"


def analyze(ctx: AnalysisContext, min_dollar_volume: float, horizon_days: int) -> AgentOpinion:
    if ctx.market.asset_class != "stock":
        return not_applicable(NAME, ROLE, "فقط برای سهام و ETF")
    s, src, asof = ctx.snap, ctx.data_source, ctx.snap["date"]
    ev: list[Evidence] = []
    unc: list[str] = []
    ccy = ctx.market.currency

    dv = s.get("dollar_vol20")
    if dv is not None:
        liquid = dv >= min_dollar_volume
        ev.append(Evidence(f"میانگین ارزش معاملات روزانه (۲۰ روز): {dv / 1e6:,.1f} میلیون {ccy}"
                           f"{'' if liquid else ' — کمتر از حد نقدشوندگی'}", 0, 0, dv, src, asof))
        if not liquid:
            unc.append("نقدشوندگی پایین: لغزش قیمت و ریسک خروج بالاست")
    else:
        unc.append("ارزش معاملات قابل محاسبه نیست")

    bench = ctx.benchmark
    if bench is not None and len(bench) > 60 and s.get("ret60") is not None and ctx.yahoo != ctx.market.benchmark:
        b = float(bench["close"].iloc[-1] / bench["close"].iloc[-61] - 1)
        rel = s["ret60"] - b
        ev.append(Evidence(f"قدرت نسبی ۶۰ کندلی در برابر {ctx.market.benchmark}: {rel:+.1%} "
                           f"(نماد {s['ret60']:+.1%}، شاخص {b:+.1%})", 1 if rel > 0.02 else -1 if rel < -0.02 else 0,
                           1.0, rel, src, asof))

    f = ctx.fundamentals or {}
    if f.get("nextEarningsDate"):
        try:
            when = date.fromisoformat(str(f["nextEarningsDate"])[:10])
            days = (when - ctx.now.date()).days
            if 0 <= days <= horizon_days * 1.5:
                ev.append(Evidence(f"گزارش درآمد بعدی در {when.isoformat()} ({days} روز دیگر) — داخل افق معامله", 0, 0,
                                   when.isoformat(), f.get("_source", ""), f.get("_fetched_utc")))
                unc.append("گزارش درآمد داخل افق زمانی است: ریسک شکاف قیمت")
        except ValueError:
            pass
    if f.get("beta") is not None:
        ev.append(Evidence(f"بتا: {f['beta']:.2f}", 0, 0, f["beta"], f.get("_source", ""), f.get("_fetched_utc")))
    if f.get("sector"):
        ev.append(Evidence(f"بخش: {f['sector']} / {f.get('industry', '')}", 0, 0, f["sector"], f.get("_source", "")))
    if ctx.market.key == "tsxv":
        unc.append("TSXV: شرکت‌های کوچک با نقدشوندگی کم و نوسان بالا")

    directional = [e for e in ev if e.stance]
    score = sum(e.stance for e in directional) / len(directional) if directional else 0.0
    return AgentOpinion(NAME, ROLE, True, round(score * 0.6, 3), 0.35, ev, unc,
                        "نقدشوندگی، فاصله تا گزارش درآمد و قدرت نسبی")
