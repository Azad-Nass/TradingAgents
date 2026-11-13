"""Historical replay of the rule-based technical pipeline.

At each replay date the agents see only bars up to that date; the outcome is
judged on the bars after it. Fundamentals and news are left out because the
provider does not serve them point-in-time. Results are stored with
``mode='backtest'`` and never mixed with live signals.

Known limitation: the universe is today's symbol list, so delisted names are
missing (survivorship bias); the report states this.
"""
from __future__ import annotations

from datetime import UTC, datetime, time

import pandas as pd

from ..agents import chief, researchers, risk_officer, technical_analyst, trader
from ..agents.base import AnalysisContext
from ..analysis import indicators
from ..analysis.levels import find_levels
from ..core.markets import MARKETS, display_symbol, infer_market, to_yahoo
from ..core.quality import DataQuality
from ..risk_management.sizing import round_trip_cost
from .evaluate import evaluate_signal, metrics


def replay_symbol(symbol: str, bars: pd.DataFrame, settings, *, start: str | None = None, end: str | None = None,
                  step: int = 5, market: str | None = None) -> list[dict]:
    market_key = market or infer_market(symbol)
    m = MARKETS[market_key]
    has_volume = m.asset_class != "forex" and bool((bars["volume"].fillna(0).tail(60) > 0).mean() > 0.8)
    full = indicators.compute(bars, m.asset_class, has_volume)
    results = []
    idx = full.index
    positions = [i for i in range(settings.min_bars, len(idx) - 1, step)
                 if (start is None or idx[i] >= pd.Timestamp(start)) and (end is None or idx[i] <= pd.Timestamp(end))]
    for i in positions:
        past = full.iloc[:i + 1]          # bars up to and including the replay date: nothing later
        snap = indicators.snapshot(past)
        lv = find_levels(past, snap["atr14"])
        when = datetime.combine(past.index[-1].date(), time(21, 0), tzinfo=UTC)
        q = DataQuality(True, len(past), past.index[0].date().isoformat(), snap["date"], snap["date"], 0, has_volume)
        ctx = AnalysisContext(symbol, display_symbol(symbol, market_key), to_yahoo(symbol, market_key), m,
                              past[["open", "high", "low", "close", "volume"]], past, snap, lv, q, when, "replay")
        tech = technical_analyst.analyze(ctx)
        ops = [tech]
        bull, bear = researchers.build_case("bull", ops), researchers.build_case("bear", ops)
        direction = 1 if tech.score > 0 else -1 if tech.score < 0 else 0
        plan = trader.make_plan(ctx, direction, settings.horizon_bars) if direction else None
        risk = risk_officer.assess(ctx, plan, settings, lambda a, b: None) if plan else None
        dec = chief.decide(ops, bull, bear, True, risk)
        row = {"symbol": symbol, "market": market_key, "date": snap["date"], "label": dec.label,
               "direction": dec.direction, "confidence": dec.confidence, "score": dec.score}
        if dec.direction and plan:
            cost = round_trip_cost(asset_class=m.asset_class, symbol=symbol, price=plan.reference_price,
                                   forex_spread_pips=settings.forex_spread_pips,
                                   stock_spread_bps=settings.stock_spread_bps,
                                   crypto_spread_bps=settings.crypto_spread_bps,
                                   commission_bps=settings.commission_bps, slippage_bps=settings.slippage_bps)
            ev = evaluate_signal(direction=dec.direction, data_as_of=snap["date"], stop=plan.stop,
                                 target=plan.targets[0], horizon_bars=plan.horizon_bars,
                                 bars=bars.iloc[i + 1:], cost=cost)
            if ev:
                row.update(ev.to_dict())
        results.append(row)
    return results


def summarize(rows: list[dict], risk_pct: float) -> dict:
    trades = [r for r in rows if r.get("net_return") is not None]
    by_label: dict[str, int] = {}
    for r in rows:
        by_label[r["label"]] = by_label.get(r["label"], 0) + 1
    return {"decisions": len(rows), "trades": len(trades), "labels": by_label, "metrics": metrics(trades, risk_pct)}
