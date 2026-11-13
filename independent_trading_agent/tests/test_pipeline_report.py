"""Engine, report and daily run with TradingAgents as the analysis engine.

TradingAgents itself is replaced by a FAKE result here (no LLM, no network);
its real run is exercised manually, never in the offline suite.
"""
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from independent_trading_agent.agents import chief
from independent_trading_agent.agents.base import AgentOpinion
from independent_trading_agent.agents.risk_officer import RiskAssessment
from independent_trading_agent.app.pipeline import Engine
from independent_trading_agent.app.runs import make_report, run_analyze, run_daily, should_run_today
from independent_trading_agent.database.db import Repository
from independent_trading_agent.integrations import tradingagents_adapter
from independent_trading_agent.performance.backtest import replay_symbol

from .conftest import FakeProvider, synthetic_bars

FAKE = {"rating": "Buy", "ok": True, "calls": []}


def fake_ta(yahoo, trade_date, **kwargs):
    FAKE["calls"].append((yahoo, trade_date, kwargs))
    if not FAKE["ok"]:
        return {"ok": False, "error": "FAKE failure"}
    return {"ok": True, "rating": FAKE["rating"], "trade_date": trade_date, "analysts": ["market", "news"],
            "reports": {"final_trade_decision": f"FAKE decision **Rating**: {FAKE['rating']}",
                        "news_report": "FAKE news report", "market_report": "FAKE market report"},
            "debate": {"bull": "FAKE bull case", "bear": "FAKE bear case"},
            "numbers": {"entry_price": None, "stop_loss": None, "price_target": None, "time_horizon": "FAKE 1-3 months"},
            "models": {"provider": "FAKE", "quick": "fake-quick", "deep": "fake-deep"}}


@pytest.fixture(autouse=True)
def fake_tradingagents(monkeypatch):
    FAKE.update(rating="Buy", ok=True, calls=[])
    monkeypatch.setattr(tradingagents_adapter, "run_deep_analysis", fake_ta)
    yield FAKE


def engine(settings, now, frames=None, **kw):
    return Engine(settings, provider=FakeProvider(frames or {}, **kw), repo=Repository(settings.db_path), now=now)


UP = {"UPP": synthetic_bars(drift=0.004, vol=0.01, seed=11)}


def test_tradingagents_drives_the_decision(settings, now):
    eng = engine(settings, now, UP)
    row = eng.analyze(["UPP"], "run1")[0]
    agents = [o["agent"] for o in row["opinions_json"]]
    assert agents == ["tradingagents_llm", "macro_analyst", "sentiment_analyst"]
    assert row["ta_json"]["rating"] == "Buy" and row["ta_json"]["reports"]["news_report"].startswith("FAKE")
    assert row["label"] in ("STRONG BUY", "NO TRADE")  # NO TRADE only through a risk veto
    if row["label"] == "STRONG BUY":
        sig = eng.repo.signals()[0]
        assert sig["direction"] == 1 and sig["stop"] < row["last_price"]
    yahoo, trade_date, kwargs = FAKE["calls"][0]
    assert (yahoo, trade_date) == ("UPP", "2026-11-12") and kwargs["analysts"] == "market,news,fundamentals"


@pytest.mark.parametrize("rating,label", [("Hold", "HOLD"), ("Overweight", "BUY"), ("Sell", "STRONG SELL")])
def test_rating_maps_to_label_unless_risk_says_no(settings, now, rating, label):
    FAKE["rating"] = rating
    row = engine(settings, now, UP).analyze(["UPP"], "run1")[0]
    assert row["label"] in (label, "NO TRADE")
    if row["label"] == "NO TRADE":
        assert "مدیر ریسک" in row["decision_json"]["reasons_fa"][0]


def test_failed_tradingagents_is_no_trade_with_reason(settings, now):
    FAKE["ok"] = False
    row = engine(settings, now, UP).analyze(["UPP"], "run1")[0]
    assert row["label"] == "NO TRADE" and "TradingAgents" in row["decision_json"]["reasons_fa"][0]
    assert row["ta_json"]["error"] == "FAKE failure"


def test_tradingagents_run_cap(settings, now):
    settings.tradingagents_max_runs = 1
    rows = engine(settings, now, {"AAA": UP["UPP"], "BBB": UP["UPP"]}).analyze(["AAA", "BBB"], "run1")
    assert len(FAKE["calls"]) == 1
    assert "سقف" in rows[1]["decision_json"]["reasons_fa"][0]


def test_bad_price_data_skips_tradingagents(settings, now):
    row = engine(settings, now, {"GONE": pd.DataFrame()}).analyze(["GONE"], "run1")[0]
    assert row["label"] == "NO TRADE" and FAKE["calls"] == []


