"""Market scanner: finds candidates across the enabled markets, in priority order.

A scan result is a candidate, not a signal. Candidates pass to the full agent
analysis (and risk review) only when their interest clears ``min_interest``;
market priority orders the work and the budget, it never lowers that bar.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime

from ..agents import technical_analyst
from ..agents.base import AnalysisContext
from ..analysis.prepare import prepare
from ..core.data_provider import BudgetExceeded
from ..core.markets import MARKETS, display_symbol, to_yahoo

logger = logging.getLogger(__name__)


@dataclass
class Candidate:
    symbol: str
    yahoo: str
    market: str
    priority: int
    included: bool
    reason: str = ""
    score: float = 0.0
    interest: float = 0.0
    direction: int = 0
    flags: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    rank: int | None = None

    def to_row(self) -> dict:
        return {"symbol": self.symbol, "market": self.market, "included": int(self.included), "reason": self.reason,
                "score": self.score, "interest": self.interest, "rank": self.rank, "flags_json": self.flags,
                "metrics_json": self.metrics}

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ScanResult:
    candidates: list[Candidate]
    breadth: dict[str, dict]
    errors: list[str]
    skipped_markets: dict[str, str]

    def included(self) -> list[Candidate]:
        return [c for c in self.candidates if c.included]

    def top(self, direction: int, n: int) -> list[Candidate]:
        pool = [c for c in self.included() if c.direction == direction]
        return sorted(pool, key=lambda c: (-c.interest, c.priority))[:n]

    def deep_candidates(self, k: int, min_interest: float) -> list[Candidate]:
        eligible = [c for c in self.included() if c.interest >= min_interest and c.direction]
        return sorted(eligible, key=lambda c: (c.priority, -c.interest))[:k]

    def abnormal(self) -> list[Candidate]:
        return [c for c in self.included() if any(f.startswith(("حجم", "نوسان")) for f in c.flags)]


def _flags(snap: dict, lv, has_volume: bool) -> list[str]:
    flags = []
    if lv.breakout == "up":
        flags.append("شکست سقف ۲۰ کندلی")
    elif lv.breakout == "down":
        flags.append("شکست کف ۲۰ کندلی")
    if lv.failed_breakout == "up":
        flags.append("شکست ناموفق سقف")
    elif lv.failed_breakout == "down":
        flags.append("شکست ناموفق کف")
    if has_volume and snap.get("vol_z") is not None and snap["vol_z"] >= 2:
        flags.append(f"حجم غیرعادی (z={snap['vol_z']:.1f})")
    med = snap.get("atr_pct_median_1y")
    if snap.get("atr_pct") and med and snap["atr_pct"] > 1.5 * med:
        flags.append(f"نوسان بالا (ATR {snap['atr_pct'] / med:.1f}× میانه)")
    r = snap.get("rsi14")
    if r is not None and (r >= 70 or r <= 30):
        flags.append(f"RSI در ناحیه {'اشباع خرید' if r >= 70 else 'اشباع فروش'} ({r:.0f})")
    if snap.get("sma50") and snap.get("sma200"):
        flags.append("روند بلندمدت " + ("صعودی" if snap["sma50"] > snap["sma200"] else "نزولی"))
    return flags


def scan(settings, provider, now: datetime) -> ScanResult:
    candidates: list[Candidate] = []
    breadth: dict[str, dict] = {}
    errors: list[str] = []
    skipped: dict[str, str] = {}
    total_budget = settings.max_total_symbols

    for market_key in settings.enabled_markets():
        universe = settings.universe.get(market_key) or []
        if not universe:
            skipped[market_key] = "فهرست نمادهای این بازار خالی است"
            continue
        if total_budget <= 0:
            skipped[market_key] = "سقف کل نمادهای پویش پر شد"
            continue
        symbols = universe[: min(settings.max_symbols_per_market, total_budget)]
        total_budget -= len(symbols)
        m = MARKETS[market_key]
        yahoo = {s: to_yahoo(s, market_key) for s in symbols}
        try:
            data = provider.history(list(yahoo.values()), settings.lookback_period, settings.timeframe)
        except BudgetExceeded as exc:
            skipped[market_key] = f"بودجه درخواست داده تمام شد: {exc}"
            continue
        except Exception as exc:
            errors.append(f"{market_key}: {type(exc).__name__}: {exc}")
            skipped[market_key] = "دریافت داده ناموفق بود"
            continue

        above50, rets, analysed = 0, [], 0
        for sym in symbols:
            prep = prepare(data.get(yahoo[sym]), market_key, now, min_bars=settings.min_bars,
                           max_stale_sessions=settings.max_stale_sessions, interval=settings.timeframe)
            c = Candidate(sym, yahoo[sym], market_key, m.priority, False)
            if not prep.quality.ok or prep.snap is None:
                c.reason = "؛ ".join(prep.quality.issues) or "داده ناکافی"
                candidates.append(c)
                continue
            snap = prep.snap
            if m.asset_class == "stock":
                min_dv = settings.min_dollar_volume_tsxv if market_key == "tsxv" else settings.min_dollar_volume
                if snap.get("dollar_vol20") is None or snap["dollar_vol20"] < min_dv:
                    c.reason = "نقدشوندگی کمتر از حد تعیین‌شده"
                    candidates.append(c)
                    continue
            ctx = AnalysisContext(sym, display_symbol(sym, market_key), yahoo[sym], m, prep.bars, prep.ind, snap,
                                  prep.levels, prep.quality, now, provider.name)
            tech = technical_analyst.analyze(ctx)
            c.included = True
            c.score = tech.score
            c.direction = 1 if tech.score > 0.1 else -1 if tech.score < -0.1 else 0
            quality_factor = 0.8 if prep.quality.warnings else 1.0
            # Trend strength (distance from SMA50 in ATR units) separates equally agreeing evidence.
            stretch = 0.0
            if snap.get("sma50") and snap.get("atr14"):
                stretch = min(1.0, abs(snap["close"] - snap["sma50"]) / (3 * snap["atr14"]))
            c.interest = round(abs(tech.score) * tech.confidence * quality_factor * (0.8 + 0.2 * stretch)
                               + 0.1 * bool(prep.levels.breakout or prep.levels.failed_breakout), 3)
            c.flags = _flags(snap, prep.levels, prep.quality.has_volume)
            c.metrics = {k: snap.get(k) for k in ("close", "rsi14", "atr_pct", "ret5", "ret20", "vol_z", "date")}
            c.metrics["confidence"] = tech.confidence
            candidates.append(c)
            analysed += 1
            if snap.get("sma50") and snap["close"] > snap["sma50"]:
                above50 += 1
            if snap.get("ret5") is not None:
                rets.append(snap["ret5"])
        breadth[market_key] = {
            "symbols": len(symbols), "analysed": analysed,
            "pct_above_sma50": above50 / analysed if analysed else None,
            "avg_ret5": sum(rets) / len(rets) if rets else None,
        }

    ranked = sorted([c for c in candidates if c.included], key=lambda c: (-c.interest, c.priority))
    for i, c in enumerate(ranked, 1):
        c.rank = i
    return ScanResult(candidates, breadth, errors, skipped)
