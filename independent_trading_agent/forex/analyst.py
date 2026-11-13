"""Forex Analyst: sessions, pip terms, relative currency strength and gap risk."""
from __future__ import annotations

from zoneinfo import ZoneInfo

from ..agents.base import AgentOpinion, AnalysisContext, Evidence, not_applicable
from ..core.markets import SESSION_NAMES_FA, forex_pair, forex_sessions_open, pip_size

NAME, ROLE = "forex_analyst", "تحلیلگر فارکس"


def currency_strength(peers: dict, lookback: int = 20) -> dict[str, float]:
    """Average ``lookback``-bar return of each currency across the given pairs."""
    totals: dict[str, list[float]] = {}
    for sym, df in peers.items():
        pair = forex_pair(sym)
        if not pair or df is None or len(df) <= lookback:
            continue
        ret = float(df["close"].iloc[-1] / df["close"].iloc[-1 - lookback] - 1)
        totals.setdefault(pair[0], []).append(ret)
        totals.setdefault(pair[1], []).append(-ret)
    return {ccy: sum(v) / len(v) for ccy, v in totals.items() if v}


def analyze(ctx: AnalysisContext) -> AgentOpinion:
    if ctx.market.key != "forex":
        return not_applicable(NAME, ROLE, "فقط برای جفت‌ارزها")
    base, quote = forex_pair(ctx.symbol)
    pip = pip_size(ctx.symbol)
    s, src, asof = ctx.snap, ctx.data_source, ctx.snap["date"]
    ev: list[Evidence] = []
    unc: list[str] = []

    sessions = forex_sessions_open(ctx.now)
    names = "، ".join(SESSION_NAMES_FA[x] for x in sessions) or "هیچ سشن اصلی باز نیست"
    ev.append(Evidence(f"سشن‌های باز در زمان تحلیل: {names}", 0, 0, sessions, "ساعت سشن‌ها (محاسبه محلی)"))
    if s["atr14"] is not None:
        ev.append(Evidence(f"ATR14 روزانه ≈ {s['atr14'] / pip:,.0f} پیپ (اندازه پیپ {pip})", 0, 0, s["atr14"] / pip, src, asof))

    strength = currency_strength(ctx.peers)
    if base in strength and quote in strength:
        diff = strength[base] - strength[quote]
        stance = 1 if diff > 0.004 else -1 if diff < -0.004 else 0
        ranked = sorted(strength.items(), key=lambda kv: kv[1], reverse=True)
        ladder = " > ".join(f"{c}" for c, _ in ranked)
        ev.append(Evidence(f"قدرت نسبی ۲۰ کندلی {base} در برابر {quote}: {diff:+.2%} (ترتیب قدرت: {ladder})",
                           stance, 1.0, diff, src, asof))
    else:
        unc.append("قدرت نسبی ارزها محاسبه نشد (جفت‌ارزهای مرجع کافی نبود)")

    ny = ctx.now.astimezone(ZoneInfo("America/New_York"))
    if ny.weekday() == 4 and ny.hour >= 12:
        unc.append("نزدیک پایان معاملات هفتگی: ریسک شکاف قیمت (Gap) در بازگشایی دوشنبه")
    if "JPY" in (base, quote) or "CHF" in (base, quote):
        unc.append("ارزهای امن (JPY/CHF) به شوک‌های ریسک جهانی حساس‌اند")

    stance_score = sum(e.stance * e.weight for e in ev) / max(1.0, sum(e.weight for e in ev if e.stance))
    return AgentOpinion(NAME, ROLE, True, round(stance_score * 0.7, 3), 0.35, ev, unc,
                        f"{base}/{quote}: سشن‌ها، پیپ و قدرت نسبی ارز")
