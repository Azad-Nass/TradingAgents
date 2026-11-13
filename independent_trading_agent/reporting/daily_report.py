"""Persian daily report (HTML, right-to-left), built from the app's database.

Sections: A Market Intelligence, B Detailed Trading Analysis, C Performance &
Risk. Markets always appear in the order forex, NASDAQ, NYSE, crypto, TSX,
TSXV. Files are archived by date and never overwritten.
"""
from __future__ import annotations

import html
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .. import __version__
from ..agents.chief import LABEL_FA
from ..core.markets import MARKETS, PRIORITY_ORDER, market_status
from ..performance.evaluate import grouped_metrics, metrics
from ..portfolio.exposure import exposure

ORDER = PRIORITY_ORDER + ["other"]
LABEL_CLASS = {"STRONG BUY": "buy", "BUY": "buy", "HOLD": "hold", "SELL": "sell", "STRONG SELL": "sell",
               "NO TRADE": "none"}


def e(x) -> str:
    return html.escape("" if x is None else str(x))


def num(v, digits: int = 4) -> str:
    if v is None:
        return "—"
    if isinstance(v, (int, float)):
        return f"{v:,.{digits}f}"
    return e(v)


def price_digits(market: str, price) -> int:
    """Decimals for a price: XAU/USD 2, USD/JPY 3, other majors 5, everything else 2."""
    if market != "forex" or price is None:
        return 2
    return 2 if price >= 500 else 3 if price >= 20 else 5


def pct(v, digits: int = 1) -> str:
    return "—" if v is None else f"{v * 100:+.{digits}f}%"


def _market_name(key: str) -> str:
    m = MARKETS.get(key)
    return f"{m.name_fa} ({m.name})" if m else e(key)


def _table(headers: list[str], rows: list[list[str]], cls: str = "") -> str:
    if not rows:
        return '<p class="muted">موردی وجود ندارد.</p>'
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="table-wrap"><table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _badge(label: str) -> str:
    return f'<span class="badge {LABEL_CLASS.get(label, "none")}">{e(label)} · {e(LABEL_FA.get(label, ""))}</span>'


CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#14171c;--muted:#5d6673;--line:#dfe3e8;--accent:#1f5fbf;
--buy:#0b7a43;--buy-bg:#e3f4ea;--sell:#b42318;--sell-bg:#fde8e6;--hold:#8a5a00;--hold-bg:#fdf3dc;--none:#4a5260;--none-bg:#eceef1}
@media (prefers-color-scheme:dark){:root{--bg:#0f1216;--card:#171b21;--ink:#e7eaee;--muted:#9aa4b1;--line:#2a3039;
--accent:#6aa0ff;--buy:#4cc38a;--buy-bg:#13301f;--sell:#ff8a7a;--sell-bg:#3a1a17;--hold:#f0c060;--hold-bg:#33290f;--none:#b4bcc7;--none-bg:#23282f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.75 "Vazirmatn","Segoe UI",Tahoma,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}h1{font-size:1.7rem;margin:0 0 4px}h2{font-size:1.3rem;margin:40px 0 12px;
padding-bottom:6px;border-bottom:2px solid var(--accent)}h3{font-size:1.1rem;margin:24px 0 8px}h4{margin:16px 0 6px;font-size:1rem}
.muted{color:var(--muted)}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin:12px 0}
.meta{display:flex;flex-wrap:wrap;gap:6px 18px;color:var(--muted);font-size:.9rem}.ltr{direction:ltr;unicode-bidi:isolate;display:inline-block}
.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:.92rem}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:right;vertical-align:top}
th{color:var(--muted);font-weight:600;white-space:nowrap}td.num,th.num{text-align:left;direction:ltr}
.badge{display:inline-block;padding:2px 10px;border-radius:999px;font-weight:700;font-size:.85rem;white-space:nowrap}
.badge.buy{color:var(--buy);background:var(--buy-bg)}.badge.sell{color:var(--sell);background:var(--sell-bg)}
.badge.hold{color:var(--hold);background:var(--hold-bg)}.badge.none{color:var(--none);background:var(--none-bg)}
.warn{border-inline-start:4px solid var(--hold);background:var(--hold-bg);padding:10px 14px;border-radius:6px;margin:10px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}ul{margin:4px 0;padding-inline-start:20px}
.pos{color:var(--buy)}.neg{color:var(--sell)}nav.toc a{margin-inline-end:14px}
@media print{body{background:#fff;font-size:12px}.card{break-inside:avoid}h2{break-before:page}h2:first-of-type{break-before:auto}}
"""


def _stance(score) -> str:
    if score is None:
        return "—"
    cls = "pos" if score > 0.1 else "neg" if score < -0.1 else ""
    return f'<span class="{cls} ltr">{score:+.2f}</span>'


def _section_a(run: dict, scan_rows: list[dict], analyses: list[dict], settings, now: datetime) -> str:
    summary = run.get("summary_json") or {}
    breadth = summary.get("breadth", {})
    skipped = summary.get("skipped_markets", {})
    included = [r for r in scan_rows if r["included"]]
    bulls = sorted([r for r in included if (r["score"] or 0) > 0.1], key=lambda r: -(r["interest"] or 0))[:settings.top_n]
    bears = sorted([r for r in included if (r["score"] or 0) < -0.1], key=lambda r: -(r["interest"] or 0))[:settings.top_n]
    labels = {}
    for a in analyses:
        labels[a["label"]] = labels.get(a["label"], 0) + 1

    out = ['<h2 id="a">بخش A — هوشمندی بازار (Market Intelligence)</h2>', '<h3>۱. خلاصه مدیریتی</h3><div class="card">']
    out.append(f"<p>{len(scan_rows)} نماد در {len([m for m in ORDER if m in breadth])} بازار پویش شد؛ "
               f"{len(included)} نماد از کنترل کیفیت و نقدشوندگی عبور کرد و {len(analyses)} نماد تحلیل عمیق شد.</p>")
    if analyses:
        out.append("<p>نتایج تحلیل عمیق: " + "، ".join(f"{_badge(k)} × {v}" for k, v in labels.items()) + "</p>")
        actionable = [a for a in analyses if a["label"] in ("BUY", "SELL", "STRONG BUY", "STRONG SELL")]
        if actionable:
            out.append("<p>سناریوهای فرضی تأییدشده توسط مدیر ریسک: " +
                       "، ".join(f"<b>{e(a['display'])}</b> {_badge(a['label'])}" for a in actionable) + "</p>")
        else:
            out.append("<p>امروز هیچ سناریوی معاملاتی از همه فیلترها (کیفیت داده، تعارض، ریسک) عبور نکرد.</p>")
    out.append("</div>")

    out.append("<h3>۲. وضعیت کلی بازارها</h3>")
    rows = []
    for key in ORDER:
        if key not in settings.markets and key not in breadth:
            continue
        b = breadth.get(key, {})
        status = market_status(key, now)
        rows.append([_market_name(key), e(status["label_fa"]), num(b.get("symbols"), 0), num(b.get("analysed"), 0),
                     "—" if b.get("pct_above_sma50") is None else f"{b['pct_above_sma50']:.0%}",
                     f'<span class="ltr">{pct(b.get("avg_ret5"))}</span>', e(skipped.get(key, ""))])
    out.append(_table(["بازار", "وضعیت (زمان گزارش)", "نمادها", "تحلیل‌شده", "بالای SMA50", "بازده ۵ روزه میانگین",
                       "توضیح"], rows))

    out.append("<h3>۳. روندهای مهم روز</h3>")
    trend_rows = []
    for key in ORDER:
        mk = [r for r in included if r["market"] == key]
        if not mk:
            continue
        strongest = sorted(mk, key=lambda r: -abs(r["score"] or 0))[:3]
        trend_rows.append([_market_name(key), "، ".join(
            f"{e(r['symbol'])} {_stance(r['score'])}" for r in strongest)])
    out.append(_table(["بازار", "قوی‌ترین روندها (امتیاز تکنیکال)"], trend_rows))

    out.append("<h3>۴. اخبار و رویدادهای اثرگذار</h3>")
    seen, news_rows = set(), []
    for a in analyses:
        for n in (a.get("news_json") or [])[:4]:
            if n["title"] in seen:
                continue
            seen.add(n["title"])
            news_rows.append([e(a["display"]), e(n["title"]), e(n.get("publisher")),
                              f'<span class="ltr">{e(n["published_utc"][:16].replace("T", " "))} UTC</span>',
                              _stance(n.get("sentiment"))])
    out.append(_table(["نماد", "عنوان", "منبع", "زمان انتشار", "احساسات"], news_rows[:15]))

    def opp_rows(items):
        return [[str(i + 1), f"<b>{e(r['symbol'])}</b>", _market_name(r["market"]), _stance(r["score"]),
                 num(r["interest"], 2), e("، ".join(r.get("flags_json") or []))] for i, r in enumerate(items)]

    out.append("<h3>۵. فرصت‌های صعودی برتر (نتیجه پویش؛ سیگنال نهایی نیست)</h3>")
    out.append(_table(["#", "نماد", "بازار", "امتیاز", "جذابیت", "نشانه‌ها"], opp_rows(bulls)))
    out.append("<h3>۶. فرصت‌های نزولی برتر (نتیجه پویش؛ سیگنال نهایی نیست)</h3>")
    out.append(_table(["#", "نماد", "بازار", "امتیاز", "جذابیت", "نشانه‌ها"], opp_rows(bears)))

    out.append("<h3>۷. تغییرات غیرعادی حجم و نوسان</h3>")
    abn = [r for r in included if any(str(f).startswith(("حجم", "نوسان")) for f in (r.get("flags_json") or []))]
    out.append(_table(["نماد", "بازار", "نشانه"], [[e(r["symbol"]), _market_name(r["market"]),
               e("، ".join(f for f in r["flags_json"] if str(f).startswith(("حجم", "نوسان"))))] for r in abn]))

    out.append("<h3>۸. فهرست پیگیری روز بعد</h3>")
    watch = [r for r in included if any("شکست" in str(f) for f in (r.get("flags_json") or []))
             or 0.2 <= (r["interest"] or 0) < settings.min_interest]
    watch_rows = [[e(r["symbol"]), _market_name(r["market"]), num(r["interest"], 2),
                   e("، ".join(r.get("flags_json") or []))] for r in watch[:12]]
    watch_rows += [[e(a["display"]), _market_name(a["market"]), "—", f"تحلیل عمیق: {_badge(a['label'])}"]
                   for a in analyses if a["label"] in ("HOLD", "NO TRADE")]
    out.append(_table(["نماد", "بازار", "جذابیت", "دلیل پیگیری"], watch_rows))
    return "\n".join(out)


def _analysis_card(a: dict, digits: int) -> str:
    d = a.get("decision_json") or {}
    q = a.get("quality_json") or {}
    plan, risk = a.get("plan_json"), a.get("risk_json") or {}
    ops = a.get("opinions_json") or []
    out = [f'<div class="card" id="sym-{e(a["symbol"])}"><h3>{e(a["display"])} {_badge(a["label"])}</h3>',
           f'<div class="meta"><span>بازار: {_market_name(a["market"])}</span>'
           f'<span>ارز: {e(MARKETS.get(a["market"], MARKETS["other"]).currency)}</span>'
           f'<span>زمان تحلیل: <span class="ltr">{e(a["created_utc"])}</span></span>'
           f'<span>آخرین قیمت معتبر: <span class="ltr">{num(a.get("last_price"), digits)}</span> '
           f'(کندل <span class="ltr">{e(a.get("data_as_of"))}</span>)</span>'
           f'<span>منبع: {e(a.get("data_source"))}</span></div>']
    out.append(f"<h4>کیفیت و تازگی داده: {e('خوب' if q.get('ok') and not q.get('warnings') else 'با هشدار' if q.get('ok') else 'نامعتبر')}</h4>")
    notes = (q.get("issues") or []) + (q.get("warnings") or [])
    out.append("<ul>" + "".join(f"<li>{e(n)}</li>" for n in notes) + "</ul>" if notes else
               f'<p class="muted">{num(q.get("bars"), 0)} کندل، آخرین کندل {e(q.get("last_bar"))}.</p>')

    for op in ops:
        if not op.get("applicable"):
            out.append(f'<h4>{e(op["role_fa"])}</h4><p class="muted">{e(op.get("note_fa"))}</p>')
            continue
        out.append(f'<h4>{e(op["role_fa"])} — {_stance(op["score"])} · اطمینان {op["confidence"]:.0%}</h4>')
        if op.get("note_fa"):
            out.append(f"<p>{e(op['note_fa'])}</p>")
        evs = op.get("evidence") or []
        if evs:
            out.append("<ul>" + "".join(
                f'<li>{"🟢 " if x["stance"] > 0 else "🔴 " if x["stance"] < 0 else ""}{e(x["text_fa"])}'
                f'{" <span class=muted>[<span class=ltr>" + e(x["source"]) + "</span>]</span>" if x.get("source") else ""}</li>'
                for x in evs[:10]) + "</ul>")
        if op.get("uncertainties"):
            out.append('<p class="muted">عدم قطعیت: ' + "؛ ".join(e(u) for u in op["uncertainties"]) + "</p>")

    deb = a.get("debate_json") or {}
    if deb:
        out.append('<h4>استدلال صعودی و نزولی</h4><div class="grid">')
        for side in ("bull", "bear"):
            c = deb.get(side) or {}
            pts = "".join(f"<li>{e(p['text_fa'])}</li>" for p in c.get("points", [])[:5]) or "<li>—</li>"
            cps = "".join(f"<li>{e(p['text_fa'])} ← <i>{e(p['response_fa'])}</i></li>"
                          for p in c.get("counterpoints", []))
            out.append(f'<div><b>{e(c.get("role_fa"))}</b> (قدرت {num(c.get("strength"), 2)})<ul>{pts}</ul>'
                       f'{"<p class=muted>پاسخ به نکات طرف مقابل:</p><ul>" + cps + "</ul>" if cps else ""}</div>')
        out.append("</div>")

    out.append(f'<h4>نتیجه نهایی: {_badge(a["label"])} — اطمینان {d.get("confidence", 0):.0%}'
               f'{"" if d.get("confidence_calibrated") else " (کالیبره‌نشده؛ نمونه تاریخی کافی نیست)"}</h4>')
    out.append("<ul>" + "".join(f"<li>{e(r)}</li>" for r in d.get("reasons_fa", [])) + "</ul>")
    if d.get("agreeing") or d.get("disagreeing"):
        out.append(f'<p>موافق: {e("، ".join(d.get("agreeing", [])) or "—")} | مخالف: {e("، ".join(d.get("disagreeing", [])) or "—")}</p>')
    if plan and d.get("direction"):
        out.append(_table(["جهت", "محدوده ورود فرضی", "حد ضرر", "اهداف", "R:R تا هدف اول", "R:R مؤثر", "افق"], [[
            "خرید (Long)" if plan["direction"] > 0 else "فروش (Short)",
            f'<span class="ltr">{num(plan["entry_low"], digits)} – {num(plan["entry_high"], digits)}</span>',
            f'<span class="ltr">{num(plan["stop"], digits)}</span>',
            f'<span class="ltr">{" / ".join(num(t, digits) for t in plan["targets"])}</span>',
            num(plan["reward_risk"], 2), num(plan["effective_reward_risk"], 2), f'{plan["horizon_bars"]} کندل']]))
        sz = risk.get("sizing") or {}
        if sz.get("ok"):
            out.append(f'<p>اندازه فرضی: <span class="ltr">{num(sz.get("lots") or sz.get("units"), 2)}</span> '
                       f'{"لات" if sz.get("lots") else "واحد"}، ریسک <span class="ltr">{num(sz.get("risk_amount"), 2)}</span>، '
                       f'ارزش اسمی <span class="ltr">{num(sz.get("notional_account"), 0)}</span>، اهرم {num(sz.get("leverage"), 2)}×</p>')
        out.append(f'<p><b>عامل ابطال سناریو:</b> بسته‌شدن قیمت {"زیر" if plan["direction"] > 0 else "بالای"} '
                   f'<span class="ltr">{num(plan["stop"], digits)}</span> یا پایان افق بدون رسیدن به هدف.</p>')
    risks = (risk.get("vetoes") or []) + (risk.get("cautions") or [])
    if risks:
        out.append("<h4>ریسک‌ها</h4><ul>" + "".join(f"<li>{e(x)}</li>" for x in risks) + "</ul>")
    if a.get("narrative"):
        src = "مدل زبانی + الگو" if a.get("narrative_source") == "llm+template" else "الگو"
        out.append(f'<h4>جمع‌بندی ({src})</h4><p style="white-space:pre-line">{e(a["narrative"])}</p>')
    out.append("</div>")
    return "\n".join(out)


def _section_b(analyses: list[dict]) -> str:
    out = ['<h2 id="b">بخش B — تحلیل معاملاتی تفصیلی (Detailed Trading Analysis)</h2>']
    if not analyses:
        out.append('<p class="muted">در این اجرا تحلیل عمیقی انجام نشد.</p>')
    for key in ORDER:
        group = [a for a in analyses if a["market"] == key]
        if group:
            out.append(f"<h3>{_market_name(key)}</h3>")
            out.extend(_analysis_card(a, price_digits(key, a.get("last_price"))) for a in group)
    return "\n".join(out)


def _section_c(repo, settings, run: dict) -> str:
    out = ['<h2 id="c">بخش C — عملکرد و ریسک (Performance &amp; Risk)</h2>']
    sigs = repo.signals(mode="live", limit=40)
    rows = []
    for s in sigs:
        res = "باز" if s["status"] == "open" else f'{e(s.get("exit_reason"))} · <span class="ltr">{pct(s.get("net_return"), 2)}</span> · R={num(s.get("r_multiple"), 2)}'
        rows.append([e(s["symbol"]), _market_name(s["market"]), _badge(s["label"]),
                     f'<span class="ltr">{e(s["issued_utc"][:16])}</span>', f'<span class="ltr">{num(s["ref_price"], 5)}</span>',
                     f'<span class="ltr">{num(s["stop"], 5)}</span>', res])
    out.append("<h3>سیگنال‌های قبلی و وضعیت آن‌ها (زنده، فرضی)</h3>")
    out.append(_table(["نماد", "بازار", "سیگنال", "زمان صدور (UTC)", "قیمت مبنا", "حد ضرر", "نتیجه"], rows))

    evals = repo.evaluations("live")
    m = metrics(evals, settings.risk_per_trade_pct)
    out.append("<h3>معیارهای عملکرد تاریخی (سیگنال‌های زنده ارزیابی‌شده)</h3>")
    if not m.get("n"):
        out.append('<p class="muted">هنوز هیچ سیگنالی به پایان افق ارزیابی نرسیده است.</p>')
    else:
        period = f'{evals[0]["issued_utc"][:10]} تا {evals[-1]["issued_utc"][:10]}'
        out.append(_table(["تعداد", "دوره", "Win Rate", "Profit Factor", "میانگین بازده", "Sharpe (هر معامله)",
                           "Sortino (هر معامله)", "Max Drawdown"], [[
            str(m["n"]), period, f'{m["win_rate"]:.0%}', num(m["profit_factor"], 2), pct(m["avg_return"], 2),
            num(m["sharpe_per_trade"], 2), num(m["sortino_per_trade"], 2), f'{m["max_drawdown"]:.1%}']]))
        if m.get("sample_note_fa"):
            out.append(f'<div class="warn">{e(m["sample_note_fa"])} (n={m["n"]})</div>')
        by_market = grouped_metrics(evals, "market", settings.risk_per_trade_pct)
        out.append(_table(["بازار", "تعداد", "Win Rate", "میانگین بازده"], [
            [_market_name(k), str(v["n"]), f'{v["win_rate"]:.0%}', pct(v["avg_return"], 2)]
            for k, v in sorted(by_market.items(), key=lambda kv: ORDER.index(kv[0]) if kv[0] in ORDER else 99)]))
    bt = repo.evaluations("backtest")
    if bt:
        mb = metrics(bt, settings.risk_per_trade_pct)
        out.append(f'<p class="muted">بک‌تست (جدا از عملکرد زنده؛ فقط تکنیکال، دارای سوگیری بقا): '
                   f'n={mb["n"]}، Win Rate {mb["win_rate"]:.0%}، میانگین بازده {pct(mb["avg_return"], 2)}.</p>')

    open_rows = repo.signals(mode="live", status="open")
    ex = exposure([{"symbol": s["symbol"], "market": s["market"], "direction": s["direction"],
                    "sizing": s.get("sizing_json")} for s in open_rows], settings.portfolio_value)
    out.append("<h3>ریسک و تمرکز پرتفوی فرضی</h3>")
    out.append(f'<p>ارزش فرضی پرتفوی: <span class="ltr">{num(settings.portfolio_value, 0)} {e(settings.account_currency)}</span>، '
               f'ریسک هر معامله {settings.risk_per_trade_pct}%؛ سیگنال باز: {ex["open_count"]}، ریسک باز مجموع '
               f'{num(ex["total_risk_pct"], 2)}%، اهرم ناخالص {num(ex["gross_leverage"], 2)}×.</p>')
    if ex["currency_net"]:
        out.append("<p>مواجهه خالص ارزی (Forex): " + "، ".join(
            f'{e(k)} <span class="ltr">{num(v, 0)}</span>' for k, v in list(ex["currency_net"].items())[:8]) + "</p>")
    for w in ex["warnings"]:
        out.append(f'<div class="warn">{e(w)}</div>')

    out.append("<h3>خطاها، داده‌های ناقص و محدودیت‌های اجرای امروز</h3>")
    errs = run.get("errors_json") or []
    summary = run.get("summary_json") or {}
    items = [e(x) for x in errs] + [f"{_market_name(k)}: {e(v)}" for k, v in (summary.get("skipped_markets") or {}).items()]
    if summary.get("excluded"):
        items.append(f'{summary["excluded"]} نماد به‌دلیل کیفیت داده یا نقدشوندگی کنار گذاشته شد (جزئیات در پایگاه داده)')
    if summary.get("data_requests") is not None:
        items.append(f'درخواست‌های داده مصرف‌شده: {summary["data_requests"]} از {settings.max_data_requests}')
    if summary.get("llm"):
        items.append(f'مدل زبانی: {e(summary["llm"])}')
    items.append("داده Yahoo Finance غیررسمی و با تأخیر است؛ قیمت لحظه‌ای نیست.")
    out.append("<ul>" + "".join(f"<li>{x}</li>" for x in items) + "</ul>")
    return "\n".join(out)


def render(repo, settings, run: dict, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    tz = ZoneInfo(settings.report_timezone)
    local = now.astimezone(tz)
    scan_rows = repo.scan_rows(run["id"])
    analyses = sorted(repo.analyses(run_id=run["id"], limit=500),
                      key=lambda a: (ORDER.index(a["market"]) if a["market"] in ORDER else 99, a["created_utc"]))
    title = "گزارش روزانه هوشمندی و تحلیل معاملات" if run["kind"] == "daily" else "گزارش تحلیل نماد"
    head = (f'<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)} — {local:%Y-%m-%d}</title>'
            f'<style>{CSS}</style></head><body><main>')
    meta = (f'<h1>{e(title)}</h1><div class="meta"><span>تاریخ و ساعت: <span class="ltr">{local:%Y-%m-%d %H:%M}</span> '
            f'({e(settings.report_timezone)}) — <span class="ltr">{now:%Y-%m-%d %H:%M} UTC</span></span>'
            f'<span>شناسه اجرا: <span class="ltr">{e(run["id"])}</span></span><span>نسخه: {e(__version__)}</span>'
            f'<span>بازارها به ترتیب اولویت: Forex، NASDAQ، NYSE، Crypto، TSX، TSXV</span></div>'
            '<div class="warn">این گزارش صرفاً تحلیلی و آموزشی است؛ توصیه سرمایه‌گذاری، سیگنال قطعی یا تضمین سود نیست. '
            'هیچ سفارش واقعی ثبت نمی‌شود و همه سناریوها فرضی‌اند.</div>'
            '<nav class="toc"><a href="#a">بخش A</a><a href="#b">بخش B</a><a href="#c">بخش C</a></nav>')
    parts = [head, meta]
    if run["kind"] == "daily" or scan_rows:
        parts.append(_section_a(run, scan_rows, analyses, settings, now))
    parts.append(_section_b(analyses))
    parts.append(_section_c(repo, settings, run))
    parts.append("</main></body></html>")
    return "\n".join(parts)


def archive_path(reports_dir: str, kind: str, now: datetime, tz: str) -> Path:
    local = now.astimezone(ZoneInfo(tz))
    folder = Path(reports_dir) / kind / f"{local:%Y}" / f"{local:%m}"
    folder.mkdir(parents=True, exist_ok=True)
    base = f"{kind}_{local:%Y-%m-%d_%H%M%S}"
    path, n = folder / f"{base}.html", 1
    while path.exists():
        n += 1
        path = folder / f"{base}_{n}.html"
    return path


def write(html_text: str, path: Path) -> Path:
    with open(path, "x", encoding="utf-8") as fh:  # "x": never overwrite an archived report
        fh.write(html_text)
    return path
