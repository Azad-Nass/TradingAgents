"""Top-level runs used by the CLI, the dashboard and the scheduler.

Every run holds the single-instance lock, is recorded in ``ita_runs`` with
its settings, status and errors, and never lets one failure hide the rest.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from ..core.markets import is_trading_day
from ..core.runtime import RunLock, redact
from ..database.db import Repository
from ..reporting import daily_report
from ..reporting.pdf import html_to_pdf
from .pipeline import Engine

logger = logging.getLogger(__name__)


def _finish(engine: Engine, run_id: str, kind: str, summary: dict, status: str = "ok") -> dict:
    budget = getattr(engine.provider, "budget", None)
    summary["data_requests"] = budget.used if budget else None
    if engine.llm:
        summary["llm"] = (f"{engine.llm.calls} فراخوانی؛ مدل‌ها: " + ("، ".join(dict.fromkeys(engine.llm.used_models))
                                                               or "پاسخی دریافت نشد"))
    engine.repo.finish_run(run_id, status, summary, engine.errors)
    return summary


def make_report(repo: Repository, settings, run_id: str, *, pdf: bool | None = None,
                now: datetime | None = None) -> dict:
    run = next((r for r in repo.runs(200) if r["id"] == run_id), None)
    if run is None:
        raise ValueError(f"run {run_id} not found")
    now = now or datetime.now(UTC)
    text = daily_report.render(repo, settings, run, now)
    kind = "daily" if run["kind"] == "daily" else "analysis"
    path = daily_report.write(text, daily_report.archive_path(settings.reports_dir, kind, now, settings.report_timezone))
    pdf_path, pdf_note = (None, "PDF غیرفعال است")
    if settings.pdf_enabled if pdf is None else pdf:
        pdf_path, pdf_note = html_to_pdf(path)
    repo.add_report(run_id, kind, str(path), str(pdf_path) if pdf_path else None)
    return {"html": str(path), "pdf": str(pdf_path) if pdf_path else None, "pdf_note": pdf_note}


def run_analyze(settings, symbols: list[str], *, report: bool = True, engine: Engine | None = None,
                market: str | None = None) -> dict:
    with RunLock(settings.lock_path):
        engine = engine or Engine(settings)
        run_id = engine.repo.start_run("analyze", settings.public_dict())
        try:
            hints = dict.fromkeys(symbols, market) if market else None
            rows = engine.analyze(symbols, run_id, market_hint=hints)
            summary = _finish(engine, run_id, "analyze", {"symbols": symbols, "labels": {r["symbol"]: r["label"]
                                                                                         for r in rows}})
        except Exception as exc:
            engine.errors.append(redact(f"{type(exc).__name__}: {exc}"))
            _finish(engine, run_id, "analyze", {}, "failed")
            raise
        out = {"run_id": run_id, "analyses": rows, "summary": summary, "errors": engine.errors}
        if report:
            out["report"] = make_report(engine.repo, settings, run_id)
        return out


def run_scan(settings, *, analyze: bool = True, report: bool = False, engine: Engine | None = None) -> dict:
    with RunLock(settings.lock_path):
        engine = engine or Engine(settings)
        run_id = engine.repo.start_run("scan", settings.public_dict())
        try:
            if analyze:
                result, rows = engine.scan_and_analyze(run_id)
            else:
                result, rows = engine.scan(run_id), []
            summary = _finish(engine, run_id, "scan", {
                "breadth": result.breadth, "skipped_markets": result.skipped_markets,
                "excluded": len([c for c in result.candidates if not c.included]),
                "deep": [r["symbol"] for r in rows]})
        except Exception as exc:
            engine.errors.append(redact(f"{type(exc).__name__}: {exc}"))
            _finish(engine, run_id, "scan", {}, "failed")
            raise
        out = {"run_id": run_id, "scan": result, "analyses": rows, "summary": summary, "errors": engine.errors}
        if report:
            out["report"] = make_report(engine.repo, settings, run_id)
        return out


def should_run_today(settings, now: datetime) -> tuple[bool, str]:
    open_markets = [m for m in settings.enabled_markets() if m != "crypto" and is_trading_day(m, now.date())]
    if open_markets:
        return True, "روز معاملاتی برای: " + "، ".join(open_markets)
    if "crypto" in settings.enabled_markets():
        return False, "فقط رمزارز فعال است و بازارهای دیگر تعطیل‌اند (برای اجرای اجباری --force)"
    return False, "امروز برای هیچ بازار فعالی روز معاملاتی نیست"


def run_daily(settings, *, force: bool = False, pdf: bool | None = None, engine: Engine | None = None,
              attempts: int = 2) -> dict:
    """Evaluate open signals, scan, analyse picks and the watchlist, write the report."""
    now = (engine.now if engine else datetime.now(UTC))
    ok, why = should_run_today(settings, now)
    if not ok and not force:
        logger.info("daily run skipped: %s", why)
        return {"skipped": True, "reason": why}
    with RunLock(settings.lock_path):
        engine = engine or Engine(settings)
        run_id = engine.repo.start_run("daily", settings.public_dict())
        status, evaluation, result, rows = "ok", {}, None, []
        try:
            evaluation = engine.evaluate_open()
            for attempt in range(attempts):
                try:
                    result, rows = engine.scan_and_analyze(run_id, extra_symbols=settings.watchlist)
                    break
                except Exception as exc:  # network trouble: limited retry, then report it
                    engine.errors.append(redact(f"attempt {attempt + 1}: {type(exc).__name__}: {exc}"))
                    if attempt == attempts - 1:
                        status = "partial"
        except Exception as exc:
            engine.errors.append(redact(f"{type(exc).__name__}: {exc}"))
            status = "partial"
        summary = {"evaluation": evaluation, "reason": why}
        if result is not None:
            summary.update({"breadth": result.breadth, "skipped_markets": result.skipped_markets,
                            "excluded": len([c for c in result.candidates if not c.included]),
                            "deep": [r["symbol"] for r in rows]})
        _finish(engine, run_id, "daily", summary, status)
        report = make_report(engine.repo, settings, run_id, pdf=pdf)
        return {"run_id": run_id, "status": status, "summary": summary, "report": report, "errors": engine.errors}


def latest_report_path(repo: Repository) -> Path | None:
    reports = repo.reports(1)
    return Path(reports[0]["path_html"]) if reports else None
