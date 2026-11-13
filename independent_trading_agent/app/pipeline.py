"""The engine: mode 1 (analyse chosen symbols), mode 2 (scan), evaluation and the daily run.

Decision flow per symbol (TradingAgents is the analysis engine):
price data + quality check -> TradingAgents multi-agent LLM analysis (its
analysts, bull/bear debate, trader, risk team and portfolio manager)
-> FRED macro view and Gemini sentiment of TradingAgents' news report
-> plan (TradingAgents' stop/target when sane, else ATR) -> risk officer
-> decision (TradingAgents' rating, stopped by bad data or a risk veto,
weakened by strong macro/sentiment opposition) -> stored with evidence.
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from datetime import UTC, datetime

from ..agents import chief, macro_analyst, narrative, risk_officer, sentiment_analyst, trader
from ..agents.base import AnalysisContext
from ..analysis.prepare import prepare
from ..config.settings import Settings
from ..core.data_provider import RequestBudget, YahooProvider
from ..core.markets import MARKETS, display_symbol, forex_pair, infer_market, to_yahoo
from ..core.runtime import redact
from ..database.db import Repository
from ..integrations import fred, tradingagents_adapter
from ..integrations.llm_client import LLMClient
from ..market_scanner.scanner import ScanResult, scan
from ..performance.evaluate import calibration_table, evaluate_signal, make_calibrator
from ..risk_management.sizing import round_trip_cost

logger = logging.getLogger(__name__)
ENGINE_VERSION = "tradingagents-primary/0.2"


def settings_fingerprint(settings: Settings) -> str:
    return hashlib.sha256(json.dumps(settings.public_dict(), sort_keys=True, default=str).encode()).hexdigest()[:12]


class Engine:
    def __init__(self, settings: Settings, provider=None, repo: Repository | None = None,
                 now: datetime | None = None, llm: LLMClient | None = None):
        self.settings = settings
        self.provider = provider or YahooProvider(RequestBudget(settings.max_data_requests,
                                                                settings.request_delay_seconds))
        self.repo = repo or Repository(settings.db_path)
        self.now = now or datetime.now(UTC)
        self.llm = llm if llm is not None else (
            LLMClient(settings.llm_chain, settings.max_llm_calls, settings.llm_timeout_seconds)
            if settings.llm_enabled else None)
        self.errors: list[str] = []
        self._fx: dict[tuple[str, str], float | None] = {}
        self.ta_runs = 0

    # ------------------------------------------------------------ helpers ---
    def _error(self, msg: str):
        msg = redact(msg)
        logger.warning(msg)
        self.errors.append(msg)

    def fx(self, src: str, dst: str) -> float | None:
        """Latest completed daily rate src->dst from the provider, cached per run."""
        if src == dst:
            return 1.0
        key = (src, dst)
        if key not in self._fx:
            rate = None
            try:
                data = self.provider.history([f"{src}{dst}=X"], "1mo", "1d")
                df = data.get(f"{src}{dst}=X")
                if df is not None and not df.empty:
                    rate = float(df["close"].dropna().iloc[-1])
            except Exception as exc:
                self._error(f"FX rate {src}/{dst} unavailable: {exc}")
            self._fx[key] = rate
        return self._fx[key]

    def _open_signals(self) -> list[dict]:
        return [{"symbol": s["symbol"], "yahoo": s["yahoo"], "market": s["market"], "direction": s["direction"],
                 "sizing": s.get("sizing_json"), "issued_utc": s["issued_utc"], "label": s["label"]}
                for s in self.repo.signals(mode="live", status="open")]

    def _calibrator(self):
        return make_calibrator(calibration_table(self.repo.evaluations("live")))

    def _tradingagents(self, sym: str, yahoo: str, market_key: str, prep) -> dict:
        s = self.settings
        if not s.tradingagents_enabled:
            return {"ok": False, "error": "TradingAgents در تنظیمات غیرفعال است"}
        if not prep.quality.ok:
            return {"ok": False, "error": "کیفیت داده قیمت کافی نیست؛ TradingAgents اجرا نشد"}
        if self.ta_runs >= s.tradingagents_max_runs:
            return {"ok": False, "error": f"سقف {s.tradingagents_max_runs} تحلیل TradingAgents در این اجرا پر شد"}
        self.ta_runs += 1
        analysts = s.tradingagents_analysts_stock if MARKETS[market_key].asset_class == "stock" \
            else s.tradingagents_analysts
        result = tradingagents_adapter.run_deep_analysis(
            yahoo, prep.snap["date"], asset_type="crypto" if market_key == "crypto" else "stock", analysts=analysts,
            timeout=s.tradingagents_timeout_seconds, data_dir=s.data_dir, language=s.tradingagents_language)
        if not result.get("ok"):
            self._error(f"TradingAgents for {sym}: {str(result.get('error', ''))[:300]}")
        return result

    # -------------------------------------------------------------- mode 1 ---
    def analyze(self, symbols: list[str], run_id: str | None = None, *, scan_info: dict | None = None,
                market_hint: dict | None = None) -> list[dict]:
        s = self.settings
        market_of = {sym: (market_hint or {}).get(sym) or infer_market(sym) for sym in symbols}
        open_signals = self._open_signals()
        needed = {to_yahoo(sym, market_of[sym]) for sym in symbols}
        needed.update(o["yahoo"] for o in open_signals if o.get("yahoo"))  # for the risk officer's correlations
        try:
            data = self.provider.history(sorted(needed), s.lookback_period, s.timeframe)
        except Exception as exc:
            self._error(f"price history unavailable: {type(exc).__name__}: {exc}")
            data = {}
        prepared = {}
        for y, raw in data.items():
            mk = next((market_of[x] for x in symbols if to_yahoo(x, market_of[x]) == y), infer_market(y))
            prepared[y] = prepare(raw, mk, self.now, min_bars=s.min_bars, max_stale_sessions=s.max_stale_sessions,
                                  interval=s.timeframe)
        calibrate = self._calibrator()
        results = []
        for sym in symbols:
            try:
                results.append(self._analyze_one(sym, market_of[sym], prepared, open_signals, calibrate, run_id,
                                                 (scan_info or {}).get(sym)))
            except Exception as exc:  # one bad symbol must not stop the run
                logger.exception("analysis of %s failed", sym)
                self._error(f"analysis of {sym} failed: {type(exc).__name__}: {exc}")
        return results

    def _analyze_one(self, sym, market_key, prepared, open_signals, calibrate, run_id, scan_row):
        s = self.settings
        m = MARKETS[market_key]
        yahoo = to_yahoo(sym, market_key)
        disp = display_symbol(sym, market_key)
        prep = prepared.get(yahoo)
        if prep is None:
            prep = prepare(None, market_key, self.now, min_bars=s.min_bars, max_stale_sessions=s.max_stale_sessions)
        if prep.snap is None:
            decision = chief.Decision("NO TRADE", 0, 0.0, 0.0, 0.0, False,
                                      ["داده قیمت کافی برای تحلیل وجود ندارد: " + "؛ ".join(prep.quality.issues)])
            row = {"run_id": run_id, "symbol": sym, "display": disp, "yahoo": yahoo, "market": market_key,
                   "data_as_of": prep.quality.last_bar, "data_source": self.provider.name,
                   "quality_json": prep.quality.to_dict(), "opinions_json": [], "debate_json": {},
                   "decision_json": decision.to_dict(), "label": decision.label, "confidence": 0.0,
                   "narrative": decision.reasons_fa[0], "narrative_source": "template",
                   "model_info_json": {"engine": ENGINE_VERSION}}
            row["id"] = self.repo.add_analysis(row)
            return row

        macro = None
        if market_key == "forex":
            base, quote = forex_pair(sym)
            macro = (fred.gold_macro(self.now.date()) if (base, quote) == ("XAU", "USD")
                     else fred.forex_macro(base, quote, self.now.date()))
        peers = {y: p.bars for y, p in prepared.items() if p.bars is not None and not p.bars.empty}
        ctx = AnalysisContext(sym, disp, yahoo, m, prep.bars, prep.ind, prep.snap, prep.levels, prep.quality,
                              self.now, self.provider.name, macro=macro, peers=peers, open_signals=open_signals)

        ta_result = self._tradingagents(sym, yahoo, market_key, prep)
        supplements = [macro_analyst.analyze_macro(ctx), sentiment_analyst.analyze(self.llm, disp, ta_result)]
        opinions = [tradingagents_adapter.to_opinion(ta_result), *supplements]

        direction = chief.TA_DIRECTION.get(ta_result.get("rating"), 0) if ta_result.get("ok") else 0
        numbers = ta_result.get("numbers") or {}
        plan = trader.make_plan(ctx, direction, s.horizon_bars, stop_hint=numbers.get("stop_loss"),
                                target_hint=numbers.get("price_target")) if direction else None
        risk = risk_officer.assess(ctx, plan, s, self.fx) if plan else None
        decision = chief.decide_tradingagents(ta_result, supplements, prep.quality.ok, risk, calibrate)
        plan_d, risk_d = (plan.to_dict() if plan else None), (risk.to_dict() if risk else None)
        # One open hypothetical signal per symbol: a repeat analysis is stored, but opens no second trade.
        already_open = next((o for o in open_signals if o["symbol"] == sym), None)
        if already_open and decision.direction:
            same = already_open["direction"] == decision.direction
            decision.reasons_fa.append(
                f"سیگنال باز قبلی ({already_open['label']}، صادره {already_open['issued_utc'][:16]} UTC) هنوز فعال است؛ "
                + ("سیگنال تکراری ثبت نشد" if same else "این تحلیل خلاف جهت آن است؛ سیگنال جدید ثبت نشد"))

        debate = ta_result.get("debate") or {}
        debate_d = {side: {"role_fa": f"پژوهشگر {'صعودی' if side == 'bull' else 'نزولی'} TradingAgents",
                           "strength": None, "points": [{"text_fa": debate[side]}] if debate.get(side) else [],
                           "counterpoints": []} for side in ("bull", "bear")} if debate else {}
        ta_d = ({k: ta_result.get(k) for k in ("rating", "trade_date", "analysts", "reports", "numbers", "models")}
                if ta_result.get("ok") else {"error": ta_result.get("error")})
        chart = prep.ind.tail(180)
        chart_d = {"dates": [d.date().isoformat() for d in chart.index]}
        for col in ("open", "high", "low", "close", "volume", "sma50", "sma200", "ema20", "bb_upper", "bb_lower",
                    "rsi14", "macd_hist"):
            chart_d[col] = [None if v != v else round(float(v), 6) for v in chart[col]]
        row = {
            "run_id": run_id, "symbol": sym, "display": disp, "yahoo": yahoo, "market": market_key,
            "data_as_of": prep.snap["date"], "last_price": prep.snap["close"], "data_source": self.provider.name,
            "quality_json": prep.quality.to_dict(), "opinions_json": [o.to_dict() for o in opinions],
            "debate_json": debate_d, "decision_json": decision.to_dict(), "label": decision.label,
            "confidence": decision.confidence, "plan_json": plan_d, "risk_json": risk_d,
            "narrative": narrative.template(disp, decision, opinions, plan_d, risk_d), "narrative_source": "template",
            "chart_json": chart_d, "news_json": [], "scan_json": scan_row, "ta_json": ta_d,
            "model_info_json": {"engine": ENGINE_VERSION, "tradingagents": ta_result.get("models"),
                                "llm_models": list(dict.fromkeys(self.llm.used_models)) if self.llm else [],
                                "settings_fingerprint": settings_fingerprint(s)},
        }
        row["id"] = self.repo.add_analysis(row)
        if decision.direction and plan and not already_open:
            self.repo.add_signal({
                "analysis_id": row["id"], "mode": "live", "symbol": sym, "yahoo": yahoo, "market": market_key,
                "issued_utc": self.now.isoformat(timespec="seconds"), "data_as_of": prep.snap["date"],
                "ref_price": plan.reference_price, "direction": decision.direction, "label": decision.label,
                "entry_low": plan.entry_low, "entry_high": plan.entry_high, "stop": plan.stop,
                "targets_json": plan.targets, "horizon_bars": plan.horizon_bars, "confidence": decision.confidence,
                "evidence_json": {"reasons": decision.reasons_fa, "agreeing": decision.agreeing,
                                  "disagreeing": decision.disagreeing},
                "sizing_json": (risk_d or {}).get("sizing"), "config_json": {"fingerprint": settings_fingerprint(s),
                                                                            "engine": ENGINE_VERSION},
            })
        return row

    # -------------------------------------------------------------- mode 2 ---
    def scan(self, run_id: str | None = None) -> ScanResult:
        result = scan(self.settings, self.provider, self.now)
        self.errors.extend(result.errors)
        if run_id:
            self.repo.add_scan_rows(run_id, [c.to_row() for c in result.candidates])
        return result

    def scan_and_analyze(self, run_id: str, extra_symbols: list[str] | None = None) -> tuple[ScanResult, list[dict]]:
        result = self.scan(run_id)
        picks = result.deep_candidates(self.settings.deep_top_k, self.settings.min_interest)
        hints = {c.symbol: c.market for c in picks}
        # The user's own watchlist goes first, so the TradingAgents run cap never cuts it.
        symbols = list(dict.fromkeys([*(extra_symbols or []), *(c.symbol for c in picks)]))
        info = {c.symbol: {"rank": c.rank, "interest": c.interest, "flags": c.flags} for c in picks}
        analyses = self.analyze(symbols, run_id, scan_info=info, market_hint=hints) if symbols else []
        return result, analyses

    # ---------------------------------------------------------- evaluation ---
    def evaluate_open(self) -> dict:
        s = self.settings
        open_rows = self.repo.signals(mode="live", status="open")
        if not open_rows:
            return {"evaluated": 0, "still_open": 0}
        try:
            data = self.provider.history(sorted({r["yahoo"] for r in open_rows}), s.lookback_period, s.timeframe)
        except Exception as exc:
            self._error(f"evaluation data unavailable: {exc}")
            return {"evaluated": 0, "still_open": len(open_rows), "error": str(exc)}
        done = 0
        for r in open_rows:
            prep = prepare(data.get(r["yahoo"]), r["market"], self.now, min_bars=1,
                           max_stale_sessions=s.max_stale_sessions)
            m = MARKETS[r["market"]]
            cost = round_trip_cost(asset_class=m.asset_class, symbol=r["symbol"], price=r["ref_price"],
                                   forex_spread_pips=s.forex_spread_pips, stock_spread_bps=s.stock_spread_bps,
                                   crypto_spread_bps=s.crypto_spread_bps, commission_bps=s.commission_bps,
                                   slippage_bps=s.slippage_bps, metal_spread_pips=s.metal_spread_pips)
            ev = evaluate_signal(direction=r["direction"], data_as_of=r["data_as_of"], stop=r["stop"],
                                 target=r["targets_json"][0], horizon_bars=r["horizon_bars"], bars=prep.bars,
                                 cost=cost)
            if ev:
                self.repo.add_evaluation({"signal_id": r["id"], **ev.to_dict()})
                done += 1
        return {"evaluated": done, "still_open": len(open_rows) - done}


def group_by_market(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        out[r["market"]].append(r)
    return out
