"""Technical indicators computed from real OHLCV bars.

Every function takes only past and current bars (no centring, no
backfilling), so a value at bar t never depends on bars after t.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..core.quality import finite


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def _wilder(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = _wilder(delta.clip(lower=0), n)
    loss = _wilder(-delta.clip(upper=0), n)
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(loss != 0, 100.0).where(gain.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "macd_signal": sig, "macd_hist": line - sig})


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = sma(close, n)
    std = close.rolling(n, min_periods=n).std(ddof=0)
    upper, lower = mid + k * std, mid - k * std
    width = (upper - lower) / mid
    pct_b = (close - lower) / (upper - lower)
    return pd.DataFrame({"bb_mid": mid, "bb_upper": upper, "bb_lower": lower, "bb_width": width, "bb_pct_b": pct_b})


def true_range(df: pd.DataFrame) -> pd.Series:
    prev = df["close"].shift(1)
    return pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return _wilder(true_range(df), n)


def rolling_vwap(df: pd.DataFrame, n: int = 20) -> pd.Series:
    """Volume-weighted typical price over the last ``n`` bars (needs real volume)."""
    typical = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].where(df["volume"] > 0)
    return (typical * vol).rolling(n, min_periods=n).sum() / vol.rolling(n, min_periods=n).sum()


def volume_zscore(volume: pd.Series, n: int = 20) -> pd.Series:
    """How unusual this bar's volume is against the previous ``n`` bars."""
    prior = volume.shift(1)
    mean, std = prior.rolling(n, min_periods=n).mean(), prior.rolling(n, min_periods=n).std()
    return (volume - mean) / std.replace(0, np.nan)


def realized_vol(close: pd.Series, n: int = 20, periods_per_year: int = 252) -> pd.Series:
    return np.log(close).diff().rolling(n, min_periods=n).std() * np.sqrt(periods_per_year)


PERIODS_PER_YEAR = {"forex": 260, "stock": 252, "crypto": 365, "other": 252}


def compute(df: pd.DataFrame, asset_class: str = "stock", has_volume: bool = True) -> pd.DataFrame:
    """``df`` plus every indicator column used by the agents and charts."""
    out = df.copy()
    c = out["close"]
    for n in (20, 50, 200):
        out[f"sma{n}"] = sma(c, n)
    for n in (10, 20, 50):
        out[f"ema{n}"] = ema(c, n)
    out["rsi14"] = rsi(c, 14)
    out = out.join(macd(c)).join(bollinger(c))
    out["atr14"] = atr(out, 14)
    out["atr_pct"] = out["atr14"] / c
    out["vol20"] = realized_vol(c, 20, PERIODS_PER_YEAR.get(asset_class, 252))
    out["ret1"] = c.pct_change()
    out["ret5"] = c.pct_change(5)
    out["ret20"] = c.pct_change(20)
    out["ret60"] = c.pct_change(60)
    if has_volume:
        out["vwap20"] = rolling_vwap(out, 20)
        out["vol_z"] = volume_zscore(out["volume"], 20)
        out["dollar_vol20"] = (c * out["volume"]).rolling(20, min_periods=20).mean()
    else:
        out["vwap20"] = np.nan
        out["vol_z"] = np.nan
        out["dollar_vol20"] = np.nan
    return out


def snapshot(ind: pd.DataFrame) -> dict:
    """Latest indicator values as plain floats (None when not computable)."""
    last = ind.iloc[-1]
    keys = ["open", "high", "low", "close", "volume", "sma20", "sma50", "sma200", "ema10", "ema20", "ema50",
            "rsi14", "macd", "macd_signal", "macd_hist", "bb_mid", "bb_upper", "bb_lower", "bb_width",
            "bb_pct_b", "atr14", "atr_pct", "vol20", "ret1", "ret5", "ret20", "ret60", "vwap20", "vol_z",
            "dollar_vol20"]
    snap = {k: finite(last.get(k)) for k in keys}
    snap["date"] = ind.index[-1].date().isoformat()
    prev = ind.iloc[-2] if len(ind) > 1 else last
    snap["macd_hist_prev"] = finite(prev.get("macd_hist"))
    snap["ema20_prev5"] = finite(ind["ema20"].iloc[-6]) if len(ind) > 6 else None
    atr_hist = ind["atr_pct"].dropna().tail(252)
    snap["atr_pct_median_1y"] = finite(atr_hist.median()) if len(atr_hist) else None
    return snap
