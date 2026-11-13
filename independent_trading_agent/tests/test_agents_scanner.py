from independent_trading_agent.agents import chief, researchers
from independent_trading_agent.agents.base import AgentOpinion, Evidence
from independent_trading_agent.agents.risk_officer import RiskAssessment
from independent_trading_agent.market_scanner.scanner import scan

from .conftest import FakeProvider, synthetic_bars


def op(agent, score, conf=0.8, stance=None):
    st = stance if stance is not None else (1 if score > 0 else -1 if score < 0 else 0)
    return AgentOpinion(agent, agent, True, score, conf, [Evidence(f"{agent} evidence", st, 1.0)])


def debate(ops):
    return researchers.build_case("bull", ops), researchers.build_case("bear", ops)


def test_bad_data_is_no_trade():
    ops = [op("technical_analyst", 0.9)]
    d = chief.decide(ops, *debate(ops), quality_ok=False, risk=RiskAssessment(True))
    assert d.label == "NO TRADE" and d.direction == 0


def test_weak_evidence_is_hold():
    ops = [op("technical_analyst", 0.05)]
    assert chief.decide(ops, *debate(ops), True, RiskAssessment(True)).label == "HOLD"


def test_serious_conflict_is_no_trade():
    # A clear net direction (+0.42) but 48% of the evidence weight points the other way.
    ops = [op("technical_analyst", 1.0, 1.0), op("fundamental_analyst", -0.2, 1.0), op("macro_analyst", -0.2, 1.0),
           op("forex_analyst", -0.2, 1.0)]
    score, conflict = chief.combine(ops)
    assert score > chief.HOLD_BAND and conflict >= chief.CONFLICT_LIMIT
    d = chief.decide(ops, *debate(ops), True, RiskAssessment(True))
    assert d.label == "NO TRADE" and "تعارض" in d.reasons_fa[0]


def test_risk_veto_is_no_trade_and_strong_needs_clean_evidence():
    ops = [op("technical_analyst", 0.8, 0.9), op("forex_analyst", 0.7, 0.5)]
    vetoed = chief.decide(ops, *debate(ops), True, RiskAssessment(False, vetoes=["R:R پایین"]))
    assert vetoed.label == "NO TRADE"
    ok = chief.decide(ops, *debate(ops), True, RiskAssessment(True))
    assert ok.label == "STRONG BUY" and ok.direction == 1
    halved = chief.decide(ops, *debate(ops), True, RiskAssessment(True, size_factor=0.5))
    assert halved.label == "BUY"


def test_not_applicable_and_zero_confidence_opinions_are_ignored():
    ops = [op("technical_analyst", -0.5, 0.8),
           AgentOpinion("fundamental_analyst", "f", False, 0.0, 0.0),
           AgentOpinion("sentiment_analyst", "s", True, 0.9, 0.0)]
    score, conflict = chief.combine(ops)
    assert score == -0.5 and conflict == 0


def test_researchers_answer_the_other_side():
    ops = [op("technical_analyst", 0.6), op("sentiment_analyst", -0.3, 0.3)]
    bull, bear = debate(ops)
    assert bull.strength > bear.strength
    assert bull.counterpoints and "وزن" in bull.counterpoints[0]["response_fa"]


def test_scan_respects_priority_budget_and_reports_exclusions(settings, now):
    settings.markets = ["nasdaq", "forex", "crypto"]
    settings.universe = {"forex": ["EURUSD", "USDJPY"], "nasdaq": ["AAA", "BBB", "CCC"], "crypto": ["BTC-USD"],
                         "nyse": [], "tsx": [], "tsxv": []}
    settings.max_symbols_per_market = 2
    settings.max_total_symbols = 3
    frames = {"AAA": synthetic_bars(drift=0.004, seed=5), "BBB": synthetic_bars(n=50, seed=6)}
    provider = FakeProvider(frames)
    res = scan(settings, provider, now)
    # forex first, then nasdaq capped by the total budget; crypto skipped
    assert [c.market for c in res.candidates][:2] == ["forex", "forex"]
    assert [c.symbol for c in res.candidates if c.market == "nasdaq"] == ["AAA"]
    assert "crypto" in res.skipped_markets
    short = synthetic_bars(n=50, seed=6)
    provider2 = FakeProvider({"AAA": short})
    settings.max_total_symbols = 60
    res2 = scan(settings, provider2, now)
    aaa = next(c for c in res2.candidates if c.symbol == "AAA")
    assert not aaa.included and "کندل کافی" in aaa.reason


def test_deep_candidates_need_min_interest_and_follow_priority(settings, now):
    settings.markets = ["forex", "nasdaq"]
    settings.universe = {"forex": ["EURUSD"], "nasdaq": ["UPP"], "nyse": [], "crypto": [], "tsx": [], "tsxv": []}
    provider = FakeProvider({"UPP": synthetic_bars(drift=0.006, vol=0.008, seed=9)})
    res = scan(settings, provider, now)
    picks = res.deep_candidates(5, settings.min_interest)
    assert all(c.interest >= settings.min_interest for c in picks)
    assert [c.priority for c in picks] == sorted(c.priority for c in picks)
    assert res.deep_candidates(5, 10.0) == []


def test_scan_survives_network_failure(settings, now):
    settings.markets = ["forex", "nasdaq"]
    provider = FakeProvider(fail={"EURUSD=X"})
    res = scan(settings, provider, now)
    assert "forex" in res.skipped_markets and res.errors
    assert any(c.market == "nasdaq" for c in res.candidates)
