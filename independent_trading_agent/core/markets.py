"""Markets: priority, trading calendars, sessions and symbol mapping.

Calendars are rule-based (fixed and floating holidays with weekend
observance). They cover the regular full-day closures of NYSE/NASDAQ and the
TSX; ad-hoc closures (a national day of mourning, a storm) are not known in
advance, so the data-staleness check in :mod:`core.quality` is the backstop.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

UTC = UTC


@dataclass(frozen=True)
class Market:
    key: str
    name: str
    name_fa: str
    priority: int          # 1 = highest
    asset_class: str       # forex | stock | crypto | other
    timezone: str
    open_time: time
    close_time: time
    currency: str
    benchmark: str | None  # Yahoo symbol for relative strength


MARKETS: dict[str, Market] = {
    "forex": Market("forex", "Forex", "فارکس", 1, "forex", "America/New_York", time(17, 0), time(17, 0), "USD", None),
    "nasdaq": Market("nasdaq", "NASDAQ", "نزدک", 2, "stock", "America/New_York", time(9, 30), time(16, 0), "USD", "QQQ"),
    "nyse": Market("nyse", "NYSE", "بورس نیویورک", 3, "stock", "America/New_York", time(9, 30), time(16, 0), "USD", "SPY"),
    "crypto": Market("crypto", "Cryptocurrency", "رمزارز", 4, "crypto", "UTC", time(0, 0), time(23, 59), "USD", "BTC-USD"),
    "tsx": Market("tsx", "TSX", "بورس تورنتو", 5, "stock", "America/Toronto", time(9, 30), time(16, 0), "CAD", "XIU.TO"),
    "tsxv": Market("tsxv", "TSXV", "بورس ونچر تورنتو", 6, "stock", "America/Toronto", time(9, 30), time(16, 0), "CAD", "XIU.TO"),
    # Anything else the user asks about (futures such as GC=F, indices).
    "other": Market("other", "Other", "سایر", 9, "other", "America/New_York", time(18, 0), time(17, 0), "USD", None),
}

PRIORITY_ORDER = [m.key for m in sorted(MARKETS.values(), key=lambda m: m.priority) if m.key != "other"]

CURRENCIES = {"USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD", "SEK", "NOK", "DKK", "SGD",
              "HKD", "MXN", "ZAR", "TRY", "CNH", "CNY", "PLN", "HUF", "CZK", "INR", "KRW"}

FOREX_SESSIONS = {
    # name: (tz, open, close) in local exchange-centre time
    "asia": ("Asia/Tokyo", time(9, 0), time(18, 0)),
    "london": ("Europe/London", time(8, 0), time(17, 0)),
    "new_york": ("America/New_York", time(8, 0), time(17, 0)),
}
SESSION_NAMES_FA = {"asia": "آسیا (توکیو)", "london": "لندن", "new_york": "نیویورک"}


# ---------------------------------------------------------------- symbols ---

# Spot metals as forex brokers quote them (XAU/USD, XAG/USD). Yahoo has no spot pair for them, so the
# data comes from the COMEX front-month future, whose price differs from spot by the futures basis.
# key: (Yahoo futures proxy, ounces per standard lot, pip size)
METALS = {"XAU": ("GC=F", 100, 0.1), "XAG": ("SI=F", 5000, 0.01)}


def forex_pair(symbol: str) -> tuple[str, str] | None:
    """(base, quote) of a forex or spot-metal symbol in any common spelling, else None."""
    s = symbol.upper().replace("/", "").replace("=X", "").replace("-", "").strip()
    if len(s) == 6 and s[3:] in CURRENCIES and (s[:3] in CURRENCIES or s[:3] in METALS):
        return s[:3], s[3:]
    return None


def is_metal(symbol: str) -> bool:
    pair = forex_pair(symbol)
    return bool(pair and pair[0] in METALS)


def contract_size(symbol: str) -> int:
    """Units of the base per standard lot: 100,000 for currencies, ounces for metals."""
    pair = forex_pair(symbol)
    return METALS[pair[0]][1] if pair and pair[0] in METALS else 100_000


def infer_market(symbol: str) -> str:
    s = symbol.upper().strip()
    if forex_pair(s) and not s.endswith("-USD"):
        return "forex"
    if re.fullmatch(r"[A-Z0-9]{2,10}-(USD|USDT|EUR|CAD)", s):
        return "crypto"
    if s.endswith(".TO"):
        return "tsx"
    if s.endswith(".V"):
        return "tsxv"
    if "=" in s or s.startswith("^"):
        return "other"
    return "nasdaq"


def to_yahoo(symbol: str, market: str | None = None) -> str:
    """The Yahoo Finance ticker for ``symbol`` in ``market``."""
    market = market or infer_market(symbol)
    s = symbol.upper().strip()
    if market == "forex":
        pair = forex_pair(s)
        if pair and pair[0] in METALS:
            return METALS[pair[0]][0] if pair[1] == "USD" else s  # only USD-quoted metals have a proxy
        return f"{pair[0]}{pair[1]}=X" if pair else s
    if market == "crypto" and "-" not in s:
        return f"{s}-USD"
    if market == "tsx" and not s.endswith(".TO"):
        return f"{s}.TO"
    if market == "tsxv" and not s.endswith(".V"):
        return f"{s}.V"
    return s


def display_symbol(symbol: str, market: str | None = None) -> str:
    market = market or infer_market(symbol)
    if market == "forex":
        pair = forex_pair(symbol)
        if pair:
            return f"{pair[0]}/{pair[1]}"
    return symbol.upper()


def pip_size(symbol: str) -> float:
    pair = forex_pair(symbol)
    if pair and pair[0] in METALS:
        return METALS[pair[0]][2]
    return 0.01 if pair and "JPY" in pair else 0.0001


# -------------------------------------------------------------- calendars ---

def _easter(year: int) -> date:
    """Gregorian Easter Sunday (anonymous algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = ((h + l_ - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th (1-based) weekday (Mon=0) of a month; n=-1 is the last."""
    if n > 0:
        first = date(year, month, 1)
        return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    last = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1))
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed_us(d: date) -> date:
    """NYSE rule: Saturday holidays close Friday, Sunday holidays close Monday."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def _observed_ca(d: date) -> date:
    """TSX rule: weekend holidays move to the following Monday."""
    if d.weekday() == 5:
        return d + timedelta(days=2)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=64)
def us_holidays(year: int) -> frozenset[date]:
    days = {
        _nth_weekday(year, 1, 0, 3),            # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),            # Washington's Birthday
        _easter(year) - timedelta(days=2),      # Good Friday
        _nth_weekday(year, 5, 0, -1),           # Memorial Day
        _observed_us(date(year, 7, 4)),         # Independence Day
        _nth_weekday(year, 9, 0, 1),            # Labor Day
        _nth_weekday(year, 11, 3, 4),           # Thanksgiving
        _observed_us(date(year, 12, 25)),       # Christmas
    }
    if year >= 2022:
        days.add(_observed_us(date(year, 6, 19)))  # Juneteenth
    new_year = date(year, 1, 1)
    if new_year.weekday() != 5:                 # a Saturday New Year is not observed on Dec 31
        days.add(_observed_us(new_year))
    return frozenset(days)


@lru_cache(maxsize=64)
def tsx_holidays(year: int) -> frozenset[date]:
    may24 = date(year, 5, 24)
    victoria = may24 - timedelta(days=may24.weekday())  # last Monday before May 25
    christmas, boxing = date(year, 12, 25), date(year, 12, 26)
    if christmas.weekday() == 5:      # Sat/Sun -> Mon/Tue
        christmas_obs, boxing_obs = christmas + timedelta(days=2), boxing + timedelta(days=2)
    elif christmas.weekday() == 6:    # Sun/Mon -> Tue (Mon is Boxing Day)
        christmas_obs, boxing_obs = christmas + timedelta(days=2), boxing
    elif christmas.weekday() == 4:    # Fri/Sat -> Fri/Mon
        christmas_obs, boxing_obs = christmas, boxing + timedelta(days=2)
    else:
        christmas_obs, boxing_obs = christmas, boxing
    return frozenset({
        _observed_ca(date(year, 1, 1)),
        _nth_weekday(year, 2, 0, 3),            # Family Day
        _easter(year) - timedelta(days=2),      # Good Friday
        victoria,                                # Victoria Day
        _observed_ca(date(year, 7, 1)),          # Canada Day
        _nth_weekday(year, 8, 0, 1),            # Civic Holiday
        _nth_weekday(year, 9, 0, 1),            # Labour Day
        _nth_weekday(year, 10, 0, 2),           # Thanksgiving
        christmas_obs, boxing_obs,
    })


def is_trading_day(market: str, d: date) -> bool:
    if market == "crypto":
        return True
    if d.weekday() >= 5:
        return False
    if market == "forex":
        return not (d.month == 12 and d.day == 25) and not (d.month == 1 and d.day == 1)
    if market in ("tsx", "tsxv"):
        return d not in tsx_holidays(d.year)
    return d not in us_holidays(d.year)


def previous_trading_day(market: str, d: date) -> date:
    d -= timedelta(days=1)
    while not is_trading_day(market, d):
        d -= timedelta(days=1)
    return d


def trading_days_between(market: str, start: date, end: date) -> int:
    """Trading days in (start, end]."""
    count, d = 0, start
    while d < end:
        d += timedelta(days=1)
        if is_trading_day(market, d):
            count += 1
    return count


def last_completed_session(market: str, now: datetime) -> date:
    """Date of the latest daily bar that is complete at ``now`` (aware datetime).

    Yahoo dates forex and crypto daily bars by UTC day, and stock bars by the
    exchange's local day, complete at the close.
    """
    m = MARKETS.get(market, MARKETS["other"])
    if market in ("forex", "crypto"):
        today = now.astimezone(UTC).date()
        d = today - timedelta(days=1)
        while not is_trading_day(market, d):
            d -= timedelta(days=1)
        return d
    local = now.astimezone(ZoneInfo(m.timezone))
    today = local.date()
    if is_trading_day(market, today) and local.time() >= m.close_time:
        return today
    return previous_trading_day(market, today)


# --------------------------------------------------------------- sessions ---

def forex_sessions_open(now: datetime) -> list[str]:
    if not forex_week_open(now):
        return []
    open_now = []
    for name, (tz, start, end) in FOREX_SESSIONS.items():
        local = now.astimezone(ZoneInfo(tz))
        if local.weekday() < 5 and start <= local.time() < end:
            open_now.append(name)
    return open_now


def forex_week_open(now: datetime) -> bool:
    """Spot FX trades from Sunday 17:00 to Friday 17:00 New York time."""
    ny = now.astimezone(ZoneInfo("America/New_York"))
    wd, t = ny.weekday(), ny.time()
    if wd == 5:
        return False
    if wd == 6:
        return t >= time(17, 0)
    if wd == 4:
        return t < time(17, 0)
    return is_trading_day("forex", ny.date()) or t >= time(17, 0)


def market_status(market: str, now: datetime) -> dict:
    """Open/closed state of a market at ``now``, with a Persian label."""
    m = MARKETS.get(market, MARKETS["other"])
    if market == "crypto":
        return {"open": True, "label_fa": "باز (۲۴/۷)", "sessions": []}
    if market == "forex":
        sessions = forex_sessions_open(now)
        is_open = forex_week_open(now)
        names = "، ".join(SESSION_NAMES_FA[s] for s in sessions) or "بین سشن‌ها"
        return {"open": is_open, "label_fa": f"باز — {names}" if is_open else "بسته (تعطیلی آخر هفته)",
                "sessions": sessions}
    local = now.astimezone(ZoneInfo(m.timezone))
    if not is_trading_day(market, local.date()):
        return {"open": False, "label_fa": "بسته (تعطیل)", "sessions": []}
    is_open = m.open_time <= local.time() < m.close_time
    return {"open": is_open, "label_fa": "باز" if is_open else "بسته (خارج از ساعت معاملات)", "sessions": []}
