"""Test fixtures. All market data here is SYNTHETIC (seeded random walks) and
labelled as such; no test touches the network or a real API key."""
from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from independent_trading_agent.config.settings import Settings
from independent_trading_agent.core.data_provider import RequestBudget

NOW = datetime(2026, 11, 12, 23, 0, tzinfo=UTC)  # Thursday, 18:00 New York
SYNTHETIC = "SYNTHETIC TEST DATA (not market data)"


def synthetic_bars(end="2026-11-12", n=320, start_price=100.0, drift=0.0, vol=0.01, seed=1, volume=True,
                   freq="B") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(end=end, periods=n, freq=freq)
    rets = rng.normal(drift, vol, n)
    close = start_price * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[start_price], close[:-1]]) * (1 + rng.normal(0, vol / 4, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol / 2, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol / 2, n)))
    vol_col = rng.integers(2_000_000, 4_000_000, n).astype(float) if volume else np.zeros(n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol_col}, index=idx)


class FakeProvider:
    """Serves preset synthetic frames; counts requests like the real provider."""

    name = SYNTHETIC

    def __init__(self, frames: dict[str, pd.DataFrame] | None = None, news: list[dict] | None = None,
                 fundamentals: dict | None = None, budget: int = 100, fail: set[str] | None = None):
        self.frames = frames or {}
        self._news = news or []
        self._fund = fundamentals or {}
        self.budget = RequestBudget(budget)
        self.fail = fail or set()
        self.history_calls: list[list[str]] = []

    def history(self, symbols, period="2y", interval="1d"):
        self.budget.spend("history")
        self.history_calls.append(list(symbols))
        if self.fail & set(symbols):
            raise ConnectionError("synthetic network failure")
        out = {}
        for i, s in enumerate(symbols):
            if s in self.frames:
                out[s] = self.frames[s]
            elif s.endswith("=X"):
                out[s] = synthetic_bars(start_price=1.1, vol=0.004, seed=100 + i, volume=False, freq="B")
            else:
                out[s] = synthetic_bars(seed=200 + i)
        return out

    def news(self, query, limit=10):
        self.budget.spend("news")
        return list(self._news)

    def fundamentals(self, symbol):
        self.budget.spend("fundamentals")
        return dict(self._fund)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No test reaches a real service: TradingAgents, FRED and LLM keys are cut off for every test."""
    import os

    from independent_trading_agent.integrations import fred, tradingagents_adapter

    for key in [k for k in os.environ if k.startswith("INDEPENDENT_AGENT_") and k.endswith("_API_KEY")]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(tradingagents_adapter, "run_deep_analysis",
                        lambda *a, **k: {"ok": False, "error": "offline test: TradingAgents not called"})
    monkeypatch.setattr(fred, "forex_macro", lambda *a, **k: {"available": False, "reason_fa": "offline test"})
    monkeypatch.setattr(fred, "gold_macro", lambda *a, **k: {"available": False, "reason_fa": "offline test"})


@pytest.fixture
def settings(tmp_path) -> Settings:
    s = Settings()
    s.data_dir = str(tmp_path / "data")
    s.reports_dir = str(tmp_path / "reports")
    s.logs_dir = str(tmp_path / "logs")
    s.pdf_enabled = False
    s.llm_enabled = False
    s.request_delay_seconds = 0
    return s


@pytest.fixture
def now() -> datetime:
    return NOW
