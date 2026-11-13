import pandas as pd
import pytest

from independent_trading_agent.performance.evaluate import calibration_table, evaluate_signal, make_calibrator, metrics
from independent_trading_agent.portfolio.exposure import exposure
from independent_trading_agent.risk_management.sizing import round_trip_cost, size_position


def no_fx(a, b):
    return None


def test_stock_sizing_risks_one_percent():
    s = size_position(symbol="AAPL", asset_class="stock", quote_ccy="USD", entry=100, stop=95,
                      portfolio_value=100_000, risk_pct=1, account_ccy="USD", fx=no_fx)
    assert s.ok and s.units == 200 and s.risk_amount == pytest.approx(1000)


def test_cad_stock_needs_and_uses_conversion():
    s = size_position(symbol="RY.TO", asset_class="stock", quote_ccy="CAD", entry=100, stop=98,
                      portfolio_value=100_000, risk_pct=1, account_ccy="USD", fx=no_fx)
    assert not s.ok
    s = size_position(symbol="RY.TO", asset_class="stock", quote_ccy="CAD", entry=100, stop=98,
                      portfolio_value=100_000, risk_pct=1, account_ccy="USD", fx=lambda a, b: 0.72)
    assert s.units == 694  # 1000 / (2 * 0.72)


def test_forex_lots_and_pip_value():
    eur = size_position(symbol="EURUSD", asset_class="forex", quote_ccy="USD", entry=1.10, stop=1.095,
                        portfolio_value=100_000, risk_pct=1, account_ccy="USD", fx=no_fx)
    assert eur.stop_pips == pytest.approx(50) and eur.pip_value_per_lot == pytest.approx(10)
    assert eur.lots == 2.0
    jpy = size_position(symbol="USDJPY", asset_class="forex", quote_ccy="USD", entry=150.0, stop=149.0,
                        portfolio_value=100_000, risk_pct=1, account_ccy="USD", fx=no_fx)
    assert jpy.stop_pips == pytest.approx(100)
    assert jpy.pip_value_per_lot == pytest.approx(1000 / 150, abs=1e-3)  # 100k * 0.01 JPY in USD
    assert jpy.lots == 1.5


def test_costs_are_positive_and_forex_uses_pips():
    fx = round_trip_cost(asset_class="forex", symbol="EURUSD", price=1.1, forex_spread_pips=1, stock_spread_bps=5,
                         crypto_spread_bps=10, commission_bps=2, slippage_bps=3)
    assert fx == pytest.approx(0.0001 / 1.1 + 0.0006)
    st = round_trip_cost(asset_class="stock", symbol="AAPL", price=100, forex_spread_pips=1, stock_spread_bps=5,
                         crypto_spread_bps=10, commission_bps=2, slippage_bps=3)
    assert st == pytest.approx(0.0015)


def bars(rows, start="2026-01-05"):
    idx = pd.bdate_range(start, periods=len(rows))
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx).assign(volume=1.0)


def test_entry_is_next_bar_open_and_stop_wins_ties():
    b = bars([[100, 101, 99, 100], [100, 111, 94, 100], [100, 101, 99, 100]])
    ev = evaluate_signal(direction=1, data_as_of="2026-01-05", stop=95, target=110, horizon_bars=5, bars=b, cost=0)
    assert ev.entry_date == "2026-01-06" and ev.exit_reason == "stop" and ev.exit_price == 95


def test_target_and_horizon_exits_with_costs():
    b = bars([[100, 101, 99, 100], [100, 103, 99, 102], [102, 111, 101, 109]])
    ev = evaluate_signal(direction=1, data_as_of="2026-01-05", stop=95, target=110, horizon_bars=5, bars=b, cost=0.001)
    assert ev.exit_reason == "target" and ev.net_return == pytest.approx(0.099)
    flat = bars([[100, 101, 99, 100]] + [[100, 101, 99, 101]] * 3)
    ev2 = evaluate_signal(direction=-1, data_as_of="2026-01-05", stop=105, target=90, horizon_bars=3, bars=flat, cost=0)
    assert ev2.exit_reason == "horizon" and ev2.net_return == pytest.approx(-0.01)
    open_trade = evaluate_signal(direction=1, data_as_of="2026-01-05", stop=95, target=110, horizon_bars=10,
                                 bars=flat, cost=0)
    assert open_trade is None  # not enough bars yet: still open


