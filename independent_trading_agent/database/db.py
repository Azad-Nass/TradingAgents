"""The app's own SQLite store (``data/independent_agent.db``).

Tables are prefixed ``ita_`` so they can never be mistaken for anything
TradingAgents keeps. ``mode`` separates live analyses from backtest replays
and labelled demo rows, and metrics are always computed per mode.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS ita_runs (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, mode TEXT NOT NULL DEFAULT 'live',
    started_utc TEXT NOT NULL, finished_utc TEXT, status TEXT NOT NULL,
    settings_json TEXT, summary_json TEXT, errors_json TEXT
);
CREATE TABLE IF NOT EXISTS ita_analyses (
    id TEXT PRIMARY KEY, run_id TEXT, mode TEXT NOT NULL DEFAULT 'live',
    symbol TEXT NOT NULL, display TEXT, yahoo TEXT, market TEXT NOT NULL, created_utc TEXT NOT NULL,
    data_as_of TEXT, last_price REAL, data_source TEXT, quality_json TEXT, opinions_json TEXT,
    debate_json TEXT, decision_json TEXT, label TEXT, confidence REAL, plan_json TEXT, risk_json TEXT,
    narrative TEXT, narrative_source TEXT, chart_json TEXT, news_json TEXT, scan_json TEXT,
    model_info_json TEXT, ta_json TEXT
);
CREATE INDEX IF NOT EXISTS ita_analyses_symbol ON ita_analyses(symbol, created_utc);
CREATE TABLE IF NOT EXISTS ita_signals (
    id TEXT PRIMARY KEY, analysis_id TEXT, mode TEXT NOT NULL DEFAULT 'live',
    symbol TEXT NOT NULL, yahoo TEXT, market TEXT NOT NULL, issued_utc TEXT NOT NULL, data_as_of TEXT NOT NULL,
    ref_price REAL, direction INTEGER NOT NULL, label TEXT NOT NULL, entry_low REAL, entry_high REAL,
    stop REAL, targets_json TEXT, horizon_bars INTEGER, confidence REAL, evidence_json TEXT,
    sizing_json TEXT, config_json TEXT, status TEXT NOT NULL DEFAULT 'open'
);
CREATE INDEX IF NOT EXISTS ita_signals_status ON ita_signals(mode, status);
CREATE TABLE IF NOT EXISTS ita_evaluations (
    signal_id TEXT PRIMARY KEY, evaluated_utc TEXT NOT NULL, entry_date TEXT, entry_price REAL,
    exit_date TEXT, exit_price REAL, exit_reason TEXT, bars_held INTEGER, gross_return REAL,
    cost REAL, net_return REAL, r_multiple REAL
);
CREATE TABLE IF NOT EXISTS ita_scan_results (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, created_utc TEXT NOT NULL, symbol TEXT NOT NULL,
    market TEXT NOT NULL, included INTEGER NOT NULL, reason TEXT, score REAL, interest REAL,
    rank INTEGER, flags_json TEXT, metrics_json TEXT
);
CREATE TABLE IF NOT EXISTS ita_reports (
    id TEXT PRIMARY KEY, run_id TEXT, kind TEXT NOT NULL, created_utc TEXT NOT NULL,
    path_html TEXT NOT NULL, path_pdf TEXT
);
"""

JSON_COLS = {c for c in ("settings_json", "summary_json", "errors_json", "quality_json", "opinions_json",
                         "debate_json", "decision_json", "plan_json", "risk_json", "chart_json", "news_json",
                         "scan_json", "model_info_json", "targets_json", "evidence_json", "sizing_json",
                         "config_json", "flags_json", "metrics_json", "ta_json")}


def now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def _encode(row: dict) -> dict:
    return {k: (json.dumps(v, ensure_ascii=False, default=str) if k in JSON_COLS and v is not None else v)
            for k, v in row.items()}


def _decode(row: sqlite3.Row) -> dict:
    out = dict(row)
    for k in JSON_COLS & out.keys():
        if out[k] is not None:
            out[k] = json.loads(out[k])
    return out


