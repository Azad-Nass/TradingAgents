"""Technical Analyst: trend, momentum, structure, volatility and volume."""
from __future__ import annotations

from .base import AgentOpinion, AnalysisContext, Evidence, score_from

NAME, ROLE = "technical_analyst", "تحلیلگر تکنیکال"


def _fmt(v, digits=4):
    return "ناموجود" if v is None else f"{v:,.{digits}f}"


def analyze(ctx: AnalysisContext) -> AgentOpinion:
    s, lv = ctx.snap, ctx.levels
    src, asof = ctx.data_source, s["date"]
    digits = 5 if ctx.market.asset_class == "forex" else 2
    ev: list[Evidence] = []
    unc: list[str] = []

    def add(text, stance=0, weight=1.0, value=None):
        ev.append(Evidence(text, stance, weight, value, src, asof))

    close = s["close"]
    # Trend
    if s["sma50"] is not None:
        up = close > s["sma50"]
        add(f"قیمت {'بالای' if up else 'زیر'} SMA50 ({_fmt(s['sma50'], digits)})", 1 if up else -1, 1.0, s["sma50"])
    if s["sma50"] is not None and s["sma200"] is not None:
        up = s["sma50"] > s["sma200"]
        add(f"SMA50 {'بالای' if up else 'زیر'} SMA200 ({_fmt(s['sma200'], digits)}) — روند بلندمدت "
            f"{'صعودی' if up else 'نزولی'}", 1 if up else -1, 1.5, s["sma200"])
    else:
        unc.append("SMA200 به‌دلیل کمبود داده محاسبه نشد")
    if s["ema20"] is not None and s["ema20_prev5"] is not None:
        slope = (s["ema20"] - s["ema20_prev5"]) / s["ema20_prev5"]
        add(f"شیب EMA20 در ۵ کندل اخیر: {slope:+.2%}", 1 if slope > 0 else -1 if slope < 0 else 0, 1.0, slope)

    # Momentum
    r = s["rsi14"]
    if r is not None:
        if r >= 70:
            add(f"RSI14 = {r:.1f} — اشباع خرید؛ مومنتوم قوی ولی ریسک اصلاح", 0, 0, r)
            unc.append("RSI در محدوده اشباع خرید است")
        elif r <= 30:
            add(f"RSI14 = {r:.1f} — اشباع فروش؛ فشار فروش قوی ولی احتمال برگشت", 0, 0, r)
            unc.append("RSI در محدوده اشباع فروش است")
        elif r > 55:
            add(f"RSI14 = {r:.1f} — مومنتوم مثبت", 1, 1.0, r)
        elif r < 45:
            add(f"RSI14 = {r:.1f} — مومنتوم منفی", -1, 1.0, r)
        else:
            add(f"RSI14 = {r:.1f} — خنثی", 0, 0, r)
    h, hp = s["macd_hist"], s["macd_hist_prev"]
    if h is not None:
        rising = hp is not None and h > hp
        add(f"هیستوگرام MACD = {h:+.5f} ({'در حال افزایش' if rising else 'در حال کاهش'})",
            1 if h > 0 else -1, 1.0, h)

    # Structure
    if lv.breakout == "up":
        add(f"شکست سقف ۲۰ کندل قبلی ({_fmt(lv.high_20, digits)}) با بسته‌شدن بالای آن", 1, 1.5, lv.high_20)
    elif lv.breakout == "down":
        add(f"شکست کف ۲۰ کندل قبلی ({_fmt(lv.low_20, digits)}) با بسته‌شدن زیر آن", -1, 1.5, lv.low_20)
    if lv.failed_breakout == "up":
        add("شکست ناموفق سقف در ۵ کندل اخیر (بازگشت به زیر سطح) — علامت نزولی", -1, 1.25)
    elif lv.failed_breakout == "down":
        add("شکست ناموفق کف در ۵ کندل اخیر (بازگشت به بالای سطح) — علامت صعودی", 1, 1.25)
    pb = s["bb_pct_b"]
    if pb is not None:
        where = "بالای باند بالایی" if pb > 1 else "زیر باند پایینی" if pb < 0 else f"{pb:.0%} از عرض باند"
        add(f"موقعیت در Bollinger Bands: {where}", 0, 0, pb)
    if lv.support is not None or lv.resistance is not None:
        add(f"نزدیک‌ترین حمایت: {_fmt(lv.support, digits)} | نزدیک‌ترین مقاومت: {_fmt(lv.resistance, digits)}", 0, 0)

    # Volatility and volume
    if s["atr_pct"] is not None:
        med = s["atr_pct_median_1y"]
        ratio = s["atr_pct"] / med if med else None
        txt = f"ATR14 = {_fmt(s['atr14'], digits)} ({s['atr_pct']:.2%} قیمت)"
        if ratio:
            txt += f"؛ {ratio:.1f} برابر میانه یک‌ساله"
            if ratio > 1.8:
                unc.append("نوسان بسیار بالاتر از معمول است")
        add(txt, 0, 0, s["atr_pct"])
    if ctx.quality.has_volume and s["vol_z"] is not None:
        z = s["vol_z"]
        day_dir = 1 if (s["ret1"] or 0) > 0 else -1
        if z >= 2:
            add(f"حجم غیرعادی: z-score = {z:.1f} همراه با کندل {'مثبت' if day_dir > 0 else 'منفی'}", day_dir, 1.0, z)
        else:
            add(f"حجم معاملات: z-score = {z:.1f} (عادی)", 0, 0, z)
        if s["vwap20"] is not None:
            above = close > s["vwap20"]
            add(f"قیمت {'بالای' if above else 'زیر'} VWAP بیست‌روزه ({_fmt(s['vwap20'], digits)})",
                1 if above else -1, 0.5, s["vwap20"])
    elif ctx.market.asset_class == "forex":
        unc.append("Forex حجم متمرکز ندارد؛ VWAP و تحلیل حجم قابل محاسبه نیست")
    else:
        unc.append("داده حجم کافی نیست؛ VWAP و تحلیل حجم محاسبه نشد")

    score, agreement = score_from(ev)
    quality_factor = 0.7 if ctx.quality.warnings else 1.0
    confidence = round(min(1.0, 0.35 + 0.55 * agreement) * quality_factor, 2)
    trend = "صعودی" if score > 0.25 else "نزولی" if score < -0.25 else "خنثی/رنج"
    return AgentOpinion(NAME, ROLE, True, round(score, 3), confidence, ev, unc,
                        f"جمع‌بندی تکنیکال: {trend} (امتیاز {score:+.2f})")