def test_no_bar_at_or_before_issue_is_used():
    b = bars([[100, 200, 1, 100], [100, 101, 99, 100], [100, 101, 99, 101]])  # wild bar on the signal day
    ev = evaluate_signal(direction=1, data_as_of="2026-01-05", stop=95, target=110, horizon_bars=2, bars=b, cost=0)
    assert ev.exit_reason == "horizon"


def test_gap_beyond_stop_invalidates_at_entry():
    b = bars([[100, 101, 99, 100], [94, 95, 93, 94]])
    ev = evaluate_signal(direction=1, data_as_of="2026-01-05", stop=95, target=110, horizon_bars=3, bars=b, cost=0.001)
    assert ev.exit_reason == "invalid_at_entry" and ev.net_return == pytest.approx(-0.001)


def test_metrics():
    rows = [{"net_return": r, "r_multiple": r * 10} for r in (0.02, -0.01, 0.03, -0.01)]
    m = metrics(rows, risk_pct=1)
    assert m["n"] == 4 and m["win_rate"] == 0.5
    assert m["profit_factor"] == pytest.approx(2.5)
    assert m["max_drawdown"] > 0 and m["sample_note_fa"]
    assert metrics([])["n"] == 0


def test_calibration_needs_samples():
    few = [{"confidence": 0.7, "net_return": 0.01}] * 10
    assert calibration_table(few) is None
    many = [{"confidence": 0.7, "net_return": 0.01 if i % 4 else -0.01} for i in range(40)]
    table = calibration_table(many)
    value, calibrated = make_calibrator(table)(0.7)
    assert calibrated and value == pytest.approx(0.75)


def test_exposure_nets_currencies():
    ex = exposure([{"symbol": "EURUSD", "market": "forex", "direction": 1,
                    "sizing": {"notional_account": 100_000, "risk_amount": 1000}},
                   {"symbol": "GBPUSD", "market": "forex", "direction": 1,
                    "sizing": {"notional_account": 50_000, "risk_amount": 1000}}], 100_000)
    assert ex["currency_net"]["USD"] == -150_000 and ex["total_risk_pct"] == 2.0


def test_stale_macro_rates_are_reported_but_not_used():
    from independent_trading_agent.agents import macro_analyst as fundamental_analyst
    from independent_trading_agent.agents.base import AnalysisContext
    from independent_trading_agent.core.markets import MARKETS

    def ctx(macro):
        return AnalysisContext("EURUSD", "EUR/USD", "EURUSD=X", MARKETS["forex"], None, None, {}, None, None,
                               None, "synthetic", macro=macro)

    fresh = {"value": 4.0, "date": "2026-11-11", "series": "DFF", "age_days": 1, "stale": False, "kind_fa": "a"}
    old = {"value": 2.0, "date": "2026-01-01", "series": "X", "age_days": 315, "stale": True, "kind_fa": "a"}
    eur = {**fresh, "value": 2.0, "series": "ECBDFR"}
    used = fundamental_analyst.analyze_macro(ctx({"available": True, "base": "EUR", "quote": "USD",
                                                  "rate_base": eur, "rate_quote": fresh}))
    assert used.score < 0  # EUR rate 2 points below USD: bearish EUR/USD
    ignored = fundamental_analyst.analyze_macro(ctx({"available": True, "base": "EUR", "quote": "USD",
                                                     "rate_base": old, "rate_quote": fresh}))
    assert ignored.score == 0 and any("کهنه" in u for u in ignored.uncertainties)


def test_gold_lots_use_ounces_and_dollar_pips():
    g = size_position(symbol="XAUUSD", asset_class="forex", quote_ccy="USD", entry=4000.0, stop=3980.0,
                      portfolio_value=100_000, risk_pct=1, account_ccy="USD", fx=no_fx)
    assert g.stop_pips == pytest.approx(200) and g.pip_value_per_lot == pytest.approx(10)
    assert g.lots == 0.5 and g.units == 50 and g.risk_amount == pytest.approx(1000)
    cost = round_trip_cost(asset_class="forex", symbol="XAUUSD", price=4000, forex_spread_pips=1,
                           stock_spread_bps=5, crypto_spread_bps=10, commission_bps=2, slippage_bps=3)
    assert cost == pytest.approx(3 * 0.1 / 4000 + 0.0006)


