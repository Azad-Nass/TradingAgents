"""Senior Trader: turns a direction into a hypothetical plan.

Entry is either at the market (the first open after the signal) or, when
TradingAgents' trader names a better price (sell higher / buy lower) within
2 ATR, a limit order at that price that must be filled within the horizon.
Stop and target come from TradingAgents when they are sane, else from ATR
and the nearest swing levels. Simulation only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .base import AnalysisContext

NAME, ROLE = "senior_trader", "معامله‌گر ارشد"
LIMIT_MIN_ATR, LIMIT_MAX_ATR = 0.1, 2.0   # how far a limit entry may sit from the market


@dataclass
class TradePlan:
    direction: int            # +1 long, -1 short
    reference_price: float    # planned entry: the limit price, or the last close for a market entry
    entry_low: float
    entry_high: float
    stop: float
    targets: list[float]
    risk_per_unit: float
    reward_risk: float        # to the first target
    effective_reward_risk: float  # to the nearest opposing level, if it comes first
    obstacle: float | None
    horizon_bars: int
    rationale_fa: list[str]
    entry_type: str = "market"     # "market" | "limit"
    market_price: float | None = None

    @property
    def limit_price(self) -> float | None:
        return self.reference_price if self.entry_type == "limit" else None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["limit_price"] = self.limit_price
        return d


def limit_entry(ctx: AnalysisContext, direction: int, entry_hint: float | None) -> tuple[float | None, str | None]:
    """(limit price, None) when the hinted entry is a sane limit, else (None, reason it was not used)."""
    close, a = ctx.snap["close"], ctx.snap["atr14"]
    if entry_hint is None or not direction or not a:
        return None, None
    better_by = (entry_hint - close) * -direction  # > 0: sell above / buy below the market
    if better_by < LIMIT_MIN_ATR * a:
        return None, (f"قیمت ورود TradingAgents ({entry_hint:,.5g}) نزدیک یا بدتر از قیمت بازار است؛ "
                      "ورود در قیمت بازار فرض شد")
    if better_by > LIMIT_MAX_ATR * a:
        return None, (f"قیمت ورود TradingAgents ({entry_hint:,.5g}) بیش از {LIMIT_MAX_ATR:g} ATR با بازار فاصله دارد؛ "
                      "ورود در قیمت بازار فرض شد")
    return entry_hint, None


def make_plan(ctx: AnalysisContext, direction: int, horizon_bars: int, *, stop_hint: float | None = None,
              target_hint: float | None = None, entry_hint: float | None = None) -> TradePlan | None:
    """An ATR-anchored plan; TradingAgents' entry/stop/target are used where they are sane."""
    limit, why_not = limit_entry(ctx, direction, entry_hint)
    plan = _atr_plan(ctx, direction, horizon_bars, ref=limit)
    if plan is None:
        return None
    if why_not:
        plan.rationale_fa.append(why_not)
    if stop_hint is None and target_hint is None:
        return plan
    ref, a = plan.reference_price, ctx.snap["atr14"]
    if stop_hint is not None and 0.5 * a <= (ref - stop_hint) * direction <= 4 * a:
        plan.stop = stop_hint
        plan.risk_per_unit = abs(ref - stop_hint)
        plan.targets = [ref + direction * 2 * plan.risk_per_unit, ref + direction * 3 * plan.risk_per_unit]
        plan.rationale_fa = [n for n in plan.rationale_fa if "(بین ۱ تا ۳ ATR)" not in n]  # the ATR stop is replaced
        plan.rationale_fa.append(f"حد ضرر {stop_hint:,.5g} از برنامه تریدر TradingAgents گرفته شد")
    elif stop_hint is not None:
        plan.rationale_fa.append(f"حد ضرر TradingAgents ({stop_hint:,.5g}) نسبت به ورود خارج از بازه ۰٫۵ تا ۴ ATR بود؛ "
                                 "حد ضرر ATR استفاده شد")
    if target_hint is not None and (target_hint - ref) * direction >= plan.risk_per_unit:
        plan.targets[0] = target_hint
        plan.rationale_fa.append("هدف اول از هدف قیمت مدیر پرتفوی TradingAgents گرفته شد")
    if (plan.targets[1] - plan.targets[0]) * direction <= 0:  # keep target 2 beyond target 1
        plan.targets[1] = plan.targets[0] + direction * plan.risk_per_unit
    plan.reward_risk = round(abs(plan.targets[0] - ref) / plan.risk_per_unit, 2)
    plan.obstacle = _obstacle(ctx, direction, ref, plan.targets[0])
    plan.rationale_fa = [n for n in plan.rationale_fa if not n.startswith("سطح مخالف")]
    if plan.obstacle is not None:
        plan.rationale_fa.append(f"سطح مخالف {plan.obstacle:,.5g} پیش از هدف اول قرار دارد")
    plan.effective_reward_risk = (round(abs(plan.obstacle - ref) / plan.risk_per_unit, 2) if plan.obstacle
                                  else plan.reward_risk)
    return plan


