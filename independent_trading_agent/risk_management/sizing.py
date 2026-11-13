"""Hypothetical position sizing and trading costs. Simulation only."""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from ..core.markets import contract_size, forex_pair, is_metal, pip_size

FxRate = Callable[[str, str], "float | None"]  # (from_ccy, to_ccy) -> rate, or None


@dataclass
class Sizing:
    ok: bool
    units: float = 0.0
    lots: float | None = None
    risk_amount: float = 0.0
    stop_distance: float = 0.0
    stop_pips: float | None = None
    pip_value_per_lot: float | None = None
    notional_account: float = 0.0
    leverage: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _convert(amount_ccy: str, account_ccy: str, fx: FxRate) -> float | None:
    if amount_ccy == account_ccy:
        return 1.0
    return fx(amount_ccy, account_ccy)


def size_position(*, symbol: str, asset_class: str, quote_ccy: str, entry: float, stop: float,
                  portfolio_value: float, risk_pct: float, account_ccy: str, fx: FxRate,
                  size_factor: float = 1.0) -> Sizing:
    """Units (and lots for forex) that lose ``risk_pct`` of the portfolio at the stop."""
    risk_amount = portfolio_value * risk_pct / 100 * size_factor
    distance = abs(entry - stop)
    if distance <= 0 or entry <= 0:
        return Sizing(False, notes=["فاصله حد ضرر نامعتبر است"])

    if asset_class == "forex":
        base, quote = forex_pair(symbol)
        pip = pip_size(symbol)
        stop_pips = distance / pip
        if quote == account_ccy:
            q2a = 1.0
        elif base == account_ccy:
            q2a = 1 / entry
        else:
            q2a = fx(quote, account_ccy)
        if q2a is None:
            return Sizing(False, notes=[f"نرخ تبدیل {quote}→{account_ccy} در دسترس نیست"])
        lot = contract_size(symbol)
        pip_value = lot * pip * q2a
        lots = math.floor(round(risk_amount / (stop_pips * pip_value) * 100, 6)) / 100
        units = lots * lot
        b2a = 1.0 if base == account_ccy else entry * q2a
        notional = units * b2a
        notes = [] if lots > 0 else ["حجم محاسبه‌شده کمتر از ۰٫۰۱ لات است"]
        return Sizing(lots > 0, units, lots, lots * stop_pips * pip_value, distance, round(stop_pips, 1),
                      round(pip_value, 4), round(notional, 2), round(notional / portfolio_value, 2), notes)

    conv = _convert(quote_ccy, account_ccy, fx)
    if conv is None:
        return Sizing(False, notes=[f"نرخ تبدیل {quote_ccy}→{account_ccy} در دسترس نیست"])
    per_unit = distance * conv
    raw_units = risk_amount / per_unit
    raw_units = round(raw_units, 6)
    units = math.floor(raw_units) if asset_class == "stock" else math.floor(raw_units * 1e6) / 1e6
    notes = [] if units > 0 else ["حجم محاسبه‌شده کمتر از یک واحد است"]
    notional = units * entry * conv
    return Sizing(units > 0, units, None, units * per_unit, distance, None, None, round(notional, 2),
                  round(notional / portfolio_value, 2), notes)


def round_trip_cost(*, asset_class: str, symbol: str, price: float, forex_spread_pips: float,
                    stock_spread_bps: float, crypto_spread_bps: float, commission_bps: float,
                    slippage_bps: float, metal_spread_pips: float = 3.0) -> float:
    """Spread + commissions + slippage of entering and exiting, as a fraction of price."""
    if asset_class == "forex":
        pips = metal_spread_pips if is_metal(symbol) else forex_spread_pips
        spread = pips * pip_size(symbol) / price
        return spread + 2 * slippage_bps / 1e4
    spread_bps = crypto_spread_bps if asset_class == "crypto" else stock_spread_bps
    return spread_bps / 1e4 + 2 * commission_bps / 1e4 + 2 * slippage_bps / 1e4
