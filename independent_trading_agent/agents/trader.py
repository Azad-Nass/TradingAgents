"""Senior Trader: turns a direction into a hypothetical, ATR-anchored plan."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .base import AnalysisContext

NAME, ROLE = "senior_trader", "معامله‌گر ارشد"


@dataclass
class TradePlan:
    direction: int            # +1 long, -1 short
    reference_price: float
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

    def to_dict(self) -> dict:
        return asdict(self)


def make_plan(ctx: AnalysisContext, direction: int, horizon_bars: int, *, stop_hint: float | None = None,
              target_hint: float | None = None) -> TradePlan | None:
    """An ATR-anchored plan; a hinted stop/target (e.g. TradingAgents' own) is used when it is sane."""
    plan = _atr_plan(ctx, direction, horizon_bars)
    if plan is None or (stop_hint is None and target_hint is None):
        return plan
    ref, a = plan.reference_price, ctx.snap["atr14"]
    if stop_hint is not None and 0.5 * a <= (ref - stop_hint) * direction <= 4 * a:
        plan.stop = stop_hint
        plan.risk_per_unit = abs(ref - stop_hint)
        plan.targets = [ref + direction * 2 * plan.risk_per_unit, ref + direction * 3 * plan.risk_per_unit]
        plan.rationale_fa.append("حد ضرر از برنامه تریدر TradingAgents گرفته شد")
    elif stop_hint is not None:
        plan.rationale_fa.append(f"حد ضرر TradingAgents ({stop_hint:,.5g}) خارج از بازه ۰٫۵ تا ۴ ATR بود؛ حد ضرر ATR استفاده شد")
    if target_hint is not None and (target_hint - ref) * direction >= plan.risk_per_unit:
        plan.targets[0] = target_hint
        plan.rationale_fa.append("هدف اول از هدف قیمت مدیر پرتفوی TradingAgents گرفته شد")
    if (plan.targets[1] - plan.targets[0]) * direction <= 0:  # keep target 2 beyond target 1
        plan.targets[1] = plan.targets[0] + direction * plan.risk_per_unit
    plan.reward_risk = round(abs(plan.targets[0] - ref) / plan.risk_per_unit, 2)
    lv = ctx.levels
    if direction > 0:
        obstacle = lv.resistance if lv.resistance is not None and ref < lv.resistance < plan.targets[0] else None
    else:
        obstacle = lv.support if lv.support is not None and plan.targets[0] < lv.support < ref else None
    plan.obstacle = obstacle
    plan.effective_reward_risk = round(abs(obstacle - ref) / plan.risk_per_unit, 2) if obstacle else plan.reward_risk
    return plan


def _atr_plan(ctx: AnalysisContext, direction: int, horizon_bars: int) -> TradePlan | None:
    s, lv = ctx.snap, ctx.levels
    ref, a = s["close"], s["atr14"]
    if not direction or a is None or a <= 0:
        return None
    notes = []
    if direction > 0:
        anchor = lv.support if lv.support is not None and ref - lv.support <= 2.5 * a else None
        stop = (anchor - 0.25 * a) if anchor is not None else ref - 1.5 * a
        stop = min(max(stop, ref - 3 * a), ref - 1.0 * a)
        notes.append(f"حد ضرر {'زیر حمایت ' + format(anchor, ',.5g') if anchor else '۱٫۵ برابر ATR زیر قیمت'} "
                     f"(بین ۱ تا ۳ ATR)")
        risk = ref - stop
        targets = [ref + 2 * risk, ref + 3 * risk]
        obstacle = lv.resistance if lv.resistance is not None and ref < lv.resistance < targets[0] else None
        entry = (ref - 0.25 * a, ref + 0.1 * a)
    else:
        anchor = lv.resistance if lv.resistance is not None and lv.resistance - ref <= 2.5 * a else None
        stop = (anchor + 0.25 * a) if anchor is not None else ref + 1.5 * a
        stop = max(min(stop, ref + 3 * a), ref + 1.0 * a)
        notes.append(f"حد ضرر {'بالای مقاومت ' + format(anchor, ',.5g') if anchor else '۱٫۵ برابر ATR بالای قیمت'} "
                     f"(بین ۱ تا ۳ ATR)")
        risk = stop - ref
        targets = [ref - 2 * risk, ref - 3 * risk]
        obstacle = lv.support if lv.support is not None and targets[0] < lv.support < ref else None
        entry = (ref - 0.1 * a, ref + 0.25 * a)
    notes.append("اهداف در ۲R و ۳R؛ ورود فرضی در نخستین قیمت باز پس از صدور سیگنال")
    eff = abs(obstacle - ref) / risk if obstacle is not None else 2.0
    if obstacle is not None:
        notes.append(f"سطح مخالف {obstacle:,.5g} پیش از هدف اول قرار دارد")
    return TradePlan(direction, ref, entry[0], entry[1], stop, targets, risk, 2.0, round(eff, 2), obstacle,
                     horizon_bars, notes)
