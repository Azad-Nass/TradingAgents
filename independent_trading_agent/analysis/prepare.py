"""Raw provider bars -> completed bars, indicators, levels and a quality verdict."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from ..core.data_provider import drop_incomplete_bars
from ..core.markets import MARKETS, last_completed_session
from ..core.quality import DataQuality, assess
from . import indicators
from .levels import Levels, find_levels


@dataclass
class Prepared:
    bars: pd.DataFrame
    ind: pd.DataFrame | None
    snap: dict | None
    levels: Levels | None
    quality: DataQuality


def prepare(raw: pd.DataFrame, market_key: str, now: datetime, *, min_bars: int, max_stale_sessions: int,
            interval: str = "1d") -> Prepared:
    m = MARKETS.get(market_key, MARKETS["other"])
    if raw is None:
        raw = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    expected = last_completed_session(market_key, now)
    # A bar without a close (Yahoo sometimes serves the latest one that way) is unusable: drop and report it.
    invalid = int(raw["close"].isna().sum()) if "close" in raw else 0
    if invalid:
        raw = raw[raw["close"].notna()]
    bars, dropped = drop_incomplete_bars(raw, expected) if interval == "1d" else (raw, 0)
    quality = assess(bars, market=market_key, asset_class=m.asset_class, expected_last=expected,
                     min_bars=min_bars, max_stale_sessions=max_stale_sessions, dropped_incomplete=dropped,
                     dropped_invalid=invalid)
    if bars.empty or len(bars) < 30:
        return Prepared(bars, None, None, None, quality)
    ind = indicators.compute(bars, m.asset_class, quality.has_volume)
    snap = indicators.snapshot(ind)
    return Prepared(bars, ind, snap, find_levels(bars, snap["atr14"]), quality)
