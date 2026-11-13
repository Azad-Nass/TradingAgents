"""Portfolio Analyst: exposure and concentration of the open hypothetical signals."""
from __future__ import annotations

from collections import Counter, defaultdict

from ..core.markets import forex_pair

NAME, ROLE = "portfolio_analyst", "تحلیلگر پرتفوی"


def exposure(open_signals: list[dict], portfolio_value: float) -> dict:
    """Counts, notional and risk by market, net currency exposure (forex) and concentration."""
    by_market: dict[str, dict] = defaultdict(lambda: {"count": 0, "notional": 0.0, "risk": 0.0})
    currency: dict[str, float] = defaultdict(float)
    for s in open_signals:
        sizing = s.get("sizing") or {}
        notional = float(sizing.get("notional_account") or 0)
        m = by_market[s["market"]]
        m["count"] += 1
        m["notional"] += notional
        m["risk"] += float(sizing.get("risk_amount") or 0)
        pair = forex_pair(s["symbol"]) if s["market"] == "forex" else None
        if pair:
            currency[pair[0]] += s["direction"] * notional
            currency[pair[1]] -= s["direction"] * notional
    total_notional = sum(m["notional"] for m in by_market.values())
    total_risk = sum(m["risk"] for m in by_market.values())
    direction_count = Counter("long" if s["direction"] > 0 else "short" for s in open_signals)
    largest = max(by_market.items(), key=lambda kv: kv[1]["notional"], default=(None, None))
    warnings = []
    if total_risk > 0.05 * portfolio_value:
        warnings.append(f"ریسک باز مجموع {total_risk / portfolio_value:.1%} پرتفوی است (بیش از ۵٪)")
    if largest[0] and total_notional and largest[1]["notional"] / total_notional > 0.6 and len(open_signals) > 2:
        warnings.append(f"تمرکز بالا در بازار {largest[0]}")
    for ccy, amount in currency.items():
        if abs(amount) > 3 * portfolio_value:
            warnings.append(f"مواجهه خالص زیاد با {ccy}")
    return {
        "open_count": len(open_signals),
        "by_market": dict(by_market),
        "currency_net": {k: round(v, 2) for k, v in sorted(currency.items(), key=lambda kv: -abs(kv[1]))},
        "total_notional": round(total_notional, 2),
        "total_risk": round(total_risk, 2),
        "total_risk_pct": round(total_risk / portfolio_value * 100, 2) if portfolio_value else None,
        "gross_leverage": round(total_notional / portfolio_value, 2) if portfolio_value else None,
        "long_short": dict(direction_count),
        "warnings": warnings,
    }
