"""Optional adapter to the TradingAgents project next to this folder.

The deep LLM debate runs in a child process (``ta_worker``) with a time
limit, so a missing package, a missing key or a crash there never stops this
app. TradingAgents' own files are untouched: its results, cache and memory
log are redirected into this app's data folder.
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
NAME, ROLE = "tradingagents_llm", "تیم چندعاملی TradingAgents (LLM)"


def is_available() -> bool:
    try:
        return importlib.util.find_spec("tradingagents") is not None
    except (ImportError, ValueError):
        return False


def run_deep_analysis(yahoo_symbol: str, trade_date: str, *, asset_type: str, analysts: str,
                      timeout: int, data_dir: str) -> dict:
    """``{"ok": True, "rating": ..., "summary": ...}`` or ``{"ok": False, "error": ...}``."""
    if not is_available():
        return {"ok": False, "error": "TradingAgents package is not installed in this environment"}
    out_dir = Path(data_dir) / "tradingagents_runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "independent_trading_agent.integrations.ta_worker", "--symbol", yahoo_symbol,
           "--date", trade_date, "--asset-type", asset_type, "--analysts", analysts, "--out-dir", str(out_dir)]
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
        return AgentOpinion(NAME, ROLE, True, 0.0, 0.0, [], [f"اجرای TradingAgents ناموفق: {result.get('error', '')[:200]}"],
                            "تحلیل عمیق LLM در دسترس نبود")
    rating = result.get("rating")
    score = RATING_SCORE.get(rating)
    if score is None:
        return AgentOpinion(NAME, ROLE, True, 0.0, 0.0, [], [f"رتبه قابل خواندن نبود ({rating})"], "")
    ev = [Evidence(f"رتبه نهایی تیم TradingAgents: {rating}", 1 if score > 0 else -1 if score < 0 else 0, 1.0,
                   rating, "TradingAgents (LLM multi-agent)", result.get("trade_date"))]
    if result.get("summary"):
        ev.append(Evidence(result["summary"][:400], 0, 0, None, "TradingAgents final decision"))
    return AgentOpinion(NAME, ROLE, True, score, 0.5, ev,
                        ["خروجی مدل زبانی است؛ ممکن است خطا یا توهم داشته باشد"],
                        f"TradingAgents: {rating}")
