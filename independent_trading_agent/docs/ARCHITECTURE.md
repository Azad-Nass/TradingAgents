# Architecture

TradingAgents is the analysis engine. This app decides *which* symbols it analyses (watchlist, then scan
picks), runs it in a child process, adds FRED macro and a Gemini sentiment reading, and applies the controls
it does not have: data quality, risk vetoes and sizing, one open signal per symbol, evaluation and reporting.

```
independent_trading_agent/
├── main.py, __main__.py      CLI (argparse): status, analyze, scan, daily, report, evaluate, backtest, serve, audit-isolation
├── config/                   settings.py (defaults → settings.toml → INDEPENDENT_AGENT_* env), example TOML
├── core/                     markets.py (priority, calendars, sessions, symbols incl. XAU/USD), data_provider.py
│                             (Yahoo daily prices + request budget), quality.py, runtime.py (lock, redacting logs)
├── analysis/                 indicators.py (causal TA), levels.py (pivots, S/R, breakouts), prepare.py (bars → frame)
├── agents/                   base.py, macro_analyst (FRED), sentiment_analyst (Gemini on TradingAgents' news report),
│                             trader (plan; uses TradingAgents' stop/target when sane), risk_officer, chief
│                             (decide_tradingagents; the rule-based decide/technical_analyst/researchers serve
│                             the scan pre-filter and its backtest), narrative (Persian template)
├── market_scanner/           scanner.py (universe → quality/liquidity filter → technical score → candidates)
├── risk_management/          sizing.py (stocks/crypto units, forex lots & pip value, metals in ounces, costs)
├── portfolio/                exposure.py (by market, net currency, concentration)
├── performance/              evaluate.py (outcome rules, metrics, calibration), backtest.py (pre-filter replay)
├── database/                 db.py (SQLite, tables ita_*; TradingAgents output in ita_analyses.ta_json)
├── integrations/             tradingagents_adapter.py + ta_worker.py (engine, child process), fred.py,
│                             llm_client.py (OpenAI-compatible chain, call budget)
├── app/                      pipeline.py (Engine), runs.py (locked, recorded runs + report)
├── reporting/                daily_report.py (Persian RTL HTML, sections A/B/C), pdf.py (headless Edge/Chrome)
├── dashboard/                server.py (127.0.0.1 JSON API + jobs), static/ (index.html, styles.css, app.js)
├── desktop/                  launch/stop scripts, desktop shortcut, icon
├── scheduler/                windows_task.ps1, examples.md (optional; not installed by default)
├── tests/                    offline tests; TradingAgents, FRED and LLM keys are cut off in every test
└── data/ logs/ reports/      runtime output (git-ignored)
```

## Decision flow

```
Yahoo daily bars ──► drop incomplete / close-less bars ──► quality check ──┬─► (fail) NO TRADE, no LLM spent
                                                                         ▼
          TradingAgents (child process, capped runs per day, timeout):
          market analyst · news analyst (+FRED) · fundamentals (SEC EDGAR, stocks) ──► bull/bear debate
          ──► research manager ──► trader (entry, stop) ──► risk team ──► portfolio manager (rating, target)
                                                                         ▼
       FRED macro view (rate differential / real yield)    Gemini sentiment of TradingAgents' news report
                                                                         ▼
  direction from the rating ──► plan (TradingAgents' stop if 0.5–4 ATR, else ATR/levels) ──► risk officer
                                                                         ▼
  chief: bad data / engine failure / run cap / risk veto → NO TRADE · Hold → HOLD
         Buy→STRONG BUY, Overweight→BUY, Underweight→SELL, Sell→STRONG SELL;
         a strong FRED or sentiment opposition weakens STRONG by one step
                                                                         ▼
               ita_analyses (+ ita_signals, one open per symbol) ──► report / dashboard
```

## Components that make up an analysis

| Role | Where | Inputs | Output |
|---|---|---|---|
| Analysts, debate, trader, risk team, portfolio manager | TradingAgents via integrations/ta_worker.py | its own data vendors (Yahoo prices, SEC EDGAR, FRED, news) and LLM chain | rating, reports, debate, entry/stop, target, horizon |
| Macro Analyst | agents/macro_analyst.py | FRED as of the date: policy/interbank rates, CPI, DFII10 | rate differential or real-yield trend; stale data flagged and unused |
| Market Sentiment Analyst | agents/sentiment_analyst.py | TradingAgents' news (and sentiment) report | sentiment −1..1 with a one-line Persian reason |
| Senior Trader | agents/trader.py | direction, ATR, levels, TradingAgents' stop/target | entry zone, stop, targets, effective R:R |
| Risk Manager / CRO | agents/risk_officer.py | plan, price data, open signals | vetoes, cautions, size factor, sizing, correlations |
| Portfolio Analyst | portfolio/exposure.py | open signals | exposure, net currency, concentration warnings |
| Chief Intelligence Agent | agents/chief.py (`decide_tradingagents`) | the above | label, confidence, agreement/disagreement |

## Isolation from TradingAgents

- Nothing outside `independent_trading_agent/` is modified (`audit-isolation` and `tests/test_isolation.py` check
  it against the baseline commit in `docs/BASELINE`).
- Own settings (`INDEPENDENT_AGENT_*`), own `.env`, own SQLite file and `ita_*` tables, own logs and reports.
- Importing the app never imports `tradingagents`; the engine runs in a child process with a timeout, and its
  results, cache and memory log go to this app's `data/tradingagents_runs/`, so TradingAgents' own history is
  untouched.