class Repository:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript(SCHEMA)
            cols = {r[1] for r in con.execute("PRAGMA table_info(ita_analyses)")}
            if "ta_json" not in cols:  # databases created before TradingAgents became the engine
                con.execute("ALTER TABLE ita_analyses ADD COLUMN ta_json TEXT")

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def _insert(self, table: str, row: dict) -> str:
        row = _encode(row)
        cols = ", ".join(row)
        marks = ", ".join(f":{c}" for c in row)
        with self.connect() as con:
            con.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", row)
        return row.get("id") or row.get("signal_id")

    def _select(self, sql: str, params=()) -> list[dict]:
        with self.connect() as con:
            return [_decode(r) for r in con.execute(sql, params).fetchall()]

    # runs
    def start_run(self, kind: str, settings: dict, mode: str = "live") -> str:
        return self._insert("ita_runs", {"id": new_id(), "kind": kind, "mode": mode, "started_utc": now_utc(),
                                         "status": "running", "settings_json": settings})

    def finish_run(self, run_id: str, status: str, summary: dict | None = None, errors: list | None = None):
        with self.connect() as con:
            con.execute("UPDATE ita_runs SET finished_utc=?, status=?, summary_json=?, errors_json=? WHERE id=?",
                        (now_utc(), status, json.dumps(summary or {}, ensure_ascii=False, default=str),
                         json.dumps(errors or [], ensure_ascii=False, default=str), run_id))

    def runs(self, limit: int = 20) -> list[dict]:
        return self._select("SELECT * FROM ita_runs ORDER BY started_utc DESC LIMIT ?", (limit,))

    # analyses and signals
    def add_analysis(self, row: dict) -> str:
        row.setdefault("id", new_id())
        row.setdefault("created_utc", now_utc())
        return self._insert("ita_analyses", row)

    def analyses(self, *, mode: str = "live", market: str | None = None, run_id: str | None = None,
                 limit: int = 50) -> list[dict]:
        sql, params = "SELECT * FROM ita_analyses WHERE mode=?", [mode]
        if market:
            sql += " AND market=?"
            params.append(market)
        if run_id:
            sql += " AND run_id=?"
            params.append(run_id)
        sql += " ORDER BY created_utc DESC LIMIT ?"
        params.append(limit)
        return self._select(sql, params)

    def analysis(self, analysis_id: str) -> dict | None:
        rows = self._select("SELECT * FROM ita_analyses WHERE id=?", (analysis_id,))
        return rows[0] if rows else None

    def add_signal(self, row: dict) -> str:
        row.setdefault("id", new_id())
        return self._insert("ita_signals", row)

    def signals(self, *, mode: str = "live", status: str | None = None, limit: int = 500) -> list[dict]:
        sql, params = ("SELECT s.*, e.exit_reason, e.net_return, e.r_multiple, e.exit_date, e.entry_price, "
                       "e.exit_price, e.bars_held FROM ita_signals s LEFT JOIN ita_evaluations e "
                       "ON e.signal_id = s.id WHERE s.mode=?"), [mode]
        if status:
            sql += " AND s.status=?"
            params.append(status)
        else:
            sql += " AND s.status != 'duplicate'"  # repeats of a still-open signal are kept but not listed
        sql += " ORDER BY s.issued_utc DESC LIMIT ?"
        params.append(limit)
        return self._select(sql, params)

    def add_evaluation(self, row: dict, status: str = "closed"):
        row.setdefault("evaluated_utc", now_utc())
        self._insert("ita_evaluations", row)
        with self.connect() as con:
            con.execute("UPDATE ita_signals SET status=? WHERE id=?", (status, row["signal_id"]))

    def evaluations(self, mode: str = "live") -> list[dict]:
        return self._select("SELECT e.*, s.symbol, s.market, s.label, s.direction, s.confidence, s.issued_utc "
                            "FROM ita_evaluations e JOIN ita_signals s ON s.id = e.signal_id WHERE s.mode=? "
                            "ORDER BY s.issued_utc", (mode,))

    # scan results and reports
    def add_scan_rows(self, run_id: str, rows: list[dict]):
        created = now_utc()
        for r in rows:
            self._insert("ita_scan_results", {"id": new_id(), "run_id": run_id, "created_utc": created, **r})

    def scan_rows(self, run_id: str) -> list[dict]:
        return self._select("SELECT * FROM ita_scan_results WHERE run_id=? ORDER BY included DESC, rank", (run_id,))

    def latest_run(self, kind: str | None = None, status: str = "ok") -> dict | None:
        sql, params = "SELECT * FROM ita_runs WHERE status=?", [status]
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        rows = self._select(sql + " ORDER BY started_utc DESC LIMIT 1", params)
        return rows[0] if rows else None

    def add_report(self, run_id: str | None, kind: str, path_html: str, path_pdf: str | None) -> str:
        return self._insert("ita_reports", {"id": new_id(), "run_id": run_id, "kind": kind, "created_utc": now_utc(),
                                            "path_html": path_html, "path_pdf": path_pdf})

    def reports(self, limit: int = 60) -> list[dict]:
        return self._select("SELECT * FROM ita_reports ORDER BY created_utc DESC LIMIT ?", (limit,))
