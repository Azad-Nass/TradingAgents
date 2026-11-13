"""Command line of the Independent Trading Agent.

    python -m independent_trading_agent <command> [options]

Commands: status, analyze, scan, daily, report, evaluate, backtest, serve,
audit-isolation. Run from the folder that contains ``independent_trading_agent``.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):  # allow "python independent_trading_agent/main.py"
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "independent_trading_agent"

from independent_trading_agent import __version__  # noqa: E402
from independent_trading_agent.config.settings import PACKAGE_DIR, load_settings, secret  # noqa: E402
from independent_trading_agent.core.runtime import AlreadyRunning, setup_logging  # noqa: E402


def _print(text: str = "") -> None:
    sys.stdout.write(text + "\n")


def cmd_status(settings, args) -> int:
    from .database.db import Repository
    from .integrations import tradingagents_adapter
    from .reporting.pdf import find_browser

    repo = Repository(settings.db_path)
    keys = {name: bool(secret(name)) for name in ("GEMINI_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY",
                                                 "FRED_API_KEY")}
    _print(f"Independent Trading Agent {__version__}")
    _print(f"  folder:        {PACKAGE_DIR}")
    _print(f"  database:      {settings.db_path}")
    _print(f"  reports:       {settings.reports_dir}")
    _print(f"  markets:       {', '.join(settings.enabled_markets())}  (priority order)")
    _print(f"  watchlist:     {', '.join(settings.watchlist) or '-'}")
    _print(f"  LLM enabled:   {settings.llm_enabled}  chain: {settings.llm_chain}")
    _print("  keys present:  " + ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in keys.items()))
    _print(f"  TradingAgents: enabled={settings.tradingagents_enabled}, installed={tradingagents_adapter.is_available()}")
    _print(f"  PDF browser:   {find_browser() or 'not found'}")
    _print(f"  live signals:  {len(repo.signals(mode='live'))} (open {len(repo.signals(mode='live', status='open'))})")
    _print(f"  reports:       {len(repo.reports(10000))}")
    return 0


def _summary_line(row: dict) -> str:
    d = row.get("decision_json") or {}
    return (f"  {row['display']:<10} {row['market']:<7} {row['label']:<11} score={d.get('score', 0):+.2f} "
            f"conf={d.get('confidence', 0):.0%} data={row.get('data_as_of')} price={row.get('last_price')}")


def cmd_analyze(settings, args) -> int:
    from .app.runs import run_analyze

    out = run_analyze(settings, args.symbols, deep=args.deep, report=not args.no_report, market=args.market)
    _print(f"run {out['run_id']}")
    for row in out["analyses"]:
        _print(_summary_line(row))
    if out.get("report"):
        _print(f"report: {out['report']['html']}")
        _print(f"pdf:    {out['report']['pdf'] or out['report']['pdf_note']}")
    for err in out["errors"]:
        _print(f"  ! {err}")
    return 0


def cmd_scan(settings, args) -> int:
    from .app.runs import run_scan

    if args.markets:
        settings.markets = [m.strip() for m in args.markets.split(",")]
    if args.top:
        settings.top_n = args.top
    out = run_scan(settings, analyze=not args.no_analysis, report=args.report)
    res = out["scan"]
    _print(f"run {out['run_id']}: {len(res.candidates)} symbols, {len(res.included())} passed quality/liquidity")
    for market, reason in res.skipped_markets.items():
        _print(f"  skipped {market}: {reason}")
    for title, direction in (("top bullish", 1), ("top bearish", -1)):
        _print(f" {title}:")
        for c in res.top(direction, settings.top_n):
            _print(f"  {c.symbol:<10} {c.market:<7} score={c.score:+.2f} interest={c.interest:.2f} {'; '.join(c.flags)}")
    for row in out["analyses"]:
        _print(_summary_line(row))
    if out.get("report"):
        _print(f"report: {out['report']['html']}")
    for err in out["errors"]:
        _print(f"  ! {err}")
    return 0


def cmd_daily(settings, args) -> int:
    from .app.runs import run_daily

    out = run_daily(settings, force=args.force, pdf=False if args.no_pdf else None)
    if out.get("skipped"):
        _print(f"skipped: {out['reason']}")
        return 0
    _print(f"run {out['run_id']} status={out['status']}")
    _print(f"report: {out['report']['html']}")
    _print(f"pdf:    {out['report']['pdf'] or out['report']['pdf_note']}")
    for err in out["errors"]:
        _print(f"  ! {err}")
    return 0 if out["status"] == "ok" else 2


def cmd_report(settings, args) -> int:
    from .app.runs import make_report
    from .database.db import Repository

    repo = Repository(settings.db_path)
    run = None
    if args.run_id:
        run = next((r for r in repo.runs(500) if r["id"] == args.run_id), None)
    else:
        run = repo.latest_run("daily") or repo.latest_run()
    if not run:
        _print("no finished run in the database yet; run 'daily', 'scan --report' or 'analyze' first")
        return 1
    out = make_report(repo, settings, run["id"], pdf=False if args.no_pdf else None)
    _print(f"report: {out['html']}")
    _print(f"pdf:    {out['pdf'] or out['pdf_note']}")
    return 0


def cmd_evaluate(settings, args) -> int:
    from .app.pipeline import Engine
    from .core.runtime import RunLock
    from .performance.evaluate import metrics

    with RunLock(settings.lock_path):
        engine = Engine(settings)
        res = engine.evaluate_open()
    _print(json.dumps(res, ensure_ascii=False))
    m = metrics(engine.repo.evaluations("live"), settings.risk_per_trade_pct)
    m.pop("equity_curve", None)
    _print(json.dumps(m, ensure_ascii=False, default=str))
    return 0


def cmd_backtest(settings, args) -> int:
    from .core.data_provider import RequestBudget, YahooProvider
    from .core.markets import infer_market, to_yahoo
    from .database.db import Repository, new_id
    from .performance.backtest import replay_symbol, summarize

    provider = YahooProvider(RequestBudget(settings.max_data_requests, settings.request_delay_seconds))
    repo = Repository(settings.db_path)
    run_id = repo.start_run("backtest", settings.public_dict(), mode="backtest")
    yahoo = {s: to_yahoo(s) for s in args.symbols}
    data = provider.history(list(yahoo.values()), args.period, "1d")
    all_rows = []
    for sym, y in yahoo.items():
        rows = replay_symbol(sym, data[y], settings, start=args.start, end=args.end, step=args.step)
        for r in rows:
            if r.get("net_return") is None:
                continue
            sid = repo.add_signal({"mode": "backtest", "symbol": sym, "yahoo": y, "market": infer_market(sym),
                                   "issued_utc": r["date"] + "T21:00:00+00:00", "data_as_of": r["date"],
                                   "ref_price": r["entry_price"], "direction": r["direction"], "label": r["label"],
                                   "stop": None, "targets_json": None, "horizon_bars": settings.horizon_bars,
                                   "confidence": r["confidence"], "status": "closed", "id": new_id()})
            repo.add_evaluation({"signal_id": sid, **{k: r[k] for k in (
                "entry_date", "entry_price", "exit_date", "exit_price", "exit_reason", "bars_held", "gross_return",
                "cost", "net_return", "r_multiple")}})
        all_rows.extend(rows)
        s = summarize(rows, settings.risk_per_trade_pct)
        m = s["metrics"]
        _print(f"{sym}: {s['decisions']} decisions, {s['trades']} trades, labels={s['labels']}")
        if m.get("n"):
            _print(f"   win={m['win_rate']:.0%} PF={m['profit_factor'] and round(m['profit_factor'], 2)} "
                   f"avgR={m['avg_r']:.2f} MDD={m['max_drawdown']:.1%}")
    total = summarize(all_rows, settings.risk_per_trade_pct)
    repo.finish_run(run_id, "ok", {"backtest": {k: v for k, v in total.items() if k != "metrics"},
                                   "metrics": {k: v for k, v in total["metrics"].items() if k != "equity_curve"}})
    _print("note: technical-only replay on today's symbol list (survivorship bias); not live performance.")
    return 0


def cmd_serve(settings, args) -> int:
    from .dashboard.server import serve

    serve(settings, port=args.port or settings.dashboard_port, open_browser=not args.no_browser)
    return 0


def cmd_audit(settings, args) -> int:
    """List repository changes outside this folder since the baseline commit."""
    root = PACKAGE_DIR.parent
    base = args.base
    if not base:
        baseline = (PACKAGE_DIR / "docs" / "BASELINE").read_text().strip()
        base = baseline.split("=", 1)[1]
    folder = PACKAGE_DIR.name + "/"
    changed = subprocess.run(["git", "diff", "--name-only", base], cwd=root, capture_output=True, text=True).stdout
    untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=root, capture_output=True,
                               text=True).stdout
    paths = sorted({p for p in (changed + untracked).splitlines() if p})
    outside = [p for p in paths if not p.startswith(folder)]
    _print(f"baseline {base}: {len(paths)} changed paths, {len(outside)} outside {folder}")
    for p in outside:
        _print(f"  OUTSIDE: {p}")
    return 1 if outside else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m independent_trading_agent",
                                description="Independent Trading Agent: analysis, scan and Persian daily report "
                                            "(simulation only; never places orders).")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="settings, keys present, database counts")
    a = sub.add_parser("analyze", help="mode 1: analyse chosen symbols")
    a.add_argument("symbols", nargs="+", help="e.g. EURUSD AAPL BTC-USD RY.TO GC=F")
    a.add_argument("--market", choices=["forex", "nasdaq", "nyse", "crypto", "tsx", "tsxv", "other"])
    a.add_argument("--deep", action="store_true", help="also run the TradingAgents LLM team (if enabled)")
    a.add_argument("--no-report", action="store_true")
    s = sub.add_parser("scan", help="mode 2: scan markets and analyse the best candidates")
    s.add_argument("--markets", help="comma list, e.g. forex,nasdaq")
    s.add_argument("--top", type=int)
    s.add_argument("--no-analysis", action="store_true", help="scan only, no deep analysis")
    s.add_argument("--report", action="store_true", help="write a report for this scan")
    d = sub.add_parser("daily", help="evaluate, scan, analyse, write the Persian daily report")
    d.add_argument("--force", action="store_true", help="run even when no enabled market trades today")
    d.add_argument("--no-pdf", action="store_true")
    r = sub.add_parser("report", help="rebuild a report from the database (no new data)")
    r.add_argument("--run-id")
    r.add_argument("--no-pdf", action="store_true")
    sub.add_parser("evaluate", help="evaluate open signals whose horizon has passed")
    b = sub.add_parser("backtest", help="technical-only historical replay (stored apart from live)")
    b.add_argument("symbols", nargs="+")
    b.add_argument("--period", default="5y")
    b.add_argument("--start")
    b.add_argument("--end")
    b.add_argument("--step", type=int, default=5)
    v = sub.add_parser("serve", help="local dashboard on 127.0.0.1")
    v.add_argument("--port", type=int)
    v.add_argument("--no-browser", action="store_true")
    i = sub.add_parser("audit-isolation", help="list repository changes outside this folder")
    i.add_argument("--base", help="git ref to compare with (default: docs/BASELINE)")
    return p


COMMANDS = {"status": cmd_status, "analyze": cmd_analyze, "scan": cmd_scan, "daily": cmd_daily,
            "report": cmd_report, "evaluate": cmd_evaluate, "backtest": cmd_backtest, "serve": cmd_serve,
            "audit-isolation": cmd_audit}


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    settings = load_settings()
    setup_logging(settings.logs_dir, args.verbose)
    try:
        return COMMANDS[args.command](settings, args)
    except AlreadyRunning as exc:
        _print(f"another run is in progress: {exc}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
