"""Settings of the independent app.

Layers, later wins: built-in defaults -> ``config/settings.toml`` (optional)
-> ``INDEPENDENT_AGENT_*`` environment variables, which may come from
``independent_trading_agent/.env``. Only variables with that prefix are read,
so this app never picks up or changes TradingAgents' settings.

Secrets (API keys) are never stored on :class:`Settings`; read them with
:func:`secret` at the moment they are needed.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent
ENV_PREFIX = "INDEPENDENT_AGENT_"
ENV_FILE = PACKAGE_DIR / ".env"
TOML_FILE = PACKAGE_DIR / "config" / "settings.toml"

MARKET_KEYS = ("forex", "nasdaq", "nyse", "crypto", "tsx", "tsxv")

DEFAULT_UNIVERSE: dict[str, list[str]] = {
    "forex": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "XAUUSD"],
    "nasdaq": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "TSLA", "AMD", "NFLX",
               "COST", "ADBE", "QQQ"],
    "nyse": ["JPM", "V", "XOM", "JNJ", "WMT", "PG", "KO", "BAC", "DIS", "SPY"],
    "crypto": ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "BNB-USD"],
    "tsx": ["RY.TO", "TD.TO", "SHOP.TO", "ENB.TO", "CNR.TO", "BNS.TO", "XIU.TO"],
    # Empty on purpose: TSXV names are thin and change often; the user adds them.
    "tsxv": [],
}


@dataclass
class Settings:
    markets: list[str] = field(default_factory=lambda: ["forex", "nasdaq", "nyse", "crypto", "tsx"])
    universe: dict[str, list[str]] = field(default_factory=lambda: {k: list(v) for k, v in DEFAULT_UNIVERSE.items()})
    watchlist: list[str] = field(default_factory=list)

    max_symbols_per_market: int = 15
    max_total_symbols: int = 60
    top_n: int = 5
    deep_top_k: int = 3            # scan picks sent to TradingAgents (after the watchlist)
    min_interest: float = 0.30
    max_data_requests: int = 40
    request_delay_seconds: float = 0.5

    timeframe: str = "1d"
    lookback_period: str = "2y"
    horizon_bars: int = 10
    min_bars: int = 200
    max_stale_sessions: int = 3
    report_timezone: str = "America/Toronto"
    run_time: str = "18:30"

    account_currency: str = "USD"
    portfolio_value: float = 100_000.0
    risk_per_trade_pct: float = 1.0
    min_reward_risk: float = 1.5
    max_open_signals: int = 10
    min_dollar_volume: float = 5_000_000.0
    min_dollar_volume_tsxv: float = 200_000.0
    forex_spread_pips: float = 1.0
    metal_spread_pips: float = 3.0     # XAU/USD pip = 0.1, so 3 pips = $0.30
    stock_spread_bps: float = 5.0
    crypto_spread_bps: float = 10.0
    commission_bps: float = 2.0
    slippage_bps: float = 3.0

    llm_enabled: bool = False
    llm_chain: str = ("gemini:gemini-3.5-flash-lite,gemini:gemini-3.5-flash,"
                      "openrouter:nvidia/nemotron-3-ultra-550b-a55b:free")
    max_llm_calls: int = 10        # Gemini sentiment calls per run (one per analysed symbol)
    llm_timeout_seconds: float = 30.0

    # TradingAgents is the analysis engine. Each run of it makes dozens of LLM calls, so runs are capped.
    tradingagents_enabled: bool = True
    tradingagents_max_runs: int = 4
    tradingagents_analysts: str = "market,news"                    # forex, gold, crypto
    tradingagents_analysts_stock: str = "market,news,fundamentals"  # stocks (SEC EDGAR statements)
    tradingagents_language: str = "Persian"
    tradingagents_timeout_seconds: int = 900

    pdf_enabled: bool = True
    dashboard_port: int = 8765

    data_dir: str = str(PACKAGE_DIR / "data")
    reports_dir: str = str(PACKAGE_DIR / "reports")
    logs_dir: str = str(PACKAGE_DIR / "logs")

    @property
    def db_path(self) -> Path:
        return Path(self.data_dir) / "independent_agent.db"

    @property
    def lock_path(self) -> Path:
        return Path(self.data_dir) / "independent_agent.lock"

    def enabled_markets(self) -> list[str]:
        """Enabled markets in the fixed priority order."""
        return [m for m in MARKET_KEYS if m in self.markets]

    def public_dict(self) -> dict:
        """Everything recorded with a run. Holds no secrets by construction."""
        return asdict(self)


def _parse_env_file(path: Path) -> dict[str, str]:
    """``KEY=value`` lines of a .env file, prefix-filtered. Comments and blanks skipped."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        if key.startswith(ENV_PREFIX):
            values[key] = value
    return values


def load_env_file(path: Path = ENV_FILE) -> None:
    """Put the app's .env values into ``os.environ`` without overriding real env vars."""
    for key, value in _parse_env_file(path).items():
        os.environ.setdefault(key, value)


def secret(name: str) -> str | None:
    """An ``INDEPENDENT_AGENT_<name>`` secret, or None when unset or blank."""
    value = os.environ.get(ENV_PREFIX + name, "").strip()
    return value or None


def _coerce(value: str, reference):
    if isinstance(reference, bool):
        low = value.strip().lower()
        if low in ("1", "true", "yes", "on"):
            return True
        if low in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"expected a boolean, got {value!r}")
    if isinstance(reference, int):
        return int(value)
    if isinstance(reference, float):
        return float(value)
    if isinstance(reference, list):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


def load_settings(*, env_file: Path | None = ENV_FILE, toml_file: Path | None = TOML_FILE,
                  environ: dict[str, str] | None = None) -> Settings:
    """Defaults, then settings.toml, then INDEPENDENT_AGENT_* variables."""
    if env_file is not None:
        load_env_file(env_file)
    env = os.environ if environ is None else environ
    settings = Settings()
    names = {f.name for f in fields(Settings)}

    if toml_file is not None and toml_file.is_file():
        data = tomllib.loads(toml_file.read_text(encoding="utf-8"))
        universe = data.pop("universe", None)
        for key, value in data.items():
            if key not in names:
                raise ValueError(f"settings.toml: unknown setting {key!r}")
            setattr(settings, key, value)
        if universe:
            for market, symbols in universe.items():
                settings.universe[market] = list(symbols)

    for name in names - {"universe"}:
        raw = env.get(ENV_PREFIX + name.upper())
        if raw is None or raw == "":
            continue
        try:
            setattr(settings, name, _coerce(raw, getattr(settings, name)))
        except ValueError as exc:
            raise ValueError(f"Invalid {ENV_PREFIX}{name.upper()}: {exc}") from exc
    for market in MARKET_KEYS:
        raw = env.get(f"{ENV_PREFIX}UNIVERSE_{market.upper()}")
        if raw is not None:
            settings.universe[market] = [s.strip() for s in raw.split(",") if s.strip()]

    unknown = [m for m in settings.markets if m not in MARKET_KEYS]
    if unknown:
        raise ValueError(f"Unknown market(s) {unknown}; choose from {list(MARKET_KEYS)}")
    if not 0 < settings.risk_per_trade_pct <= 5:
        raise ValueError("risk_per_trade_pct must be in (0, 5]")
    return settings
