"""Price data access with a request budget.

:class:`YahooProvider` reads daily prices from Yahoo Finance through yfinance
(no key needed; delayed and unofficial, which every report states). It feeds
the data-quality check, the scan, the risk officer and signal evaluation; the
analysis itself comes from TradingAgents. Tests use any object with the same
``history`` method; nothing here invents data.
"""
from __future__ import annotations

import logging
import time as _time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

import pandas as pd

logger = logging.getLogger(__name__)

OHLCV = ["open", "high", "low", "close", "volume"]


class BudgetExceeded(RuntimeError):
    """The run has used its allowed number of data requests."""


class DataProvider(Protocol):
    name: str

    def history(self, symbols: list[str], period: str, interval: str) -> dict[str, pd.DataFrame]: ...


@dataclass
class RequestBudget:
    limit: int
    delay_seconds: float = 0.0
    used: int = 0
    log: list[str] = field(default_factory=list)

    def spend(self, what: str) -> None:
        if self.used >= self.limit:
            raise BudgetExceeded(f"data request budget of {self.limit} used up (next: {what})")
        if self.used and self.delay_seconds:
            _time.sleep(self.delay_seconds)
        self.used += 1
        self.log.append(what)


def _retry(fn, attempts: int = 3, base_delay: float = 1.0):
    """Call ``fn`` with limited exponential backoff on network errors."""
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # yfinance raises many types for network trouble
            if attempt == attempts - 1:
                raise
            wait = base_delay * 2 ** attempt
            logger.warning("data request failed (%s: %s); retrying in %.0fs", type(exc).__name__, exc, wait)
            _time.sleep(wait)
    return None


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Lower-case OHLCV columns on a tz-naive, sorted, de-duplicated date index."""
    if df is None or df.empty:
        return pd.DataFrame(columns=OHLCV)
    out = df.rename(columns=str.lower)
    out = out[[c for c in OHLCV if c in out.columns]].copy()
    for col in OHLCV:
        if col not in out.columns:
            out[col] = float("nan")
    idx = pd.DatetimeIndex(out.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    out.index = idx
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out.dropna(how="all", subset=["open", "high", "low", "close"])


class YahooProvider:
    name = "Yahoo Finance (yfinance; delayed, unofficial)"

    def __init__(self, budget: RequestBudget):
        self.budget = budget
        self._history_cache: dict[tuple, pd.DataFrame] = {}

    def history(self, symbols: list[str], period: str = "2y", interval: str = "1d") -> dict[str, pd.DataFrame]:
        import yfinance as yf

        wanted = [s for s in dict.fromkeys(symbols) if (s, period, interval) not in self._history_cache]
        for start in range(0, len(wanted), 25):
            chunk = wanted[start:start + 25]
            self.budget.spend(f"history {','.join(chunk)}")
            raw = _retry(lambda c=chunk: yf.download(
                c, period=period, interval=interval, group_by="ticker", auto_adjust=False,
                progress=False, threads=True))
            for sym in chunk:
                try:
                    part = raw[sym] if isinstance(raw.columns, pd.MultiIndex) else raw
                except KeyError:
                    part = pd.DataFrame()
                self._history_cache[(sym, period, interval)] = normalize_ohlcv(part)
        return {s: self._history_cache[(s, period, interval)] for s in symbols}


def drop_incomplete_bars(df: pd.DataFrame, last_complete: pd.Timestamp | datetime) -> tuple[pd.DataFrame, int]:
    """Bars dated after the last completed session removed, with how many were dropped."""
    if df.empty:
        return df, 0
    cutoff = pd.Timestamp(last_complete).normalize()
    kept = df[df.index.normalize() <= cutoff]
    return kept, len(df) - len(kept)
