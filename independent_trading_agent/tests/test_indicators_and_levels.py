import numpy as np
import pandas as pd
import pytest

from independent_trading_agent.analysis import indicators
from independent_trading_agent.analysis.levels import find_levels

from .conftest import synthetic_bars


def test_sma_and_ema_match_hand_computation():
    s = pd.Series([1.0, 2, 3, 4, 5])
    assert indicators.sma(s, 3).tolist()[2:] == [2.0, 3.0, 4.0]
    e = indicators.ema(s, 3)  # alpha 0.5, seeded from the first value
    assert e.iloc[-1] == pytest.approx(4.0625)


def test_rsi_extremes_and_range():
    up = pd.Series(np.arange(1, 40, dtype=float))
    assert indicators.rsi(up).iloc[-1] == pytest.approx(100.0)
    down = pd.Series(np.arange(40, 1, -1, dtype=float))
    assert indicators.rsi(down).iloc[-1] == pytest.approx(0.0, abs=1e-9)
    r = indicators.rsi(synthetic_bars()["close"]).dropna()
    assert r.between(0, 100).all()


def test_atr_of_constant_range_bars():
    df = pd.DataFrame({"open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "volume": 1.0},
                      index=pd.date_range("2026-01-01", periods=40))
    assert indicators.atr(df).iloc[-1] == pytest.approx(2.0)


def test_indicators_are_causal():
    """A value at bar t must not change when later bars change."""
    df = synthetic_bars()
    a = indicators.compute(df)
    altered = df.copy()
    altered.iloc[-10:, :4] *= 1.5
    b = indicators.compute(altered)
    cols = ["sma50", "ema20", "rsi14", "macd_hist", "bb_upper", "atr14", "vwap20", "vol_z"]
    pd.testing.assert_frame_equal(a[cols].iloc[:-10], b[cols].iloc[:-10])


def test_forex_has_no_volume_indicators():
    df = synthetic_bars(volume=False)
    ind = indicators.compute(df, "forex", has_volume=False)
    assert ind["vwap20"].isna().all() and ind["vol_z"].isna().all()


def test_breakout_and_levels():
    df = synthetic_bars(drift=0.0, vol=0.005, seed=3)
    df = df.copy()
    last = df.index[-1]
    df.loc[last, ["high", "close"]] = df["high"].iloc[-21:-1].max() * 1.03
    lv = find_levels(df, float(indicators.atr(df).iloc[-1]))
    assert lv.breakout == "up"
    assert lv.support is None or lv.support < df["close"].iloc[-1]
