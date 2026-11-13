"""Optional FRED macro data for forex, read as of the analysis date (ALFRED vintages)."""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from datetime import date, datetime
from zoneinfo import ZoneInfo

from ..config.settings import secret
from ..core.runtime import redact

logger = logging.getLogger(__name__)

# Short-term rates, freshest first: daily policy rates where FRED carries them (Fed funds, ECB deposit
# facility), else the OECD 3-month interbank rate (monthly, published with a lag). CPI y/y from the OECD.
RATE_SERIES = {"USD": ["DFF", "IR3TIB01USM156N"], "EUR": ["ECBDFR", "IR3TIB01EZM156N"],
               "GBP": ["IR3TIB01GBM156N"], "JPY": ["IR3TIB01JPM156N", "IRSTCB01JPM156N"],
               "AUD": ["IR3TIB01AUM156N"], "CAD": ["IR3TIB01CAM156N"], "CHF": ["IR3TIB01CHM156N"],
               "NZD": ["IR3TIB01NZM156N"]}
SERIES_KIND_FA = {"DFF": "نرخ سیاستی فدرال رزرو (روزانه)", "ECBDFR": "نرخ سپرده بانک مرکزی اروپا (روزانه)"}
MAX_AGE_DAYS = 120  # older observations are reported as stale and not used for a view
CPI_SERIES = {"USD": "CPALTT01USM659N", "GBP": "CPALTT01GBM659N", "JPY": "CPALTT01JPM659N",
              "AUD": "CPALTT01AUQ659N", "CAD": "CPALTT01CAM659N", "CHF": "CPALTT01CHM659N",
              "NZD": "CPALTT01NZQ659N"}


def _latest(series_id: str, as_of: date, key: str) -> dict | None:
    params = urllib.parse.urlencode({
        "series_id": series_id, "api_key": key, "file_type": "json", "sort_order": "desc", "limit": 3,
        "observation_end": as_of.isoformat(), "realtime_start": as_of.isoformat(), "realtime_end": as_of.isoformat()})
    url = f"https://api.stlouisfed.org/fred/series/observations?{params}"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.info("FRED %s unavailable: %s", series_id, redact(str(exc)))
        return None
    for obs in data.get("observations", []):
        try:
            value, when = float(obs["value"]), date.fromisoformat(obs["date"])
        except (ValueError, KeyError):
            continue
        age = (as_of - when).days
        return {"value": value, "date": obs["date"], "series": series_id, "age_days": age,
                "stale": age > MAX_AGE_DAYS,
                "kind_fa": SERIES_KIND_FA.get(series_id, "نرخ بین‌بانکی ۳ ماهه OECD (ماهانه)"),
                "category": "policy" if series_id in SERIES_KIND_FA else "interbank"}
    return None


def _freshest(series_ids: list[str], as_of: date, key: str) -> dict | None:
    """The first series with a fresh observation, else the most recent stale one."""
    found = [obs for sid in series_ids if (obs := _latest(sid, as_of, key))]
    fresh = [o for o in found if not o["stale"]]
    if fresh:
        return fresh[0]
    return max(found, key=lambda o: o["date"]) if found else None


def fred_today() -> date:
    """FRED's own calendar day (US Central); it rejects real-time dates after it."""
    return datetime.now(ZoneInfo("America/Chicago")).date()


def forex_macro(base: str, quote: str, as_of: date) -> dict:
    as_of = min(as_of, fred_today())
    key = secret("FRED_API_KEY")
    if not key:
        return {"available": False, "reason_fa": "کلید FRED (INDEPENDENT_AGENT_FRED_API_KEY) تنظیم نشده است"}
    out = {"available": False, "base": base, "quote": quote, "as_of": as_of.isoformat()}
    for ccy, tag in ((base, "base"), (quote, "quote")):
        if ccy in RATE_SERIES:
            out[f"rate_{tag}"] = _freshest(RATE_SERIES[ccy], as_of, key)
        if ccy in CPI_SERIES:
            out[f"cpi_{tag}"] = _latest(CPI_SERIES[ccy], as_of, key)
    out["available"] = bool(out.get("rate_base") and out.get("rate_quote"))
    if not out["available"]:
        out["reason_fa"] = "سری نرخ بهره یکی از دو ارز از FRED دریافت نشد"
    return out
