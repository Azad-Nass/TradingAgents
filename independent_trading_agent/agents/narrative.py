"""Persian narrative of a decided analysis: a fixed template, optionally
re-phrased by an LLM that is given only these facts."""
from __future__ import annotations

from .base import AgentOpinion
from .chief import Decision


def facts(display: str, decision: Decision, opinions: list[AgentOpinion], plan: dict | None,
          risk: dict | None) -> dict:
    """The only material an LLM may use to phrase the summary."""
    return {
        "symbol": display,
        "decision": decision.label, "decision_fa": decision.label_fa,
        "combined_score": decision.score, "conflict": decision.conflict, "confidence": decision.confidence,
        "reasons": decision.reasons_fa,
        "agents": [{"role": o.role_fa, "stance": o.stance, "note": o.note_fa,
                    "key_evidence": [e.text_fa for e in o.evidence if e.stance][:3]}
                   for o in opinions if o.applicable],
        "plan": {k: plan[k] for k in ("entry_low", "entry_high", "stop", "targets", "effective_reward_risk",
                                      "horizon_bars")} if plan else None,
        "risk_vetoes": (risk or {}).get("vetoes"), "risk_cautions": (risk or {}).get("cautions"),
    }


def template(display: str, decision: Decision, opinions: list[AgentOpinion], plan: dict | None,
             risk: dict | None) -> str:
    parts = [f"نتیجه برای {display}: «{decision.label_fa}» ({decision.label})، امتیاز ترکیبی {decision.score:+.2f} "
             f"و اطمینان {decision.confidence:.0%}{'' if decision.confidence_calibrated else ' (کالیبره‌نشده)'}."]
    parts.extend(decision.reasons_fa)
    if decision.agreeing:
        parts.append("هم‌جهت با نتیجه: " + "، ".join(decision.agreeing) + ".")
    if decision.disagreeing:
        parts.append("مخالف: " + "، ".join(decision.disagreeing) + ".")
    if plan and decision.direction:
        parts.append(f"سناریوی فرضی: ورود {plan['entry_low']:,.5g}–{plan['entry_high']:,.5g}، حد ضرر {plan['stop']:,.5g}، "
                     f"اهداف {' / '.join(format(t, ',.5g') for t in plan['targets'])}.")
    if risk and risk.get("cautions"):
        parts.append("هشدارهای ریسک: " + "؛ ".join(risk["cautions"]) + ".")
    parts.append("این تحلیل توصیه سرمایه‌گذاری یا تضمین سود نیست.")
    return " ".join(parts)
