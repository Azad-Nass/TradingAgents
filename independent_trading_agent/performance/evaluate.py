"""Signal evaluation and performance metrics.

Rules, fixed in advance so nothing is fitted after the fact:
- Entry is the open of the first bar dated after the signal's data bar.
  Bars at or before ``data_as_of`` are never used.
- Long: a bar whose low reaches the stop exits at the stop (or at the open if
  it gapped through); else a high reaching target 1 exits there. If both
  happen in one bar the stop is assumed first. Shorts mirror this.
- Otherwise the trade closes at the close of bar ``horizon_bars``.
- Round-trip costs (spread, commission, slippage) come off every trade.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import pandas as pd


@dataclass
class Evaluation:
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    exit_reason: str        # stop | target | horizon
    bars_held: int
    gross_return: float
    cost: float
    net_return: float
    r_multiple: float

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate_signal(*, direction: int, data_as_of: str, stop: float, target: float, horizon_bars: int,
                    bars: pd.DataFrame, cost: float) -> Evaluation | None:
    """The outcome once ``horizon_bars`` bars after the signal exist (or the stop/target hit); else None."""
    if direction == 0:
        return None
    after = bars[bars.index.normalize() > pd.Timestamp(data_as_of).normalize()]
    if after.empty:
        return None
    entry_bar = after.iloc[0]
    entry = float(entry_bar["open"])
    risk = abs(entry - stop)
    if risk <= 0 or entry <= 0:
        return None
    first = after.index[0].date().isoformat()
    if (direction > 0 and not stop < entry < target) or (direction < 0 and not target < entry < stop):
        # The market opened beyond the stop or the target: the plan no longer applies; costs are still paid.
        return Evaluation(first, round(entry, 6), first, round(entry, 6), "invalid_at_entry", 0, 0.0,
                          round(cost, 6), round(-cost, 6), round(-cost * entry / risk, 3))
    exit_price, reason, held = None, None, 0
    for i, (ts, bar) in enumerate(after.iloc[:horizon_bars].iterrows()):
        held = i + 1
        o, h, low = float(bar["open"]), float(bar["high"]), float(bar["low"])
        if direction > 0:
            if low <= stop:
                exit_price, reason = (min(o, stop) if i > 0 else stop), "stop"
            elif h >= target:
                exit_price, reason = (max(o, target) if i > 0 else target), "target"
        else:
            if h >= stop:
                exit_price, reason = (max(o, stop) if i > 0 else stop), "stop"
            elif low <= target:
                exit_price, reason = (min(o, target) if i > 0 else target), "target"
        if reason:
            exit_ts = ts
            break
    else:
        if len(after) < horizon_bars:
            return None  # still open
        exit_ts = after.index[horizon_bars - 1]
        exit_price, reason, held = float(after["close"].iloc[horizon_bars - 1]), "horizon", horizon_bars
    gross = direction * (exit_price - entry) / entry
    net = gross - cost
    r_mult = net * entry / risk
    return Evaluation(after.index[0].date().isoformat(), round(entry, 6), exit_ts.date().isoformat(),
                      round(exit_price, 6), reason, held, round(gross, 6), round(cost, 6), round(net, 6),
                      round(r_mult, 3))


def metrics(rows: list[dict], risk_pct: float = 1.0) -> dict:
    """Win rate, profit factor, Sharpe/Sortino (per trade, not annualised), drawdown, by R-risk equity."""
    rets = [r["net_return"] for r in rows if r.get("net_return") is not None]
    rs = [r["r_multiple"] for r in rows if r.get("r_multiple") is not None]
    n = len(rets)
    if not n:
        return {"n": 0}
    wins = [x for x in rets if x > 0]
    losses = [x for x in rets if x <= 0]
    mean = sum(rets) / n
    std = math.sqrt(sum((x - mean) ** 2 for x in rets) / (n - 1)) if n > 1 else 0.0
    downside = math.sqrt(sum(min(0.0, x) ** 2 for x in rets) / n)
    equity, peak, mdd, curve = 1.0, 1.0, 0.0, []
    for r in rs:
        equity *= 1 + r * risk_pct / 100
        peak = max(peak, equity)
        mdd = max(mdd, 1 - equity / peak)
        curve.append(round(equity, 6))
    gross_loss = -sum(losses)
    return {
        "n": n,
        "win_rate": len(wins) / n,
        "profit_factor": (sum(wins) / gross_loss) if gross_loss > 0 else None,
        "avg_return": mean,
        "avg_r": sum(rs) / len(rs) if rs else None,
        "sharpe_per_trade": mean / std if std > 0 else None,
        "sortino_per_trade": mean / downside if downside > 0 else None,
        "max_drawdown": mdd,
        "equity_curve": curve,
        "sample_note_fa": "نمونه آماری کم است؛ نتایج قابل اتکا نیست" if n < 30 else "",
    }


def grouped_metrics(rows: list[dict], key: str, risk_pct: float = 1.0) -> dict[str, dict]:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(str(r.get(key)), []).append(r)
    return {k: {kk: vv for kk, vv in metrics(v, risk_pct).items() if kk != "equity_curve"} for k, v in groups.items()}


def calibration_table(rows: list[dict], min_samples: int = 30) -> list[tuple[float, float, float, int]] | None:
    """(low, high, hit_rate, n) per confidence bucket once enough signals are evaluated."""
    usable = [r for r in rows if r.get("confidence") is not None and r.get("net_return") is not None]
    if len(usable) < min_samples:
        return None
    buckets = [(0.0, 0.45), (0.45, 0.6), (0.6, 0.75), (0.75, 1.01)]
    table = []
    for lo, hi in buckets:
        inside = [r for r in usable if lo <= r["confidence"] < hi]
        if len(inside) >= 8:
            table.append((lo, hi, sum(r["net_return"] > 0 for r in inside) / len(inside), len(inside)))
    return table or None


def make_calibrator(table):
    """Maps a raw confidence to the observed hit rate of its bucket, when known."""
    def calibrate(raw: float):
        if table:
            for lo, hi, hit, _ in table:
                if lo <= raw < hi:
                    return hit, True
        return raw, False
    return calibrate
