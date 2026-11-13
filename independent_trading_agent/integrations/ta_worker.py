"""Child process that runs one TradingAgents analysis and prints a JSON line.

Run only by :mod:`tradingagents_adapter`. Everything TradingAgents writes
goes under ``--out-dir`` (this app's data folder), never its default home.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--asset-type", default="stock")
    parser.add_argument("--analysts", default="market,news")
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
            "output_language": "English",
        })
        analysts = [a.strip() for a in args.analysts.split(",") if a.strip()]
        graph = TradingAgentsGraph(selected_analysts=analysts, config=config)
        state, rating = graph.propagate(args.symbol, args.date, asset_type=args.asset_type)
        summary = str(state.get("final_trade_decision") or "")
        print(json.dumps({"ok": True, "rating": rating, "summary": summary[:1500], "trade_date": args.date,
                          "models": {"quick": config.get("quick_think_llm"), "deep": config.get("deep_think_llm"),
                                     "provider": config.get("llm_provider")}}, ensure_ascii=False))
        return 0
    except Exception as exc:  # report, never raise into the parent
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"[:800]}, ensure_ascii=False))
        return 0


if __name__ == "__main__":
    sys.exit(main())
