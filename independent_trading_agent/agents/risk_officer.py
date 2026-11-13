"""Risk Manager / Chief Risk Officer: vetoes, cautions and hypothetical size."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from zoneinfo import ZoneInfo

import pandas as pd

from ..risk_management.sizing import FxRate, size_position
from .base import AnalysisContext
from .trader import TradePlan

NAME, ROLE = "risk_officer", "مدیر ارشد ریسک"


@dataclass
class RiskAssessment:
    approved: bool
    vetoes: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    size_factor: float = 1.0
    sizing: dict | None = None
    correlations: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _corr(a: pd.DataFrame, b: pd.DataFrame, n: int = 60) -> float | None:
    joined = pd.concat([a["close"].pct_change(), b["close"].pct_change()], axis=1, join="inner").dropna().tail(n)
    if len(joined) < 30:
        return None
    return float(joined.corr().iloc[0, 1])


def assess(ctx: AnalysisContext, plan: TradePlan | None, settings, fx: FxRate) -> RiskAssessment:
    ra = RiskAssessment(True)
    if not ctx.quality.ok:
        ra.vetoes.extend(ctx.quality.issues)
    if plan is None:
        ra.vetoes.append("برنامه معامله قابل ساخت نیست (ATR یا جهت نامعتبر)")
        ra.approved = False
        return ra

    if plan.effective_reward_risk < settings.min_reward_risk:
        ra.vetoes.append(f"نسبت ریسک به بازده تا سطح مخالف {plan.effective_reward_risk:.2f} کمتر از حداقل "
                         f"{settings.min_reward_risk} است")
    s = ctx.snap
    med = s.get("atr_pct_median_1y")
    if s.get("atr_pct") and med and s["atr_pct"] > 2.5 * med:
        ra.vetoes.append("نوسان بیش از ۲٫۵ برابر میانه یک‌ساله است")
    elif s.get("atr_pct") and med and s["atr_pct"] > 1.8 * med:
        ra.cautions.append("نوسان بالا؛ حجم نصف شد")
        ra.size_factor *= 0.5

    if ctx.market.asset_class == "stock":
        min_dv = settings.min_dollar_volume_tsxv if ctx.market.key == "tsxv" else settings.min_dollar_volume
        dv = s.get("dollar_vol20")
        if dv is None:
            ra.cautions.append("نقدشوندگی قابل سنجش نیست")
        elif dv < min_dv:
            ra.vetoes.append(f"نقدشوندگی ناکافی ({dv / 1e6:,.2f} میلیون در روز)")
        f = ctx.fundamentals or {}
        if f.get("nextEarningsDate"):
            try:
                days = (date.fromisoformat(str(f["nextEarningsDate"])[:10]) - ctx.now.date()).days
                if 0 <= days <= plan.horizon_bars * 1.5:
                    ra.cautions.append(f"گزارش درآمد {days} روز دیگر؛ حجم نصف شد")
                    ra.size_factor *= 0.5
            except ValueError:
                pass
    ny = ctx.now.astimezone(ZoneInfo("America/New_York"))
    if ctx.market.key == "forex" and ny.weekday() == 4 and ny.hour >= 12:
        ra.cautions.append("نزدیک بسته‌شدن هفتگی فارکس (جمعه، نیویورک): ریسک شکاف قیمت آخر هفته")

    open_signals = [o for o in ctx.open_signals if o.get("symbol") != ctx.symbol]
    if len(open_signals) >= settings.max_open_signals:
        ra.vetoes.append(f"سقف {settings.max_open_signals} سیگنال باز فرضی پر است")
    for o in open_signals:
        other = ctx.peers.get(o.get("yahoo") or "")
        if other is None:
            continue
        c = _corr(ctx.bars, other)
        if c is None:
            continue
        same_way = c * plan.direction * (o.get("direction") or 0)
        ra.correlations.append({"symbol": o["symbol"], "corr": round(c, 2), "effective": round(same_way, 2)})
        if same_way > 0.8:
            ra.cautions.append(f"همبستگی بالا با سیگنال باز {o['symbol']} ({c:+.2f}) در همان جهت مؤثر؛ حجم نصف شد")
            ra.size_factor *= 0.5

    sizing = size_position(symbol=ctx.symbol, asset_class=ctx.market.asset_class, quote_ccy=ctx.market.currency,
                           entry=plan.reference_price, stop=plan.stop, portfolio_value=settings.portfolio_value,
                           risk_pct=settings.risk_per_trade_pct, account_ccy=settings.account_currency, fx=fx,
                           size_factor=ra.size_factor)
    ra.sizing = sizing.to_dict()
    if not sizing.ok:
        ra.cautions.extend(sizing.notes)
    elif sizing.leverage > 10:
        ra.cautions.append(f"اهرم اسمی {sizing.leverage:.1f} برابر است")
    ra.approved = not ra.vetoes
    return ra
