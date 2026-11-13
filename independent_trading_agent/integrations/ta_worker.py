"""Child process that runs one TradingAgents analysis and prints a JSON line.

Run only by :mod:`tradingagents_adapter`. Everything TradingAgents writes
goes under ``--out-dir`` (this app's data folder), never its default home.
The JSON carries the rating, every agent report (trimmed), the bull/bear
debate and the trader's and portfolio manager's structured numbers.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPORT_KEYS = ("market_report", "news_report", "sentiment_report", "fundamentals_report", "investment_plan",
               "trader_investment_plan", "final_trade_decision")
LIMIT = 6000


def _number(text: str, label: str) -> float | None:
    """A number rendered as ``**Label**: 123.4`` by TradingAgents' structured agents."""
    m = re.search(rf"\*\*{re.escape(label)}\*\*\s*:\s*\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)", text or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _text(text: str, label: str) -> str | None:
    m = re.search(rf"\*\*{re.escape(label)}\*\*\s*:\s*(.+)", text or "")
    return m.group(1).strip() if m else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--asset-type", default="stock")
    parser.add_argument("--analysts", default="market,news")
    parser.add_argument("--language", default="English")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    out = Path(args.out_dir)
    try:
        from tradingagents.default_config import build_default_config
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        config = build_default_config()
        config.update({
            "results_dir": str(out / "results"),
            "data_cache_dir": str(out / "cache"),
            "memory_log_path": str(out / "memory" / "trading_memory.md"),
            "output_language": args.language,
        })
        analysts = [a.strip() for a in args.analysts.split(",") if a.strip()]
        graph = TradingAgentsGraph(selected_analysts=analysts, config=config)
        state, rating = graph.propagate(args.symbol, args.date, asset_type=args.asset_type)
        reports = {k: str(state.get(k) or "")[:LIMIT] for k in REPORT_KEYS}
        debate = state.get("investment_debate_state") or {}
        trader, final = reports["trader_investment_plan"], reports["final_trade_decision"]
        print(json.dumps({
            "ok": True, "rating": rating, "trade_date": args.date, "symbol": args.symbol, "analysts": analysts,
            "reports": reports,
            "debate": {"bull": str(debate.get("bull_history") or "")[:3000],
                       "bear": str(debate.get("bear_history") or "")[:3000]},
            "numbers": {"entry_price": _number(trader, "Entry Price"), "stop_loss": _number(trader, "Stop Loss"),
                        "price_target": _number(final, "Price Target"),
                        "time_horizon": _text(final, "Time Horizon")},
            "models": {"provider": config.get("llm_provider"), "quick": config.get("quick_think_llm"),
                       "deep": config.get("deep_think_llm"), "fallbacks": config.get("llm_fallbacks")},
        }, ensure_ascii=False))
        return 0
    except Exception as exc:  # report, never raise into the parent
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"[:800]}, ensure_ascii=False))
        return 0


if __name__ == "__main__":
    sys.exit(main())
