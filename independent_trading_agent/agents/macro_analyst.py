"""Macro Analyst (FRED): rate differentials and inflation for forex, US real yields for gold.

Observations are read as of the analysis date (ALFRED vintages); anything
older than the freshness limit is shown but kept out of the view.
"""
from __future__ import annotations

from .base import AgentOpinion, AnalysisContext, Evidence, not_applicable, score_from

MACRO, MACRO_ROLE = "macro_analyst", "تحلیلگر اقتصاد کلان (FRED)"


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
