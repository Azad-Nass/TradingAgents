"""Shared types of the agents.

Agents here are deterministic, evidence-based modules: each reads the
analysis context, cites the values it used (with their source and date),
states its uncertainty and returns a structured opinion. An optional LLM may
later phrase the result in Persian, but never changes a number or a decision.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from ..analysis.levels import Levels
from ..core.markets import Market
from ..core.quality import DataQuality


@dataclass
class Evidence:
    text_fa: str
    stance: int = 0                 # +1 bullish, -1 bearish, 0 neutral/context
    weight: float = 1.0
    value: Any = None
    source: str = ""
    as_of: str | None = None


@dataclass
class AgentOpinion:
    agent: str
    role_fa: str
    applicable: bool
    score: float                    # -1 (bearish) .. +1 (bullish)
    confidence: float               # 0 .. 1
    evidence: list[Evidence] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    note_fa: str = ""

    @property
    def stance(self) -> str:
        if not self.applicable:
            return "n/a"
        return "bullish" if self.score > 0.1 else "bearish" if self.score < -0.1 else "neutral"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["stance"] = self.stance
        return d


def not_applicable(agent: str, role_fa: str, reason_fa: str) -> AgentOpinion:
    return AgentOpinion(agent, role_fa, False, 0.0, 0.0, [], [], reason_fa)


def score_from(evidence: list[Evidence]) -> tuple[float, float]:
    """Weighted score in [-1, 1] and the agreement among directional evidence."""
    directional = [e for e in evidence if e.stance]
    if not directional:
        return 0.0, 0.0
    total = sum(e.weight for e in directional)
    net = sum(e.weight * e.stance for e in directional)
    score = max(-1.0, min(1.0, net / total)) if total else 0.0
    agreement = abs(net) / total if total else 0.0
    return score, agreement


@dataclass
class AnalysisContext:
    symbol: str                     # as the user wrote it
    display: str                    # EUR/USD, AAPL, ...
    yahoo: str
    market: Market
    bars: pd.DataFrame              # completed bars only
    ind: pd.DataFrame               # bars + indicator columns
    snap: dict
    levels: Levels
    quality: DataQuality
    now: datetime
    data_source: str
    fundamentals: dict | None = None
    news: list[dict] = field(default_factory=list)
    macro: dict | None = None
    benchmark: pd.DataFrame | None = None
    peers: dict[str, pd.DataFrame] = field(default_factory=dict)
    open_signals: list[dict] = field(default_factory=list)
    tradingagents: dict | None = None
    news_sentiment_method: str = "none"
