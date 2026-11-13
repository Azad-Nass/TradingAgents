"""Adapter to the TradingAgents project next to this folder: the primary analysis engine.

The LLM multi-agent analysis runs in a child process (``ta_worker``) with a
time limit, so a missing package, a missing key or a crash there never stops
this app; the symbol is then recorded as NO TRADE with the reason.
TradingAgents' own files are untouched: its results, cache and memory log are
redirected into this app's data folder.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import subprocess
import sys
from pathlib import Path

from ..agents.base import AgentOpinion, Evidence
from ..config.settings import PACKAGE_DIR
from ..core.runtime import redact

logger = logging.getLogger(__name__)

RATING_SCORE = {"Buy": 0.8, "Overweight": 0.4, "Hold": 0.0, "Underweight": -0.4, "Sell": -0.8}
RATING_LABEL = {"Buy": "STRONG BUY", "Overweight": "BUY", "Hold": "HOLD", "Underweight": "SELL",
                "Sell": "STRONG SELL"}
NAME, ROLE = "tradingagents_llm", "تیم چندعاملی TradingAgents (مدل زبانی)"


def is_available() -> bool:
    try:
        return importlib.util.find_spec("tradingagents") is not None
    except (ImportError, ValueError):
        return False


def analysts_for(market_key: str, configured: dict) -> str:
    return configured.get(market_key) or configured.get("default") or "market,news"


def run_deep_analysis(yahoo_symbol: str, trade_date: str, *, asset_type: str, analysts: str, timeout: int,
                      data_dir: str, language: str = "Persian") -> dict:
    """``{"ok": True, "rating": ..., "reports": {...}, ...}`` or ``{"ok": False, "error": ...}``."""
    if not is_available():
        return {"ok": False, "error": "TradingAgents package is not installed in this environment"}
    out_dir = Path(data_dir) / "tradingagents_runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "independent_trading_agent.integrations.ta_worker", "--symbol", yahoo_symbol,
           "--date", trade_date, "--asset-type", asset_type, "--analysts", analysts, "--language", language,
           "--out-dir", str(out_dir)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, cwd=str(PACKAGE_DIR.parent))
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timed out after {timeout}s"}
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
    if proc.returncode != 0 or not lines:
        tail = redact((proc.stderr or proc.stdout or "")[-600:])
        return {"ok": False, "error": f"exit {proc.returncode}: {tail}"}
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"unreadable worker output: {exc}"}


def to_opinion(result: dict) -> AgentOpinion:
    if not result.get("ok"):
        return AgentOpinion(NAME, ROLE, True, 0.0, 0.0, [],
                            [f"اجرای TradingAgents ناموفق: {str(result.get('error', ''))[:300]}"],
                            "تحلیل TradingAgents انجام نشد")
    rating = result.get("rating")
    score = RATING_SCORE.get(rating)
    if score is None:
        return AgentOpinion(NAME, ROLE, True, 0.0, 0.0, [], [f"رتبه قابل خواندن نبود ({rating})"],
                            "رتبه نهایی TradingAgents خوانده نشد")
    n = result.get("numbers") or {}
    src, asof = "TradingAgents (LLM multi-agent)", result.get("trade_date")
    ev = [Evidence(f"رتبه نهایی مدیر پرتفوی: {rating}", 1 if score > 0 else -1 if score < 0 else 0, 1.0, rating,
                   src, asof)]
    for label, key in (("قیمت ورود پیشنهادی تریدر", "entry_price"), ("حد ضرر پیشنهادی تریدر", "stop_loss"),
                       ("هدف قیمت مدیر پرتفوی", "price_target")):
        if n.get(key) is not None:
            ev.append(Evidence(f"{label}: {n[key]:,.5g}", 0, 0, n[key], src, asof))
    if n.get("time_horizon"):
        ev.append(Evidence(f"افق زمانی: {n['time_horizon']}", 0, 0, n["time_horizon"], src, asof))
    unc = ["خروجی مدل زبانی است و ممکن است خطا یا ادعای بی‌پشتوانه داشته باشد؛ گزارش کامل را بخوانید"]
    return AgentOpinion(NAME, ROLE, True, score, 0.6 if abs(score) > 0.5 else 0.5, ev, unc,
                        f"TradingAgents: {rating}")
