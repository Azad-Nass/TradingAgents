"""Chief Intelligence Agent: weighs the opinions, the debate and the risk
review into one label, and explains agreement, disagreement and risk.

The label is evidence-based, not an average: a data-quality failure, a
serious conflict between agents or a risk veto all end in NO TRADE.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .base import AgentOpinion
from .researchers import DebateCase
from .risk_officer import RiskAssessment

WEIGHTS = {
    "technical_analyst": 0.45,
    "macro_analyst": 0.15,
    "sentiment_analyst": 0.08,
    "forex_analyst": 0.12,
    "stock_market_analyst": 0.12,
    "crypto_analyst": 0.12,
    "tradingagents_llm": 0.15,
}
LABELS = ("STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL", "NO TRADE")
LABEL_FA = {"STRONG BUY": "خرید قوی", "BUY": "خرید", "HOLD": "نگه‌داری / بدون موقعیت جدید",
            "SELL": "فروش", "STRONG SELL": "فروش قوی", "NO TRADE": "عدم معامله"}
HOLD_BAND = 0.15
CONFLICT_LIMIT = 0.45


@dataclass
class Decision:
    label: str
    direction: int
    score: float
    conflict: float
    confidence: float
    confidence_calibrated: bool
    reasons_fa: list[str] = field(default_factory=list)
    agreeing: list[str] = field(default_factory=list)
    disagreeing: list[str] = field(default_factory=list)

    @property
    def label_fa(self) -> str:
        return LABEL_FA[self.label]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["label_fa"] = self.label_fa
        return d


def combine(opinions: list[AgentOpinion]) -> tuple[float, float]:
    """Reliability-weighted score and the share of weight that points the other way."""
    used = [(WEIGHTS.get(o.agent, 0.05) * o.confidence, o.score) for o in opinions
            if o.applicable and o.confidence > 0 and o.agent != "news_analyst"]
    total = sum(w for w, _ in used)
    if not total:
        return 0.0, 0.0
    score = sum(w * s for w, s in used) / total
    sign = 1 if score > 0 else -1
    against = sum(w for w, s in used if s * sign < -0.1)
    return score, against / total


def decide(opinions: list[AgentOpinion], bull: DebateCase, bear: DebateCase, quality_ok: bool,
           risk: RiskAssessment | None, calibrate=None) -> Decision:
    """``risk`` is the review of a plan in the direction of the combined score."""
    score, conflict = combine(opinions)
    direction = 1 if score > 0 else -1 if score < 0 else 0
    tech = next((o for o in opinions if o.agent == "technical_analyst"), None)
    reasons: list[str] = []
    agreeing = [o.role_fa for o in opinions if o.applicable and o.confidence > 0 and o.score * direction > 0.1]
    disagreeing = [o.role_fa for o in opinions if o.applicable and o.confidence > 0 and o.score * direction < -0.1]

    raw_conf = max(0.05, min(0.95, 0.25 + 0.5 * abs(score) + 0.2 * (1 - conflict)))
    if tech:
        raw_conf *= 0.6 + 0.4 * tech.confidence
    conf, calibrated = (calibrate(raw_conf) if calibrate else (raw_conf, False))

    def out(label, why):
        reasons.extend(why)
        return Decision(label, direction if label not in ("HOLD", "NO TRADE") else 0, round(score, 3),
                        round(conflict, 3), round(conf, 2), calibrated, reasons, agreeing, disagreeing)

    if not quality_ok:
        return out("NO TRADE", ["کیفیت یا تازگی داده برای تصمیم کافی نیست"])
    if abs(score) < HOLD_BAND:
        return out("HOLD", [f"امتیاز ترکیبی {score:+.2f} در محدوده خنثی (±{HOLD_BAND}) است؛ برتری روشنی وجود ندارد"])
    if conflict >= CONFLICT_LIMIT:
        return out("NO TRADE", [f"تعارض جدی میان عامل‌ها: {conflict:.0%} از وزن شواهد خلاف جهت غالب است"])
    if risk is None or not risk.approved:
        vetoes = risk.vetoes if risk else ["بررسی ریسک انجام نشد"]
        return out("NO TRADE", ["مدیر ریسک سناریو را رد کرد: " + "؛ ".join(vetoes)])

    lead, lag = (bull, bear) if direction > 0 else (bear, bull)
    reasons.append(f"امتیاز ترکیبی {score:+.2f}؛ {lead.role_fa} با قدرت {lead.strength:.2f} در برابر "
                   f"{lag.strength:.2f}")
    if conflict > 0.2:
        reasons.append(f"اختلاف‌نظر قابل توجه ({conflict:.0%} از وزن شواهد مخالف)")
    strong = abs(score) >= 0.5 and conflict < 0.2 and tech is not None and tech.confidence >= 0.6 \
        and risk.size_factor >= 1.0
    if direction > 0:
        return out("STRONG BUY" if strong else "BUY", [])
    return out("STRONG SELL" if strong else "SELL", [])


TA_LABEL = {"Buy": "STRONG BUY", "Overweight": "BUY", "Hold": "HOLD", "Underweight": "SELL", "Sell": "STRONG SELL"}
TA_DIRECTION = {"Buy": 1, "Overweight": 1, "Hold": 0, "Underweight": -1, "Sell": -1}
OPPOSE_LIMIT = 0.3


def decide_tradingagents(ta_result: dict | None, supplements: list[AgentOpinion], quality_ok: bool,
                         risk: RiskAssessment | None, calibrate=None) -> Decision:
    """The decision when TradingAgents is the analysis engine.

    TradingAgents' rating sets the direction and strength. Data quality and
    the risk officer can only stop a trade (NO TRADE). FRED macro and the
    sentiment reading can only weaken it: a strong opposing view turns
    STRONG BUY/SELL into BUY/SELL and is reported as a disagreement.
    """
    ok = bool(ta_result and ta_result.get("ok"))
    rating = (ta_result or {}).get("rating") if ok else None
    direction = TA_DIRECTION.get(rating, 0)
    used = [o for o in supplements if o.applicable and o.confidence > 0]
    agreeing = [o.role_fa for o in used if direction and o.score * direction > 0.1]
    disagreeing = [o.role_fa for o in used if direction and o.score * direction < -0.1]
    opposing = [o for o in used if direction and o.score * direction <= -OPPOSE_LIMIT]
    base_conf = {"Buy": 0.65, "Sell": 0.65, "Overweight": 0.55, "Underweight": 0.55, "Hold": 0.5}.get(rating, 0.0)
    raw = max(0.05, base_conf - 0.1 * len(opposing) + 0.05 * len(agreeing))
    conf, calibrated = (calibrate(raw) if calibrate else (raw, False))
    score = {"Buy": 0.8, "Overweight": 0.4, "Hold": 0.0, "Underweight": -0.4, "Sell": -0.8}.get(rating, 0.0)
    total = sum(1 for _ in used) or 1
    conflict = round(len(disagreeing) / (total + 1), 3)

    def out(label, reasons, d=0):
        return Decision(label, d, score, conflict, round(conf, 2), calibrated, reasons, agreeing, disagreeing)

    if not quality_ok:
        return out("NO TRADE", ["کیفیت یا تازگی داده قیمت برای تصمیم کافی نیست"])
    if not ok:
        err = str((ta_result or {}).get("error") or "اجرا نشد")[:200]
        return out("NO TRADE", [f"تحلیل TradingAgents انجام نشد: {err}"])
    if rating not in TA_LABEL:
        return out("NO TRADE", [f"رتبه نهایی TradingAgents قابل خواندن نبود ({rating})"])
    if direction == 0:
        return out("HOLD", ["رتبه نهایی TradingAgents «Hold» است؛ موقعیت جدیدی پیشنهاد نمی‌شود"])
    if risk is None or not risk.approved:
        vetoes = risk.vetoes if risk else ["بررسی ریسک انجام نشد"]
        return out("NO TRADE", [f"TradingAgents: {rating}؛ اما مدیر ریسک سناریو را رد کرد: " + "؛ ".join(vetoes)])
    label = TA_LABEL[rating]
    reasons = [f"رتبه نهایی TradingAgents: {rating}"]
    if opposing and label.startswith("STRONG"):
        label = label.replace("STRONG ", "")
        reasons.append("به‌دلیل مخالفت " + "، ".join(o.role_fa for o in opposing) + " یک درجه تضعیف شد")
    elif opposing:
        reasons.append("مخالفت " + "، ".join(o.role_fa for o in opposing) + " ثبت شد")
    if risk.size_factor < 1:
        reasons.append(f"مدیر ریسک حجم را به {risk.size_factor:.0%} کاهش داد")
    return out(label, reasons, direction)
