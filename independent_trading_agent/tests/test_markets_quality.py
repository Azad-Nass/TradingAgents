from datetime import UTC, date, datetime

import pandas as pd

from independent_trading_agent.core import markets
from independent_trading_agent.core.data_provider import drop_incomplete_bars
from independent_trading_agent.core.quality import assess

from .conftest import synthetic_bars


def test_priority_order_is_fixed():
    assert markets.PRIORITY_ORDER == ["forex", "nasdaq", "nyse", "crypto", "tsx", "tsxv"]


def test_symbol_mapping():
    assert markets.to_yahoo("EUR/USD") == "EURUSD=X"
    assert markets.to_yahoo("eurusd") == "EURUSD=X"
    assert markets.to_yahoo("BTC", "crypto") == "BTC-USD"
    assert markets.to_yahoo("RY", "tsx") == "RY.TO"
    assert markets.infer_market("BTC-USD") == "crypto"
    assert markets.infer_market("SHOP.TO") == "tsx"
    assert markets.infer_market("GC=F") == "other"
    assert markets.display_symbol("USDJPY") == "USD/JPY"
    assert markets.pip_size("USDJPY") == 0.01 and markets.pip_size("EURUSD") == 0.0001


def test_us_and_canadian_holidays_2026():
    us = markets.us_holidays(2026)
    assert date(2026, 11, 26) in us          # Thanksgiving
    assert date(2026, 4, 3) in us            # Good Friday
    assert date(2026, 7, 3) in us            # July 4 is a Saturday -> Friday
    assert not markets.is_trading_day("nyse", date(2026, 11, 26))
    assert markets.is_trading_day("nyse", date(2026, 11, 12))
    ca = markets.tsx_holidays(2026)
    assert date(2026, 10, 12) in ca          # Canadian Thanksgiving
    assert date(2026, 5, 18) in ca           # Victoria Day (May 25 is itself a Monday)
    assert date(2025, 5, 19) in markets.tsx_holidays(2025)
    assert markets.is_trading_day("crypto", date(2026, 11, 14))   # Saturday
    assert not markets.is_trading_day("forex", date(2026, 11, 14))


def test_last_completed_session():
    after_close = datetime(2026, 11, 12, 22, 0, tzinfo=UTC)   # 17:00 NY
    before_close = datetime(2026, 11, 12, 18, 0, tzinfo=UTC)  # 13:00 NY
    assert markets.last_completed_session("nasdaq", after_close) == date(2026, 11, 12)
    assert markets.last_completed_session("nasdaq", before_close) == date(2026, 11, 11)
    assert markets.last_completed_session("forex", after_close) == date(2026, 11, 11)
    assert markets.last_completed_session("nasdaq", datetime(2026, 11, 27, 14, 0, tzinfo=UTC)) \
        == date(2026, 11, 25)                                            # day after Thanksgiving, before close


def test_forex_sessions():
    tokyo_morning = datetime(2026, 11, 13, 1, 0, tzinfo=UTC)
    assert "asia" in markets.forex_sessions_open(tokyo_morning)
    saturday = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    assert markets.forex_sessions_open(saturday) == []
    assert not markets.market_status("forex", saturday)["open"]


def test_incomplete_bar_dropped_and_quality_ok():
    df = synthetic_bars()
    kept, dropped = drop_incomplete_bars(df, date(2026, 11, 11))
    assert dropped == 1 and kept.index[-1] == pd.Timestamp("2026-11-11")
    q = assess(kept, market="nasdaq", asset_class="stock", expected_last=date(2026, 11, 11), min_bars=200,
               max_stale_sessions=3)
    assert q.ok and q.has_volume


def test_quality_flags_stale_short_and_bad_data():
    df = synthetic_bars(end="2026-10-01", n=120)
    q = assess(df, market="nasdaq", asset_class="stock", expected_last=date(2026, 11, 12), min_bars=200,
               max_stale_sessions=3)
    assert not q.ok
    assert any("کندل کافی" in i for i in q.issues) and any("کهنه" in i for i in q.issues)
    bad = synthetic_bars().copy()
    bad.iloc[5, 3] = -1.0
    q2 = assess(bad, market="nasdaq", asset_class="stock", expected_last=date(2026, 11, 12), min_bars=200,
                max_stale_sessions=3)
    assert not q2.ok
    empty = assess(pd.DataFrame(), market="forex", asset_class="forex", expected_last=date(2026, 11, 12),
                   min_bars=200, max_stale_sessions=3)
    assert not empty.ok and empty.bars == 0


def test_bar_without_close_is_dropped_and_reported(now):
    from independent_trading_agent.analysis.prepare import prepare

    df = synthetic_bars().copy()
    df.loc[df.index[-1], "close"] = float("nan")  # as Yahoo sometimes serves the latest US bar
    prep = prepare(df, "nasdaq", now, min_bars=200, max_stale_sessions=3)
    assert prep.bars.index[-1] == df.index[-2]
    assert prep.snap["dollar_vol20"] is not None
    assert any("بدون قیمت بسته‌شدن" in w for w in prep.quality.warnings)
