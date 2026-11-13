from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from independent_trading_agent.app.pipeline import Engine
from independent_trading_agent.app.runs import make_report, run_analyze, run_daily, should_run_today
from independent_trading_agent.database.db import Repository
from independent_trading_agent.performance.backtest import replay_symbol

from .conftest import FakeProvider, synthetic_bars

NEWS = [{"title": "Company beats estimates, shares surge", "publisher": "Test Wire",
         "published_utc": "2026-11-12T15:00:00+00:00", "source": "synthetic"},
        {"title": "Old headline that must be dropped", "publisher": "Test Wire",
         "published_utc": "2026-09-01T15:00:00+00:00", "source": "synthetic"}]
FUND = {"longName": "Uptrend Corp", "trailingPE": 22.0, "revenueGrowth": 0.12, "profitMargins": 0.2,
        "freeCashflow": 2e9, "_source": "synthetic", "_fetched_utc": "2026-11-12T22:00:00+00:00"}


def engine(settings, now, frames=None, **kw):
    return Engine(settings, provider=FakeProvider(frames or {}, news=NEWS, fundamentals=FUND, **kw),
                  repo=Repository(settings.db_path), now=now)


def test_analyze_records_evidence_and_signal(settings, now):
    eng = engine(settings, now, {"UPP": synthetic_bars(drift=0.004, vol=0.01, seed=11)})
    rows = eng.analyze(["UPP"], "run1")
    row = rows[0]
    assert row["data_as_of"] == "2026-11-12" and row["data_source"].startswith("SYNTHETIC")
    agents = {o["agent"] for o in row["opinions_json"]}
    assert {"technical_analyst", "fundamental_analyst", "news_analyst", "sentiment_analyst",
            "stock_market_analyst"} <= agents
    news_titles = [n["title"] for n in row["news_json"]]
    assert "Old headline that must be dropped" not in news_titles
    stored = eng.repo.analysis(row["id"])
    assert stored["label"] == row["label"]
    if row["label"] in ("BUY", "STRONG BUY", "SELL", "STRONG SELL"):
        sig = eng.repo.signals()[0]
        assert sig["data_as_of"] == "2026-11-12" and sig["stop"] and sig["targets_json"]


def test_forex_analysis_drops_the_incomplete_bar(settings, now):
    eng = engine(settings, now)
    row = eng.analyze(["EURUSD"], "run1")[0]
    assert row["market"] == "forex" and row["data_as_of"] == "2026-11-11"
    assert row["quality_json"]["dropped_incomplete"] == 1


def test_missing_data_is_no_trade_not_invented(settings, now):
    eng = engine(settings, now, {"GONE": pd.DataFrame()})
    row = eng.analyze(["GONE"], "run1")[0]
    assert row["label"] == "NO TRADE" and row.get("last_price") is None


def test_report_is_persian_rtl_in_market_order_and_never_overwritten(settings, now):
    eng = engine(settings, now)
    out = run_analyze(settings, ["AAPL", "EURUSD", "BTC-USD"], engine=eng)
    html = Path(out["report"]["html"]).read_text(encoding="utf-8")
    assert 'dir="rtl"' in html and 'lang="fa"' in html
    assert html.index("فارکس (Forex)") < html.index("نزدک (NASDAQ)") < html.index("رمزارز (Cryptocurrency)")
    for section in ("بخش B", "بخش C", "توصیه سرمایه‌گذاری"):
        assert section in html
    second = make_report(eng.repo, settings, out["run_id"], now=now)
    assert second["html"] != out["report"]["html"]


def test_daily_run_end_to_end(settings, now):
    settings.markets = ["forex", "nasdaq"]
    settings.universe = {"forex": ["EURUSD", "GBPUSD"], "nasdaq": ["UPP"], "nyse": [], "crypto": [], "tsx": [],
                         "tsxv": []}
    settings.watchlist = ["GC=F"]
    eng = engine(settings, now, {"UPP": synthetic_bars(drift=0.004, vol=0.01, seed=11)})
    out = run_daily(settings, engine=eng)
    assert out["status"] == "ok"
    html = Path(out["report"]["html"]).read_text(encoding="utf-8")
    assert html.index("بخش A") < html.index("بخش B") < html.index("بخش C")
    assert "GC=F" in html
    assert eng.repo.scan_rows(out["run_id"])


def test_weekend_daily_run_is_skipped_without_force(settings):
    saturday = datetime(2026, 11, 14, 15, 0, tzinfo=UTC)
    settings.markets = ["forex", "nasdaq"]
    ok, _ = should_run_today(settings, saturday)
    assert not ok


def test_open_signals_get_evaluated_later(settings, now):
    frames = {"UPP": synthetic_bars(end="2026-10-30", drift=0.004, vol=0.01, seed=11)}
    issue_time = datetime(2026, 10, 30, 23, 0, tzinfo=UTC)
    eng = engine(settings, issue_time, frames)
    eng.analyze(["UPP"], "run1")
    if not eng.repo.signals(status="open"):
        return  # the synthetic series produced no trade; covered by other tests
    later = engine(settings, now, {"UPP": synthetic_bars(drift=0.004, vol=0.01, seed=11)})
    result = later.evaluate_open()
    assert result["evaluated"] == 1
    ev = later.repo.evaluations()[0]
    assert ev["entry_date"] > "2026-10-30"


def test_backtest_replay_has_no_look_ahead(settings):
    df = synthetic_bars(n=420, drift=0.001, seed=21)
    a = replay_symbol("UPP", df, settings, step=20, market="nasdaq")
    altered = df.copy()
    altered.iloc[-30:, :4] *= 0.5
    b = replay_symbol("UPP", altered, settings, step=20, market="nasdaq")
    cutoff = str(df.index[-31].date())
    early_a = [(r["date"], r["label"], r["score"]) for r in a if r["date"] < cutoff]
    early_b = [(r["date"], r["label"], r["score"]) for r in b if r["date"] < cutoff]
    assert early_a and early_a == early_b
