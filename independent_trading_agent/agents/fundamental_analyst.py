"""Fundamental Analyst (companies) and Macro Analyst (forex).

Company figures come from the provider's current quote summary, so they are
not point-in-time and are used for live analysis only (never in backtests).
Forex uses central-bank-driven short rates and inflation from FRED, read as
of the analysis date when a FRED key is configured; otherwise it says so.
"""
from __future__ import annotations

from .base import AgentOpinion, AnalysisContext, Evidence, not_applicable, score_from

FUND, FUND_ROLE = "fundamental_analyst", "تحلیلگر بنیادی"
MACRO, MACRO_ROLE = "macro_analyst", "تحلیلگر اقتصاد کلان"


def _pct(v):
    return f"{v * 100:.1f}%"


def analyze_company(ctx: AnalysisContext) -> AgentOpinion:
    if ctx.market.asset_class != "stock":
        return not_applicable(FUND, FUND_ROLE, "تحلیل بنیادی شرکتی برای این دارایی نامرتبط است")
    f = ctx.fundamentals or {}
    if not f or all(k.startswith("_") for k in f):
        return AgentOpinion(FUND, FUND_ROLE, True, 0.0, 0.0, [], ["داده بنیادی دریافت نشد"],
                            "داده بنیادی در دسترس نیست؛ این بخش در تصمیم اثری ندارد")
    if f.get("quoteType") == "ETF" or ctx.symbol.upper() in ("QQQ", "SPY", "XIU.TO"):
        return not_applicable(FUND, FUND_ROLE, "ETF است؛ تحلیل بنیادی تک‌شرکتی نامرتبط است")
    src, asof = f.get("_source", "provider"), f.get("_fetched_utc")
    ev: list[Evidence] = []

    def add(text, stance, weight=1.0, value=None):
        ev.append(Evidence(text, stance, weight, value, src, asof))

    pe = f.get("trailingPE")
    if pe is not None:
        if pe <= 0:
            add(f"P/E منفی ({pe:.1f}) — شرکت زیان‌ده است", -1, 1.0, pe)
        elif pe < 15:
            add(f"P/E = {pe:.1f} — ارزش‌گذاری پایین نسبت به بازار", 1, 0.75, pe)
        elif pe > 45:
            add(f"P/E = {pe:.1f} — ارزش‌گذاری بالا؛ حساس به ناامیدی از رشد", -1, 0.75, pe)
        else:
            add(f"P/E = {pe:.1f} — در محدوده معمول", 0, 0, pe)
    if f.get("forwardPE") and pe and pe > 0:
        add(f"P/E آتی = {f['forwardPE']:.1f} ({'رشد سود مورد انتظار' if f['forwardPE'] < pe else 'کاهش سود مورد انتظار'})",
            1 if f["forwardPE"] < pe else -1, 0.5, f["forwardPE"])
    if f.get("priceToBook") is not None:
        add(f"P/B = {f['priceToBook']:.2f}", 0, 0, f["priceToBook"])
    if f.get("trailingEps") is not None:
        add(f"EPS دوازده‌ماهه = {f['trailingEps']:.2f}", 1 if f["trailingEps"] > 0 else -1, 0.5, f["trailingEps"])
    g = f.get("revenueGrowth")
    if g is not None:
        add(f"رشد درآمد سالانه: {_pct(g)}", 1 if g > 0.08 else -1 if g < 0 else 0, 1.0, g)
    eg = f.get("earningsGrowth")
    if eg is not None:
        add(f"رشد سود: {_pct(eg)}", 1 if eg > 0.08 else -1 if eg < 0 else 0, 0.75, eg)
    pm = f.get("profitMargins")
    if pm is not None:
        add(f"حاشیه سود خالص: {_pct(pm)}", 1 if pm > 0.15 else -1 if pm < 0 else 0, 0.75, pm)
    roe = f.get("returnOnEquity")
    if roe is not None:
        add(f"ROE: {_pct(roe)}", 1 if roe > 0.15 else -1 if roe < 0 else 0, 0.5, roe)
    de = f.get("debtToEquity")
    if de is not None:
        add(f"نسبت بدهی به حقوق صاحبان سهام: {de:.0f}%", -1 if de > 200 else 0, 0.75, de)
    cr = f.get("currentRatio")
    if cr is not None:
        add(f"نسبت جاری: {cr:.2f}", -1 if cr < 1 else 0, 0.5, cr)
    fcf = f.get("freeCashflow")
    if fcf is not None:
        add(f"جریان نقدی آزاد: {fcf / 1e9:,.2f} میلیارد", 1 if fcf > 0 else -1, 0.75, fcf)

    score, agreement = score_from(ev)
    unc = ["ارقام بنیادی از خلاصه فعلی Yahoo است (point-in-time نیست) و مقایسه با همتایان انجام نشده است"]
    conf = round(min(0.6, 0.25 + 0.35 * agreement), 2)
    return AgentOpinion(FUND, FUND_ROLE, True, round(score * 0.8, 3), conf, ev, unc,
                        f"کیفیت/ارزش‌گذاری: امتیاز {score:+.2f}")


