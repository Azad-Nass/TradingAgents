"""Local dashboard: a small JSON API over the app's database plus a static page.

Binds to 127.0.0.1 only. Write actions (start an analysis or a scan) need the
``X-ITA`` header and a same-origin request, so another web page cannot
trigger them. Runs started here take the same single-instance lock as the CLI
and the scheduler.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import threading
import uuid
import webbrowser
from datetime import UTC, datetime, time, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from zoneinfo import ZoneInfo

from ..core.markets import FOREX_SESSIONS, MARKETS, PRIORITY_ORDER, SESSION_NAMES_FA, market_status
from ..core.runtime import AlreadyRunning, redact
from ..database.db import Repository
from ..performance.evaluate import grouped_metrics, metrics
from ..portfolio.exposure import exposure

logger = logging.getLogger(__name__)
STATIC = Path(__file__).resolve().parent / "static"
HOST = "127.0.0.1"
LIGHT_FIELDS = ("id", "symbol", "display", "market", "created_utc", "data_as_of", "last_price", "label",
                "confidence", "data_source", "run_id")


def _ribbon(now: datetime, tz_name: str) -> dict:
    """Forex sessions on the report-timezone day, in minutes from local midnight."""
    tz = ZoneInfo(tz_name)
    local_now = now.astimezone(tz)
    midnight = datetime.combine(local_now.date(), time(0), tzinfo=tz)
    sessions = []
    for key, (stz, start, end) in FOREX_SESSIONS.items():
        for day_offset in (-1, 0, 1):
            d = (local_now + timedelta(days=day_offset)).astimezone(ZoneInfo(stz)).date()
            s = datetime.combine(d, start, tzinfo=ZoneInfo(stz))
            e = datetime.combine(d, end, tzinfo=ZoneInfo(stz))
            a = (s - midnight).total_seconds() / 60
            b = (e - midnight).total_seconds() / 60
            if b > 0 and a < 1440 and d.weekday() < 5:
                sessions.append({"key": key, "name_fa": SESSION_NAMES_FA[key], "start": max(0, a), "end": min(1440, b),
                                 "start_label": s.astimezone(tz).strftime("%H:%M"),
                                 "end_label": e.astimezone(tz).strftime("%H:%M")})
    return {"timezone": tz_name, "now": (local_now - midnight).total_seconds() / 60,
            "now_label": local_now.strftime("%H:%M"), "date": local_now.date().isoformat(), "sessions": sessions}


def _latest_per_symbol(rows: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in rows:
        if r["symbol"] in seen:
            continue
        seen.add(r["symbol"])
        d = r.get("decision_json") or {}
        item = {k: r.get(k) for k in LIGHT_FIELDS}
        item.update({"score": d.get("score"), "label_fa": d.get("label_fa"), "conflict": d.get("conflict"),
                     "quality_ok": (r.get("quality_json") or {}).get("ok"),
                     "quality_warnings": len((r.get("quality_json") or {}).get("warnings") or []),
                     "rr": (r.get("plan_json") or {}).get("effective_reward_risk"),
                     "priority": MARKETS.get(r["market"], MARKETS["other"]).priority})
        out.append(item)
    return sorted(out, key=lambda x: (x["priority"], x["symbol"]))


class Api:
    def __init__(self, settings):
        self.settings = settings
        self.repo = Repository(settings.db_path)
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()

    # -------------------------------------------------------------- reads ---
    def overview(self) -> dict:
        s, now = self.settings, datetime.now(UTC)
        live_open = self.repo.signals(mode="live", status="open")
        evals = self.repo.evaluations("live")
        m = metrics(evals, s.risk_per_trade_pct)
        latest_scan = self.repo.latest_run("daily") or self.repo.latest_run("scan")
        top = []
        if latest_scan:
            rows = [r for r in self.repo.scan_rows(latest_scan["id"]) if r["included"]]
            top = sorted(rows, key=lambda r: -(r["interest"] or 0))[:10]
        ex = exposure([{"symbol": x["symbol"], "market": x["market"], "direction": x["direction"],
                        "sizing": x.get("sizing_json")} for x in live_open], s.portfolio_value)
        analyses = _latest_per_symbol(self.repo.analyses(limit=300))
        alerts = list(ex["warnings"])
        alerts += [f"{a['display']}: کیفیت داده نامعتبر" for a in analyses if a["quality_ok"] is False][:5]
        runs = self.repo.runs(8)
        last_errors = (runs[0].get("errors_json") or []) if runs else []
        return {
            "now_utc": now.isoformat(timespec="seconds"),
            "ribbon": _ribbon(now, s.report_timezone),
            "markets": [{"key": k, "name": MARKETS[k].name, "name_fa": MARKETS[k].name_fa,
                         "priority": MARKETS[k].priority, "enabled": k in s.markets,
                         **market_status(k, now)} for k in PRIORITY_ORDER],
            "kpis": {"open_signals": len(live_open), "analyses": len(analyses), "evaluated": m.get("n", 0),
                     "win_rate": m.get("win_rate"), "avg_return": m.get("avg_return"),
                     "total_risk_pct": ex["total_risk_pct"]},
            "top": [{"symbol": r["symbol"], "market": r["market"], "score": r["score"], "interest": r["interest"],
                     "flags": r.get("flags_json") or []} for r in top],
            "scan_run": {k: latest_scan[k] for k in ("id", "kind", "started_utc")} if latest_scan else None,
            "alerts": alerts, "last_errors": [redact(str(x)) for x in last_errors][:6],
            "runs": [{k: r[k] for k in ("id", "kind", "status", "started_utc", "finished_utc")} for r in runs],
            "reports": self.reports()[:5],
            "settings": {"markets": s.enabled_markets(), "timezone": s.report_timezone, "portfolio_value":
                         s.portfolio_value, "account_currency": s.account_currency, "risk_pct": s.risk_per_trade_pct,
                         "llm_enabled": s.llm_enabled, "tradingagents_enabled": s.tradingagents_enabled},
            "demo": False,
        }

    def analyses(self, market: str | None) -> list[dict]:
        rows = self.repo.analyses(market=market, limit=400)
        return _latest_per_symbol(rows)

    def analysis(self, analysis_id: str) -> dict | None:
        row = self.repo.analysis(analysis_id)
        if row:
            history = [{"id": a["id"], "created_utc": a["created_utc"], "label": a["label"]}
                       for a in self.repo.analyses(limit=400) if a["symbol"] == row["symbol"]][:12]
            row["history"] = history
        return row

    def performance(self, mode: str) -> dict:
        s = self.settings
        evals = self.repo.evaluations(mode)
        m = metrics(evals, s.risk_per_trade_pct)
        return {"mode": mode, "metrics": m, "by_market": grouped_metrics(evals, "market", s.risk_per_trade_pct),
                "by_label": grouped_metrics(evals, "label", s.risk_per_trade_pct),
                "period": [evals[0]["issued_utc"][:10], evals[-1]["issued_utc"][:10]] if evals else None,
                "signals": self.repo.signals(mode=mode, limit=200 if mode == "live" else 100)}

    def risk(self) -> dict:
        s = self.settings
        open_rows = self.repo.signals(mode="live", status="open")
        ex = exposure([{"symbol": x["symbol"], "market": x["market"], "direction": x["direction"],
                        "sizing": x.get("sizing_json")} for x in open_rows], s.portfolio_value)
        return {"exposure": ex, "open": open_rows, "portfolio_value": s.portfolio_value,
                "account_currency": s.account_currency, "risk_pct": s.risk_per_trade_pct,
                "min_rr": s.min_reward_risk, "max_open": s.max_open_signals}

    def reports(self) -> list[dict]:
        base = Path(self.settings.reports_dir).resolve()
        out = []
        for r in self.repo.reports(200):
            item = {"id": r["id"], "kind": r["kind"], "created_utc": r["created_utc"], "run_id": r["run_id"]}
            for key in ("path_html", "path_pdf"):
                p = r.get(key)
                if p and Path(p).resolve().is_relative_to(base) and Path(p).exists():
                    item[key.replace("path_", "")] = "/reports/" + Path(p).resolve().relative_to(base).as_posix()
            out.append(item)
        return out

    # -------------------------------------------------------------- jobs ---
    def start_job(self, kind: str, payload: dict) -> dict:
        from ..app.runs import run_analyze, run_scan
        from ..config.settings import load_settings

        if kind == "analyze":
            symbols = [str(x).strip() for x in payload.get("symbols", []) if str(x).strip()][:10]
            if not symbols:
                return {"error": "حداقل یک نماد وارد کنید"}
        job_id = uuid.uuid4().hex[:10]
        job = {"id": job_id, "kind": kind, "status": "running", "started_utc": datetime.now(UTC).isoformat(
            timespec="seconds"), "result": None, "error": None}
        with self.lock:
            if any(j["status"] == "running" for j in self.jobs.values()):
                return {"error": "یک اجرای دیگر در جریان است؛ پس از پایان آن دوباره تلاش کنید"}
            self.jobs[job_id] = job

        def work():
            try:
                settings = load_settings()
                if kind == "analyze":
                    out = run_analyze(settings, symbols, report=True, market=payload.get("market") or None)
                    job["result"] = {"run_id": out["run_id"], "labels": out["summary"].get("labels"),
                                     "errors": out["errors"][:5]}
                else:
                    out = run_scan(settings, analyze=True, report=True)
                    job["result"] = {"run_id": out["run_id"], "deep": out["summary"].get("deep"),
                                     "errors": out["errors"][:5]}
                job["status"] = "done"
            except AlreadyRunning:
                job["status"], job["error"] = "failed", "اجرای دیگری (CLI یا زمان‌بند) در جریان است"
            except Exception as exc:
                logger.exception("dashboard job failed")
                job["status"], job["error"] = "failed", redact(f"{type(exc).__name__}: {exc}")

        threading.Thread(target=work, daemon=True).start()
        return job


def make_handler(api: Api, port: int):
    origin = f"http://{HOST}:{port}"

    class Handler(BaseHTTPRequestHandler):
        server_version = "ITA/0.1"

        def log_message(self, fmt, *args):
            logger.debug("dashboard: " + fmt, *args)

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, code: int = 200):
            self._send(code, json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _file(self, path: Path, base: Path):
            try:
                resolved = path.resolve()
                if not resolved.is_relative_to(base.resolve()) or not resolved.is_file():
                    return self._json({"error": "not found"}, 404)
            except (OSError, ValueError):
                return self._json({"error": "not found"}, 404)
            ctype = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript",):
                ctype += "; charset=utf-8"
            self._send(200, resolved.read_bytes(), ctype)

        def do_GET(self):
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            path = url.path
            try:
                if path in ("/", "/index.html"):
                    return self._file(STATIC / "index.html", STATIC)
                if path.startswith("/static/"):
                    return self._file(STATIC / unquote(path[len("/static/"):]), STATIC)
                if path.startswith("/reports/"):
                    base = Path(api.settings.reports_dir)
                    return self._file(base / unquote(path[len("/reports/"):]), base)
                if path == "/api/overview":
                    return self._json(api.overview())
                if path == "/api/analyses":
                    return self._json(api.analyses(q.get("market")))
                if path.startswith("/api/analysis/"):
                    row = api.analysis(path.rsplit("/", 1)[1])
                    return self._json(row) if row else self._json({"error": "not found"}, 404)
                if path == "/api/performance":
                    return self._json(api.performance("backtest" if q.get("mode") == "backtest" else "live"))
                if path == "/api/risk":
                    return self._json(api.risk())
                if path == "/api/reports":
                    return self._json(api.reports())
                if path.startswith("/api/jobs/"):
                    job = api.jobs.get(path.rsplit("/", 1)[1])
                    return self._json(job) if job else self._json({"error": "not found"}, 404)
                return self._json({"error": "not found"}, 404)
            except Exception as exc:
                logger.exception("dashboard GET failed")
                return self._json({"error": redact(f"{type(exc).__name__}: {exc}")}, 500)

        def do_POST(self):
            if self.headers.get("X-ITA") != "1" or self.headers.get("Origin") not in (None, origin):
                return self._json({"error": "forbidden"}, 403)
            length = min(int(self.headers.get("Content-Length") or 0), 10_000)
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "bad json"}, 400)
            path = urlparse(self.path).path
            if path == "/api/analyze":
                job = api.start_job("analyze", payload)
            elif path == "/api/scan":
                job = api.start_job("scan", payload)
            else:
                return self._json({"error": "not found"}, 404)
            return self._json(job, 409 if "error" in job and "id" not in job else 202)

    return Handler


def serve(settings, port: int = 8765, open_browser: bool = True) -> None:
    api = Api(settings)
    httpd = ThreadingHTTPServer((HOST, port), make_handler(api, port))
    url = f"http://{HOST}:{port}/"
    print(f"Dashboard: {url}  (Ctrl+C to stop)", flush=True)
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
