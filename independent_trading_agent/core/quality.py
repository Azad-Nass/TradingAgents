"""Data-quality checks run before any analysis."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from .markets import trading_days_between

# A single-bar move beyond this (as a fraction) is flagged as a possible bad tick.
JUMP_LIMIT = {"forex": 0.05, "stock": 0.30, "crypto": 0.40, "other": 0.20}


@dataclass
class DataQuality:
    ok: bool
    bars: int
    first_bar: str | None
    last_bar: str | None
    expected_last_bar: str | None
    stale_sessions: int | None
    has_volume: bool
    dropped_incomplete: int = 0
    issues: list[str] = field(default_factory=list)    # block analysis
    warnings: list[str] = field(default_factory=list)  # reported, do not block

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def label_fa(self) -> str:
        if not self.ok:
            return "نامعتبر"
        return "قابل قبول با هشدار" if self.warnings else "خوب"


def assess(df: pd.DataFrame, *, market: str, asset_class: str, expected_last: date,
           min_bars: int, max_stale_sessions: int, dropped_incomplete: int = 0,
           dropped_invalid: int = 0) -> DataQuality:
    issues: list[str] = []
    warnings: list[str] = []
    if df is None or df.empty:
        return DataQuality(False, 0, None, None, expected_last.isoformat(), None, False,
                           dropped_incomplete, ["هیچ داده قیمتی دریافت نشد"])

    bars = len(df)
    last = df.index[-1].date()
    stale = trading_days_between(market, last, expected_last) if last < expected_last else 0
    if bars < min_bars:
        issues.append(f"تعداد کندل کافی نیست ({bars} < {min_bars})")
    if stale > max_stale_sessions:
        issues.append(f"داده کهنه است: {stale} جلسه معاملاتی عقب‌تر از {expected_last.isoformat()}")
    elif stale > 0:
        warnings.append(f"آخرین کندل {stale} جلسه عقب‌تر از انتظار است")

    close = df["close"]
    nan_share = float(close.isna().mean())
    if nan_share > 0.02:
        issues.append(f"{nan_share:.0%} از قیمت‌های بسته‌شدن خالی است")
    prices = df[["open", "high", "low", "close"]].dropna()
    if (prices <= 0).any().any():
        issues.append("قیمت صفر یا منفی در داده وجود دارد")
    bad_range = (prices["high"] < prices[["open", "close"]].max(axis=1) - 1e-12) | \
                (prices["low"] > prices[["open", "close"]].min(axis=1) + 1e-12)
    if int(bad_range.sum()) > max(1, bars // 100):
        warnings.append(f"{int(bad_range.sum())} کندل با High/Low ناسازگار")

    returns = close.pct_change().abs().dropna()
    limit = JUMP_LIMIT.get(asset_class, 0.2)
    jumps = returns[returns > limit]
    if len(jumps):
        warnings.append(f"{len(jumps)} جهش تک‌کندلی بیش از {limit:.0%} (احتمال داده خراب)؛ "
                        f"آخرین: {jumps.index[-1].date().isoformat()}")

    volume = df["volume"].fillna(0)
    has_volume = bool((volume.tail(60) > 0).mean() > 0.8) if asset_class != "forex" else False
    if asset_class != "forex" and not has_volume:
        warnings.append("داده حجم معاملات ناقص یا صفر است")
    if dropped_invalid:
        warnings.append(f"{dropped_invalid} کندل بدون قیمت بسته‌شدن از منبع داده دریافت و کنار گذاشته شد")
    if dropped_incomplete:
        warnings.append(f"{dropped_incomplete} کندل ناتمام (جلسه جاری) کنار گذاشته شد")

    return DataQuality(not issues, bars, df.index[0].date().isoformat(), last.isoformat(),
                       expected_last.isoformat(), stale, has_volume, dropped_incomplete, issues, warnings)


def finite(value) -> float | None:
    """A float, or None for NaN/inf/missing."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None