def _gold_macro(m: dict) -> AgentOpinion:
    ry, prev, chg = m["real_yield"], m["real_yield_prev"], m["change"]
    unc = ["بازده واقعی تنها عامل کلان طلا نیست؛ خرید بانک‌های مرکزی و تقاضای امن لحاظ نشده است"]
    if m.get("stale"):
        unc.append("آخرین داده بازده واقعی بیش از ۱۰ روز قدیمی است؛ در تصمیم استفاده نشد")
        stance = 0
    else:
        stance = -1 if chg > 0.10 else 1 if chg < -0.10 else 0
    effect = "افزایش؛ فشار بر طلا" if stance < 0 else "کاهش؛ حمایت از طلا" if stance > 0 else "بدون تغییر معنادار"
    ev = [Evidence(f"بازده واقعی ۱۰ ساله آمریکا (TIPS): {ry['value']:.2f}% در {ry['date']}، تغییر {chg:+.2f} "
                   f"واحد درصد نسبت به {prev['date']} ({effect})", stance, 1.0, chg, f"FRED {m['series']}",
                   m.get("as_of"))]
    score, _ = score_from(ev)
    return AgentOpinion(MACRO, MACRO_ROLE, True, round(score * 0.6, 3), 0.4 if stance else 0.3, ev, unc,
                        "بازده واقعی اوراق آمریکا (مهم‌ترین عامل کلان طلا)")


def analyze_macro(ctx: AnalysisContext) -> AgentOpinion:
    if ctx.market.asset_class != "forex":
        return not_applicable(MACRO, MACRO_ROLE, "این بخش فقط برای Forex استفاده می‌شود")
    m = ctx.macro
    if not m or not m.get("available"):
        reason = (m or {}).get("reason_fa", "کلید FRED تنظیم نشده است")
        return AgentOpinion(MACRO, MACRO_ROLE, True, 0.0, 0.0, [], [reason],
                            "داده اقتصاد کلان (نرخ بهره و تورم) در دسترس نیست؛ در تصمیم اثری ندارد")
    ev: list[Evidence] = []
    if m.get("kind") == "metal":
        return _gold_macro(m)
    base, quote = m["base"], m["quote"]
    rb, rq = m.get("rate_base"), m.get("rate_quote")
    unc = ["انتظارات بازار از سیاست پولی آینده لحاظ نشده است"]
    for ccy, r in ((base, rb), (quote, rq)):
        if r:
            ev.append(Evidence(f"نرخ بهره {ccy}: {r['value']:.2f}% — {r['kind_fa']}، مشاهده {r['date']}"
                               f"{' (کهنه؛ در تصمیم استفاده نشد)' if r['stale'] else ''}", 0, 0, r["value"],
                               f"FRED {r['series']}", m.get("as_of")))
    if rb and rq and not rb["stale"] and not rq["stale"]:
        diff = rb["value"] - rq["value"]
        stance = 1 if diff > 0.5 else -1 if diff < -0.5 else 0
        ev.append(Evidence(f"اختلاف نرخ بهره {base}−{quote}: {diff:+.2f} واحد درصد", stance, 1.0, diff,
                           "FRED", m.get("as_of")))
        if rb.get("category") != rq.get("category"):
            unc.append("دو نرخ از یک نوع نیستند (سیاستی در برابر بین‌بانکی)؛ مقایسه تقریبی است")
    else:
        unc.append("دست‌کم یکی از نرخ‌های بهره کهنه است (بیش از ۱۲۰ روز)؛ اختلاف نرخ در تصمیم استفاده نشد")
    for ccy, key in ((base, "cpi_base"), (quote, "cpi_quote")):
        c = m.get(key)
        if c and not c.get("stale"):
            ev.append(Evidence(f"تورم سالانه {ccy}: {c['value']:.1f}% (مشاهده {c['date']})", 0, 0, c["value"],
                               f"FRED {c['series']}", m.get("as_of")))
        elif c:
            unc.append(f"آخرین داده تورم {ccy} مربوط به {c['date']} است (کهنه)")
    score, _ = score_from(ev)
    return AgentOpinion(MACRO, MACRO_ROLE, True, round(score * 0.6, 3), 0.4 if ev else 0.0, ev, unc,
                        "تفاوت نرخ بهره (Carry) و تورم")
