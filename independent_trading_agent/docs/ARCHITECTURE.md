# Architecture

```
independent_trading_agent/
├── main.py, __main__.py      CLI (argparse): status, analyze, scan, daily, report, evaluate, backtest, serve, audit-isolation
├── config/                   settings.py (defaults → settings.toml → INDEPENDENT_AGENT_* env), example TOML
├── core/                     markets.py (priority, calendars, sessions, symbols), data_provider.py (Yahoo + request
│                             budget), quality.py (data checks), runtime.py (lock, secret-redacting logs)
├── analysis/                 indicators.py (causal TA), levels.py (pivots, S/R, breakouts), prepare.py (bars → frame)
├── agents/                   base.py (Evidence/AgentOpinion/AnalysisContext), technical_analyst, fundamental_analyst
│                             (company + macro), news_analyst (news + sentiment), researchers (bull/bear), trader,
│                             risk_officer, chief (final decision), narrative (Persian template / LLM phrasing)
├── forex/ nasdaq/ crypto/    market specialists (sessions & currency strength; liquidity & earnings; strength vs BTC)
├── market_scanner/           scanner.py (universe → quality/liquidity filter → score → rank → deep candidates)
├── risk_management/          sizing.py (stocks/crypto units, forex lots & pip value, costs)
├── portfolio/                exposure.py (by market, net currency, concentration)
├── performance/              evaluate.py (signal outcome rules, metrics, calibration), backtest.py (replay)
├── database/                 db.py (SQLite, tables ita_*; live / backtest kept apart by `mode`)
├── integrations/             llm_client.py (OpenAI-compatible chain, call budget), fred.py (ALFRED as-of),
│                             tradingagents_adapter.py + ta_worker.py (optional child process)
├── app/                      pipeline.py (Engine), runs.py (locked, recorded runs + report)
├── reporting/                daily_report.py (Persian RTL HTML, sections A/B/C), pdf.py (headless Edge/Chrome)
├── dashboard/                server.py (127.0.0.1 JSON API + jobs), static/ (index.html, styles.css, app.js)
├── scheduler/                windows_task.ps1, examples.md (cron, launchd)
├── tests/                    53 offline tests on labelled synthetic data
└── data/ logs/ reports/      runtime output (git-ignored)
```

## Decision flow

```
provider bars ──► drop incomplete bar ──► quality check ──┬─► (fail) NO TRADE, reason stored
                                                          ▼
                       indicators + levels + context (news, fundamentals / FRED macro, peers, open signals)
                                                          ▼
 technical · fundamental|macro · news · sentiment · forex|stock|crypto specialist · [TradingAgents LLM team]
                                                          ▼
               bull researcher ◄──── evidence ────► bear researcher   (each answers the other's top points)
                                                          ▼
     combined score (weight × confidence) ──► direction ──► trader plan (ATR/levels, 2R/3R) ──► risk officer
                                                          ▼
 chief: quality fail → NO TRADE · |score|<0.15 → HOLD · conflict ≥45% → NO TRADE · risk veto → NO TRADE
        else BUY/SELL, STRONG only with |score|≥0.5, conflict<20%, technical confidence ≥0.6, full size
                                                          ▼
               ita_analyses (+ ita_signals for directional labels) ──► report / dashboard
```

## Agents

| Agent | Module | Inputs | Output |
|---|---|---|---|
| Technical Analyst | agents/technical_analyst.py | bars, indicators, levels | trend/momentum/structure/volume evidence, score, confidence |
| Fundamental Analyst | agents/fundamental_analyst.py | provider quote summary (stocks) | valuation, growth, profitability, balance sheet; "n/a" for non-companies |
| Macro Analyst (forex) | agents/fundamental_analyst.py | FRED short rates & CPI as of the date | rate differential (carry), inflation |
| News Intelligence Analyst | agents/news_analyst.py | headlines with publish time (≤ N days) | listed headlines, sources, times |
| Market Sentiment Analyst | agents/news_analyst.py | headlines | LLM or lexicon sentiment, method stated |
| Forex Analyst | forex/analyst.py | sessions, pip size, peer pairs | sessions open, ATR in pips, relative currency strength, gap risk |
| NASDAQ/Stock Analyst | nasdaq/analyst.py | liquidity, benchmark ETF, calendar | dollar volume, relative strength, earnings in horizon |
| Crypto Analyst | crypto/analyst.py | BTC benchmark | strength vs BTC, volatility regime |
| Bullish / Bearish Researcher | agents/researchers.py | all evidence | case, strength, answers to the other side |
| Senior Trader | agents/trader.py | direction, ATR, levels | entry zone, stop, 2R/3R targets, effective R:R |
| Risk Manager / CRO | agents/risk_officer.py | plan, data, open signals | vetoes, cautions, size factor, sizing, correlations |
| Portfolio Analyst | portfolio/exposure.py | open signals | exposure, net currency, concentration warnings |
| Chief Intelligence Agent | agents/chief.py | everything above | label, confidence (calibrated when n≥30), agreement/disagreement |

## Isolation from TradingAgents

- Nothing outside `independent_trading_agent/` is modified (`audit-isolation` and `tests/test_isolation.py` check
  it against the baseline commit in `docs/BASELINE`).
- Own settings (`INDEPENDENT_AGENT_*`), own `.env`, own SQLite file and `ita_*` tables, own logs and reports.
- The package is not part of TradingAgents' installed packages (its `pyproject.toml` includes only
  `tradingagents*` and `cli*`), and importing the app never imports `tradingagents`.
- The optional TradingAgents call runs in a child process with a timeout; its results, cache and memory log are
  redirected into this app's `data/tradingagents_runs/`, so TradingAgents' own history is untouched.
