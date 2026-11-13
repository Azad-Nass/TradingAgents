"""Bullish and Bearish Researchers: each builds its own case from the
analysts' evidence and answers the other side's strongest points."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .base import AgentOpinion


@dataclass
class DebateCase:
    side: str                 # "bull" | "bear"
    role_fa: str
    strength: float
    points: list[dict] = field(default_factory=list)
    counterpoints: list[dict] = field(default_factory=list)
    verdict_fa: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _weighted(opinions: list[AgentOpinion], stance: int) -> list[tuple[float, str, str]]:
    out = []
    for op in opinions:
        if not op.applicable or op.confidence <= 0:
            continue
        for e in op.evidence:
            if e.stance == stance:
                out.append((e.weight * op.confidence, e.text_fa, op.role_fa))
    return sorted(out, key=lambda t: t[0], reverse=True)


def build_case(side: str, opinions: list[AgentOpinion]) -> DebateCase:
    stance = 1 if side == "bull" else -1
    role = "پژوهشگر صعودی" if side == "bull" else "پژوهشگر نزولی"
    own, other = _weighted(opinions, stance), _weighted(opinions, -stance)
    strength, against = sum(w for w, _, _ in own), sum(w for w, _, _ in other)
    case = DebateCase(side, role, round(strength, 3))
    case.points = [{"text_fa": t, "agent": a, "weight": round(w, 3)} for w, t, a in own[:6]]
    for w, text, agent in other[:3]:
        if strength > against:
            reply = "این شاهد پذیرفته می‌شود، اما وزن مجموع شواهد مقابل آن بیشتر است"
        elif strength == 0:
            reply = "پاسخی مبتنی بر شواهد برای این نکته وجود ندارد"
        else:
            reply = "این نکته معتبر است و موضع این پژوهشگر را تضعیف می‌کند"
        case.counterpoints.append({"text_fa": text, "agent": agent, "weight": round(w, 3), "response_fa": reply})
    total = strength + against
    share = strength / total if total else 0.0
    case.verdict_fa = (f"{role}: {len(own)} شاهد موافق، سهم وزن شواهد {share:.0%}"
                       if own else f"{role}: شاهد موافقی یافت نشد")
    return case