def test_strong_opposition_weakens_but_risk_veto_stops():
    ta = {"ok": True, "rating": "Buy"}
    macro = AgentOpinion("macro_analyst", "macro", True, -0.6, 0.4)
    weak = chief.decide_tradingagents(ta, [macro], True, RiskAssessment(True))
    assert weak.label == "BUY" and "macro" in weak.disagreeing
    stopped = chief.decide_tradingagents(ta, [], True, RiskAssessment(False, vetoes=["R:R"]))
    assert stopped.label == "NO TRADE"
    assert chief.decide_tradingagents(ta, [], False, RiskAssessment(True)).label == "NO TRADE"


def test_tradingagents_stop_is_used_when_sane(now):
    from independent_trading_agent.agents import trader
    from independent_trading_agent.agents.base import AnalysisContext
    from independent_trading_agent.analysis.prepare import prepare
    from independent_trading_agent.core.markets import MARKETS

    prep = prepare(UP["UPP"], "nasdaq", now, min_bars=200, max_stale_sessions=3)
    ctx = AnalysisContext("UPP", "UPP", "UPP", MARKETS["nasdaq"], prep.bars, prep.ind, prep.snap, prep.levels,
                          prep.quality, now, "synthetic")
    ref, atr = prep.snap["close"], prep.snap["atr14"]
    sane = trader.make_plan(ctx, 1, 10, stop_hint=ref - 2 * atr)
    assert sane.stop == pytest.approx(ref - 2 * atr)
    wild = trader.make_plan(ctx, 1, 10, stop_hint=ref - 10 * atr)
    assert wild.stop > ref - 4 * atr


def test_forex_analysis_drops_the_incomplete_bar(settings, now):
    row = engine(settings, now).analyze(["EURUSD"], "run1")[0]
    assert row["market"] == "forex" and row["data_as_of"] == "2026-11-11"
    assert row["quality_json"]["dropped_incomplete"] == 1
    assert FAKE["calls"][0][2]["analysts"] == "market,news"


def test_gold_is_analysed_in_the_forex_section(settings, now):
    gold = synthetic_bars(start_price=4000, vol=0.01, seed=31)
    row = engine(settings, now, {"GC=F": gold}).analyze(["XAUUSD"], "run1")[0]
    assert row["market"] == "forex" and row["display"] == "XAU/USD" and row["yahoo"] == "GC=F"
    assert FAKE["calls"][0][0] == "GC=F"


def test_report_is_persian_rtl_in_market_order_and_never_overwritten(settings, now):
    eng = engine(settings, now)
    out = run_analyze(settings, ["AAPL", "EURUSD", "BTC-USD"], engine=eng)
    html = Path(out["report"]["html"]).read_text(encoding="utf-8")
    assert 'dir="rtl"' in html and 'lang="fa"' in html
    assert html.index("فارکس (Forex)") < html.index("نزدک (NASDAQ)") < html.index("رمزارز (Cryptocurrency)")
    for section in ("بخش B", "بخش C", "توصیه سرمایه‌گذاری", "گزارش‌های تیم TradingAgents"):
        assert section in html
    second = make_report(eng.repo, settings, out["run_id"], now=now)
    assert second["html"] != out["report"]["html"]


def test_daily_run_end_to_end_with_watchlist_first(settings, now):
    settings.markets = ["forex", "nasdaq"]
    settings.universe = {"forex": ["EURUSD", "GBPUSD"], "nasdaq": ["UPP"], "nyse": [], "crypto": [], "tsx": [],
                         "tsxv": []}
    settings.watchlist = ["XAUUSD"]
    eng = engine(settings, now, {**UP, "GC=F": synthetic_bars(start_price=4000, seed=31)})
    out = run_daily(settings, engine=eng)
    assert out["status"] == "ok"
    assert FAKE["calls"][0][0] == "GC=F"  # the watchlist is analysed before the scan picks
    html = Path(out["report"]["html"]).read_text(encoding="utf-8")
    assert html.index("بخش A") < html.index("بخش B") < html.index("بخش C")
    assert "XAU/USD" in html and eng.repo.scan_rows(out["run_id"])


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
        pytest.skip("the risk officer vetoed this synthetic series; nothing to evaluate")
    later = engine(settings, now, UP)
    assert later.evaluate_open()["evaluated"] == 1
    assert later.repo.evaluations()[0]["entry_date"] > "2026-10-30"


def test_repeat_analysis_opens_no_duplicate_signal(settings, now):
    eng = engine(settings, now, UP)
    first = eng.analyze(["UPP"], "run1")[0]
    if first["label"] == "NO TRADE":
        pytest.skip("the risk officer vetoed this synthetic series; nothing to duplicate")
    second = engine(settings, now, UP).analyze(["UPP"], "run2")[0]
    assert len(eng.repo.signals(status="open")) == 1
    assert any("هنوز فعال است" in r for r in second["decision_json"]["reasons_fa"])


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
