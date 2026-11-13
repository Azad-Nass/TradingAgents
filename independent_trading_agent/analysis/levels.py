"""Support/resistance from confirmed swing pivots, and breakout detection.

A pivot at bar i is confirmed only ``k`` bars later, so the levels known at
the last bar use pivots up to ``len - 1 - k``: no future bar is used.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from ..core.quality import finite


@dataclass
class Levels:
    support: float | None
    resistance: float | None
    supports: list[float]
    resistances: list[float]
    high_20: float | None       # highest high of the 20 bars before the last
    low_20: float | None
    breakout: str | None        # "up" | "down" | None, on the last bar
    failed_breakout: str | None  # "up" (bearish) | "down" (bullish) | None, within 5 bars

    def to_dict(self) -> dict:
        return asdict(self)


def swing_pivots(df: pd.DataFrame, k: int = 5, lookback: int = 160) -> tuple[list[float], list[float]]:
    """Confirmed swing highs and lows of the last ``lookback`` bars."""
    data = df.tail(lookback)
    highs, lows = data["high"].to_numpy(), data["low"].to_numpy()
    piv_h, piv_l = [], []
    for i in range(k, len(data) - k):
        window_h, window_l = highs[i - k:i + k + 1], lows[i - k:i + k + 1]
        if highs[i] == window_h.max():
            piv_h.append(float(highs[i]))
        if lows[i] == window_l.min():
            piv_l.append(float(lows[i]))
    return piv_h, piv_l


def _cluster(levels: list[float], tol: float) -> list[float]:
    """Merge levels within ``tol`` of each other into their mean."""
    out: list[list[float]] = []
    for lv in sorted(levels):
        if out and abs(lv - out[-1][-1]) <= tol:
            out[-1].append(lv)
        else:
            out.append([lv])
    return [sum(g) / len(g) for g in out]


def find_levels(df: pd.DataFrame, atr_value: float | None) -> Levels:
    close = float(df["close"].iloc[-1])
    tol = (atr_value or close * 0.01) * 0.5
    piv_h, piv_l = swing_pivots(df)
    levels = _cluster(piv_h + piv_l, tol)
    resistances = sorted([lv for lv in levels if lv > close])
    supports = sorted([lv for lv in levels if lv < close], reverse=True)

    prior = df.iloc[-21:-1] if len(df) > 21 else df.iloc[:-1]
    high_20 = finite(prior["high"].max()) if len(prior) else None
    low_20 = finite(prior["low"].min()) if len(prior) else None
    breakout = None
    if high_20 is not None and close > high_20:
        breakout = "up"
    elif low_20 is not None and close < low_20:
        breakout = "down"

    failed = None
    if len(df) > 26 and breakout is None:
        for j in range(2, 7):  # a breakout close within the 5 bars before the last
            window = df.iloc[-j - 20:-j]
            bar_close = float(df["close"].iloc[-j])
            lvl_h, lvl_l = float(window["high"].max()), float(window["low"].min())
            if bar_close > lvl_h and close < lvl_h:
                failed = "up"
                break
            if bar_close < lvl_l and close > lvl_l:
                failed = "down"
                break

    return Levels(supports[0] if supports else None, resistances[0] if resistances else None,
                  supports[:3], resistances[:3], high_20, low_20, breakout, failed)