def test_gold_macro_reads_real_yields():
    from independent_trading_agent.agents import macro_analyst as fundamental_analyst
    from independent_trading_agent.agents.base import AnalysisContext
    from independent_trading_agent.core.markets import MARKETS

    macro = {"available": True, "kind": "metal", "series": "DFII10", "as_of": "2026-11-12", "stale": False,
             "real_yield": {"value": 2.1, "date": "2026-11-11"}, "real_yield_prev": {"value": 1.8, "date": "2026-10-14"},
             "change": 0.3}
    ctx = AnalysisContext("XAUUSD", "XAU/USD", "GC=F", MARKETS["forex"], None, None, {}, None, None, None,
                          "synthetic", macro=macro)
    op = fundamental_analyst.analyze_macro(ctx)
    assert op.score < 0 and "TIPS" in op.evidence[0].text_fa  # rising real yields weigh on gold


def test_short_limit_fills_on_the_rally_then_hits_target():
    # signal day, rally through 105 (fill), then a fall to the target
    b = bars([[100, 101, 99, 100], [101, 106, 100, 104], [104, 104.5, 96, 97], [97, 98, 94, 95]])
    ev = evaluate_signal(direction=-1, data_as_of="2026-01-05", stop=108, target=99, horizon_bars=5, bars=b,
                         cost=0, limit_price=105)
    assert ev.entry_price == 105 and ev.entry_date == "2026-01-06"
    assert ev.exit_reason == "target" and ev.exit_price == 99


def test_limit_gap_fills_at_the_better_open():
    b = bars([[100, 101, 99, 100], [107, 107.5, 104, 105]])
    ev = evaluate_signal(direction=-1, data_as_of="2026-01-05", stop=110, target=99, horizon_bars=3, bars=b,
                         cost=0, limit_price=105)
    assert ev is None  # filled at 107 but the horizon is not over yet
    more = bars([[100, 101, 99, 100], [107, 107.5, 104, 105], [105, 106, 104, 105], [105, 106, 104, 104]])
    ev = evaluate_signal(direction=-1, data_as_of="2026-01-05", stop=110, target=99, horizon_bars=3, bars=more,
                         cost=0, limit_price=105)
    assert ev.entry_price == 107 and ev.exit_reason == "horizon"


def test_limit_fill_bar_counts_only_the_stop():
    # the fill bar also touches the target: ignored (order of moves inside the bar is unknown)
    b = bars([[100, 101, 99, 100], [101, 106, 98, 99], [99, 100, 98.5, 99.5], [99.5, 100, 99, 99.6]])
    ev = evaluate_signal(direction=-1, data_as_of="2026-01-05", stop=108, target=98.5, horizon_bars=3, bars=b,
                         cost=0, limit_price=105)
    assert ev.entry_date == "2026-01-06" and ev.exit_reason == "target" and ev.exit_date == "2026-01-07"


def test_unfilled_limit_is_not_a_trade():
    b = bars([[100, 101, 99, 100]] + [[100, 102, 99, 101]] * 3)
    pending = evaluate_signal(direction=-1, data_as_of="2026-01-05", stop=110, target=95, horizon_bars=5, bars=b,
                              cost=0.001, limit_price=105)
    assert pending is None
    done = evaluate_signal(direction=-1, data_as_of="2026-01-05", stop=110, target=95, horizon_bars=3, bars=b,
                           cost=0.001, limit_price=105)
    assert done.exit_reason == "not_filled" and done.net_return == 0
    m = metrics([done.to_dict(), {"net_return": 0.02, "r_multiple": 1.0, "exit_reason": "target"}])
    assert m["n"] == 1  # the unfilled limit is left out


def test_trader_turns_a_better_entry_into_a_limit(now):
    from independent_trading_agent.agents import trader
    from independent_trading_agent.agents.base import AnalysisContext
    from independent_trading_agent.analysis.prepare import prepare
    from independent_trading_agent.core.markets import MARKETS

    from .conftest import synthetic_bars

    prep = prepare(synthetic_bars(seed=11), "nasdaq", now, min_bars=200, max_stale_sessions=3)
    ctx = AnalysisContext("UPP", "UPP", "UPP", MARKETS["nasdaq"], prep.bars, prep.ind, prep.snap, prep.levels,
                          prep.quality, now, "synthetic")
    close, atr = prep.snap["close"], prep.snap["atr14"]
    short = trader.make_plan(ctx, -1, 10, entry_hint=close + 1.0 * atr)
    assert short.entry_type == "limit" and short.limit_price == pytest.approx(close + atr)
    assert short.stop > short.limit_price > short.targets[0]
    worse = trader.make_plan(ctx, -1, 10, entry_hint=close - 1.0 * atr)   # selling below the market
    far = trader.make_plan(ctx, -1, 10, entry_hint=close + 5 * atr)       # too far to expect a fill
    assert worse.entry_type == "market" and far.entry_type == "market"
    assert worse.reference_price == close