def _obstacle(ctx: AnalysisContext, direction: int, ref: float, target: float) -> float | None:
    """The nearest level against the trade (resistance for a long, support for a short) before target 1."""
    lv = ctx.levels
    if direction > 0:
        return lv.resistance if lv.resistance is not None and ref < lv.resistance < target else None
    return lv.support if lv.support is not None and target < lv.support < ref else None


def _atr_plan(ctx: AnalysisContext, direction: int, horizon_bars: int, ref: float | None = None) -> TradePlan | None:
    s, lv = ctx.snap, ctx.levels
    close, a = s["close"], s["atr14"]
    if not direction or a is None or a <= 0:
        return None
    entry_type = "limit" if ref is not None else "market"
    ref = close if ref is None else ref
    notes = []
    if direction > 0:
        below = [x for x in lv.supports if x < ref]                 # nearest first
        anchor = below[0] if below and ref - below[0] <= 2.5 * a else None
        stop = (anchor - 0.25 * a) if anchor is not None else ref - 1.5 * a
        stop = min(max(stop, ref - 3 * a), ref - 1.0 * a)
        notes.append(f"حد ضرر {'زیر حمایت ' + format(anchor, ',.5g') if anchor else '۱٫۵ برابر ATR زیر ورود'} "
                     f"(بین ۱ تا ۳ ATR)")
        risk = ref - stop
        targets = [ref + 2 * risk, ref + 3 * risk]
    else:
        above = [x for x in lv.resistances if x > ref]
        anchor = above[0] if above and above[0] - ref <= 2.5 * a else None
        stop = (anchor + 0.25 * a) if anchor is not None else ref + 1.5 * a
        stop = max(min(stop, ref + 3 * a), ref + 1.0 * a)
        notes.append(f"حد ضرر {'بالای مقاومت ' + format(anchor, ',.5g') if anchor else '۱٫۵ برابر ATR بالای ورود'} "
                     f"(بین ۱ تا ۳ ATR)")
        risk = stop - ref
        targets = [ref - 2 * risk, ref - 3 * risk]
    if entry_type == "limit":
        entry = (ref, ref)
        notes.append(f"ورود شرطی (Limit) در {ref:,.5g} طبق برنامه TradingAgents؛ قیمت بازار {close:,.5g}. "
                     "اگر تا پایان افق به این قیمت نرسد، معامله انجام‌نشده حساب می‌شود")
    else:
        entry = (ref - 0.25 * a, ref + 0.1 * a) if direction > 0 else (ref - 0.1 * a, ref + 0.25 * a)
        notes.append("ورود فرضی در نخستین قیمت باز پس از صدور سیگنال")
    notes.append("اهداف در ۲R و ۳R")
    obstacle = _obstacle(ctx, direction, ref, targets[0])
    eff = abs(obstacle - ref) / risk if obstacle is not None else 2.0
    if obstacle is not None:
        notes.append(f"سطح مخالف {obstacle:,.5g} پیش از هدف اول قرار دارد")
    return TradePlan(direction, ref, entry[0], entry[1], stop, targets, risk, 2.0, round(eff, 2), obstacle,
                     horizon_bars, notes, entry_type, close)
