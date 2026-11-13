/* Independent Trading Agent dashboard: vanilla JS over the local JSON API. */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const view = $("#view");
const tip = $("#tip");
const state = { overview: null, tz: "UTC", selected: null, stockTab: "nasdaq", perfMode: "live" };

const MARKET_FA = { forex: "فارکس", nasdaq: "نزدک", nyse: "بورس نیویورک", crypto: "رمزارز", tsx: "بورس تورنتو",
  tsxv: "بورس ونچر تورنتو", other: "سایر" };
const LABEL_FA = { "STRONG BUY": "خرید قوی", "BUY": "خرید", "HOLD": "نگه‌داری", "SELL": "فروش",
  "STRONG SELL": "فروش قوی", "NO TRADE": "عدم معامله" };
const LABEL_CLS = { "STRONG BUY": "buy", "BUY": "buy", "HOLD": "hold", "SELL": "sell", "STRONG SELL": "sell", "NO TRADE": "none" };
const LABEL_ICON = { buy: "▲", sell: "▼", hold: "■", none: "○" };

function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function num(v, d = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}
function price(v, market) {
  if (market !== "forex" || v == null) return num(v, 2);
  const a = Math.abs(v);
  return num(v, a >= 500 ? 2 : a >= 20 ? 3 : 5);  // XAU/USD 2, USD/JPY 3, majors 5
}
function pct(v, d = 1, sign = true) {
  if (v === null || v === undefined) return "—";
  return (sign && v > 0 ? "+" : "") + (v * 100).toFixed(d) + "%";
}
function when(iso) {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat("en-CA", { timeZone: state.tz, year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(iso)).replace(",", "");
  } catch { return iso; }
}
function pill(label) {
  const cls = LABEL_CLS[label] || "none";
  return `<span class="pill ${cls}"><span aria-hidden="true">${LABEL_ICON[cls]}</span>${esc(label)}<span class="muted" style="font-weight:500">${esc(LABEL_FA[label] || "")}</span></span>`;
}
function signed(v, d = 2) {
  if (v === null || v === undefined) return "—";
  const cls = v > 0.1 ? "up" : v < -0.1 ? "down" : "";
  return `<span class="ltr ${cls}">${v > 0 ? "+" : ""}${Number(v).toFixed(d)}</span>`;
}
function empty(text) { return `<div class="empty">${text}</div>`; }

async function api(path) {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json();
}
async function post(path, body) {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", "X-ITA": "1" },
    body: JSON.stringify(body) });
  return res.json();
}

/* ---------------------------------------------------------------- theme --- */
function storedTheme() { try { return localStorage.getItem("ita-theme"); } catch { return null; } }
function applyTheme(t) {
  if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
  const dark = t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  $("#theme").textContent = dark ? "حالت روشن" : "حالت تاریک";
}
$("#theme").addEventListener("click", () => {
  const dark = getComputedStyle(document.documentElement).colorScheme.includes("dark");
  const next = dark ? "light" : "dark";
  try { localStorage.setItem("ita-theme", next); } catch { /* private mode */ }
  applyTheme(next);
});
applyTheme(storedTheme());

/* ------------------------------------------------------- ribbon/markets --- */
function renderRibbon(r) {
  const el = $("#ribbon");
  const lanes = ["asia", "london", "new_york"];
  const x = m => (m / 1440 * 100).toFixed(3) + "%";
  let html = "";
  lanes.forEach((key, i) => {
    html += `<div class="lane" style="top:${10 + i * 21}px">`;
    r.sessions.filter(s => s.key === key).forEach(s => {
      const live = r.now >= s.start && r.now < s.end;
      html += `<div class="band${live ? " live" : ""}" style="left:${x(s.start)};width:${x(s.end - s.start)}"
        title="${esc(s.name_fa)} ${esc(s.start_label)}–${esc(s.end_label)}">${esc(s.name_fa)} <span class="ltr">${esc(s.start_label)}–${esc(s.end_label)}</span></div>`;
    });
    html += "</div>";
  });
  html += `<div class="hours">${[0, 3, 6, 9, 12, 15, 18, 21, 24].map(h => `<span style="left:${h / 24 * 100}%">${String(h).padStart(2, "0")}</span>`).join("")}</div>`;
  html += `<div class="now" style="left:calc(14px + (100% - 28px) * ${r.now / 1440})"><b>اکنون ${esc(r.now_label)}</b></div>`;
  el.innerHTML = html;
  el.setAttribute("aria-label", `سشن‌های فارکس به وقت ${r.timezone}؛ اکنون ${r.now_label}`);
}
function renderMarkets(list) {
  $("#markets").innerHTML = list.map(m => `<li class="${m.open ? "open" : ""} ${m.enabled ? "" : "off"}">
    <span class="dot" aria-hidden="true"></span><span class="rank">${m.priority}</span>
    <b>${esc(m.name)}</b> <span>${esc(m.label_fa)}${m.enabled ? "" : " (غیرفعال)"}</span></li>`).join("");
}

/* --------------------------------------------------------------- charts --- */
const NS = "http://www.w3.org/2000/svg";
function showTip(evt, html) {
  tip.innerHTML = html; tip.hidden = false;
  const pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
  let left = evt.clientX + pad, top = evt.clientY + pad;
  if (left + w > innerWidth - 8) left = evt.clientX - w - pad;
  if (top + h > innerHeight - 8) top = evt.clientY - h - pad;
  tip.style.left = left + "px"; tip.style.top = top + "px";
}
function hideTip() { tip.hidden = true; }

function lineChart(host, { dates, series, band, height = 260, yFormat = v => num(v, 2), guides = [], domain }) {
  const W = 760, H = height, m = { t: 12, r: 64, b: 26, l: 8 };
  const n = dates.length;
  const vals = [];
  series.forEach(s => s.values.forEach(v => v != null && vals.push(v)));
  if (band) band.upper.concat(band.lower).forEach(v => v != null && vals.push(v));
  if (!n || !vals.length) { host.innerHTML = empty("داده‌ای برای نمودار نیست"); return; }
  let [lo, hi] = domain || [Math.min(...vals), Math.max(...vals)];
  const padv = (hi - lo) * 0.06 || Math.abs(hi) * 0.01 || 1; if (!domain) { lo -= padv; hi += padv; }
  const X = i => m.l + (W - m.l - m.r) * (n === 1 ? 0.5 : i / (n - 1));
  const Y = v => m.t + (H - m.t - m.b) * (1 - (v - lo) / (hi - lo));
  const path = arr => { let d = "", pen = false; arr.forEach((v, i) => { if (v == null) { pen = false; return; }
    d += (pen ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1); pen = true; }); return d; };
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(series.map(s => s.name).join("، "))}" direction="ltr"><g class="grid">`;
  const ticks = 4;
  for (let k = 0; k <= ticks; k++) {
    const v = lo + (hi - lo) * k / ticks;
    svg += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}"/>`;
  }
  svg += `</g><g class="axis">`;
  for (let k = 0; k <= ticks; k++) {
    const v = lo + (hi - lo) * k / ticks;
    svg += `<text x="${W - m.r + 6}" y="${Y(v) + 4}">${esc(yFormat(v))}</text>`;
  }
  const step = Math.max(1, Math.floor(n / 5));
  for (let i = 0; i < n; i += step) svg += `<text x="${X(i)}" y="${H - 6}" text-anchor="middle">${esc(dates[i].slice(5))}</text>`;
  svg += `</g>`;
  guides.forEach(g => { svg += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(g)}" y2="${Y(g)}" stroke="var(--muted)" stroke-dasharray="4 4" stroke-width="1"/>`; });
  if (band) {
    const up = band.upper.map((v, i) => v == null ? null : [X(i), Y(v)]).filter(Boolean);
    const dn = band.lower.map((v, i) => v == null ? null : [X(i), Y(v)]).filter(Boolean).reverse();
    if (up.length) svg += `<path d="M${up.concat(dn).map(p => p.map(c => c.toFixed(1)).join(" ")).join("L")}Z" fill="${band.color}" opacity="0.12"/>`;
  }
  series.forEach(s => { svg += `<path d="${path(s.values)}" fill="none" stroke="${s.color}" stroke-width="${s.width || 2}" stroke-linejoin="round" stroke-linecap="round"/>`; });
  svg += `<line class="xh" y1="${m.t}" y2="${H - m.b}" stroke="var(--ink)" stroke-width="1" opacity="0"/>`;
  series.forEach((s, j) => { svg += `<circle class="dot${j}" r="4" fill="${s.color}" stroke="var(--panel)" stroke-width="2" opacity="0"/>`; });
  svg += `<rect class="hit" x="${m.l}" y="0" width="${W - m.l - m.r}" height="${H}" fill="transparent"/></svg>`;
  const legend = series.length > 1 ? `<div class="legend">${series.map(s => `<span><i style="background:${s.color}"></i>${esc(s.name)}</span>`).join("")}</div>` : "";
  host.innerHTML = legend + `<div class="chart">${svg}</div>`;
  const el = host.querySelector("svg"), xh = el.querySelector(".xh"), hit = el.querySelector(".hit");
  hit.addEventListener("mousemove", evt => {
    const box = el.getBoundingClientRect();
    const px = (evt.clientX - box.left) / box.width * W;
    const i = Math.max(0, Math.min(n - 1, Math.round((px - m.l) / (W - m.l - m.r) * (n - 1))));
    xh.setAttribute("x1", X(i)); xh.setAttribute("x2", X(i)); xh.setAttribute("opacity", "0.35");
    series.forEach((s, j) => { const c = el.querySelector(".dot" + j); const v = s.values[i];
      if (v == null) c.setAttribute("opacity", "0"); else { c.setAttribute("cx", X(i)); c.setAttribute("cy", Y(v)); c.setAttribute("opacity", "1"); } });
    showTip(evt, `<b class="ltr">${esc(dates[i])}</b>` + series.map(s => `<div class="row"><span>${esc(s.name)}</span><span class="ltr">${s.values[i] == null ? "—" : esc(yFormat(s.values[i]))}</span></div>`).join(""));
  });
  hit.addEventListener("mouseleave", () => { hideTip(); xh.setAttribute("opacity", "0"); series.forEach((s, j) => el.querySelector(".dot" + j).setAttribute("opacity", "0")); });
}

function priceCharts(host, c, market) {
  const css = getComputedStyle(document.documentElement);
  const col = k => css.getPropertyValue(k).trim();
  host.innerHTML = `<div class="pc"></div><h3>RSI 14</h3><div class="rc"></div>`;
  lineChart(host.querySelector(".pc"), {
    dates: c.dates, yFormat: v => price(v, market),
    series: [{ name: "قیمت بسته‌شدن", values: c.close, color: col("--s1") },
             { name: "SMA50", values: c.sma50, color: col("--s2"), width: 1.6 },
             { name: "SMA200", values: c.sma200, color: col("--s3"), width: 1.6 }],
    band: { upper: c.bb_upper, lower: c.bb_lower, color: col("--s1") } });
  lineChart(host.querySelector(".rc"), { dates: c.dates, height: 120, domain: [0, 100], guides: [30, 70],
    yFormat: v => num(v, 0), series: [{ name: "RSI", values: c.rsi14, color: col("--s1") }] });
}

/* ----------------------------------------------------------- components --- */
function symbolTable(rows, onPick) {
  if (!rows.length) return empty("هنوز تحلیلی برای این بخش ثبت نشده است. از کادر «تحلیل نماد» بالای صفحه یا «پویش بازارها» استفاده کنید.");
  return `<div class="table-wrap"><table><thead><tr><th>نماد</th><th>نتیجه</th><th class="n">امتیاز</th>
    <th class="n">قیمت</th><th>داده</th></tr></thead><tbody>${rows.map(r => `
    <tr class="pick" tabindex="0" data-id="${esc(r.id)}" aria-selected="${state.selected === r.id}">
      <td><b>${esc(r.display)}</b><div class="fine">${esc(MARKET_FA[r.market] || r.market)}</div></td>
      <td>${pill(r.label)}</td><td class="n">${signed(r.score)}</td><td class="n">${price(r.last_price, r.market)}</td>
      <td class="fine">${esc(r.data_as_of || "—")}${r.quality_ok === false ? ' <span class="down">نامعتبر</span>' : r.quality_warnings ? " (هشدار)" : ""}</td>
    </tr>`).join("")}</tbody></table></div>`;
}
function bindPicks(root, loader) {
  root.querySelectorAll("tr.pick").forEach(tr => {
    const go = () => { state.selected = tr.dataset.id; root.querySelectorAll("tr.pick").forEach(x => x.setAttribute("aria-selected", x === tr)); loader(tr.dataset.id); };
    tr.addEventListener("click", go);
    tr.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
  });
}

function stanceRow(o) {
  if (!o.applicable) return `<div class="stance"><span>${esc(o.role_fa)}</span><span class="fine">${esc(o.note_fa)}</span><span></span></div>`;
  const s = Math.max(-1, Math.min(1, o.score || 0));
  const w = Math.abs(s) * 50;
  const bar = s >= 0 ? `left:50%;width:${w}%;background:var(--pos)` : `left:${50 - w}%;width:${w}%;background:var(--neg)`;
  const word = o.confidence === 0 ? "بدون داده" : s > 0.1 ? "صعودی" : s < -0.1 ? "نزولی" : "خنثی";
  return `<div class="stance"><span>${esc(o.role_fa)}<div class="fine">${word} · اطمینان ${Math.round(o.confidence * 100)}%</div></span>
    <span class="bar" aria-label="امتیاز ${s.toFixed(2)}"><span class="zero"></span><i style="${bar}"></i></span>${signed(s)}</div>`;
}

function agentsBlock(a) {
  const ops = a.opinions_json || [];
  return ops.map(o => `${stanceRow(o)}${o.applicable && (o.evidence || []).length ? `<details><summary class="fine">شواهد و منابع (${o.evidence.length})</summary>
    <ul class="evidence">${o.evidence.map(e => `<li>${e.stance > 0 ? '<span class="up">▲</span> ' : e.stance < 0 ? '<span class="down">▼</span> ' : ""}${esc(e.text_fa)}
    ${e.source ? `<span class="src">[<span class="ltr">${esc(e.source)}</span>${e.as_of ? " · " + esc(String(e.as_of).slice(0, 16)) : ""}]</span>` : ""}</li>`).join("")}</ul>
    ${(o.uncertainties || []).length ? `<p class="fine">عدم قطعیت: ${o.uncertainties.map(esc).join("؛ ")}</p>` : ""}</details>` : ""}`).join("");
}

function detailHtml(a) {
  const d = a.decision_json || {}, p = a.plan_json, r = a.risk_json || {}, q = a.quality_json || {};
  const deb = a.debate_json || {};
  const sz = r.sizing || {};
  const quality = q.ok ? (q.warnings || []).length ? "قابل قبول با هشدار" : "خوب" : "نامعتبر";
  let html = `<div class="panel"><h2 style="margin-top:0">${esc(a.display)} ${pill(a.label)}</h2>
    <dl class="facts"><dt>بازار</dt><dd>${esc(MARKET_FA[a.market] || a.market)}</dd>
    <dt>آخرین قیمت معتبر</dt><dd><span class="ltr">${price(a.last_price, a.market)}</span> — کندل <span class="ltr">${esc(a.data_as_of || "—")}</span></dd>
    <dt>زمان تحلیل</dt><dd><span class="ltr">${esc(when(a.created_utc))}</span></dd>
    <dt>منبع داده</dt><dd>${esc(a.data_source)}</dd>
    <dt>کیفیت داده</dt><dd>${quality}${[...(q.issues || []), ...(q.warnings || [])].map(x => `<div class="fine">${esc(x)}</div>`).join("")}</dd>
    <dt>نتیجه</dt><dd>امتیاز ${signed(d.score)} · تعارض ${pct(d.conflict, 0, false)} · اطمینان ${pct(d.confidence, 0, false)}${d.confidence_calibrated ? "" : " (کالیبره‌نشده)"}</dd></dl>
    <ul class="evidence">${(d.reasons_fa || []).map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>`;
  html += `<div class="panel" style="margin-top:12px"><h3 style="margin-top:0">قیمت، SMA50/200 و باند بولینگر</h3><div id="charts"></div></div>`;
  if (p && d.direction) {
    html += `<div class="panel" style="margin-top:12px"><h3 style="margin-top:0">سناریوی فرضی (شبیه‌سازی)</h3>
      <dl class="facts"><dt>جهت</dt><dd>${p.direction > 0 ? "خرید (Long)" : "فروش (Short)"}</dd>
      <dt>محدوده ورود</dt><dd><span class="ltr">${price(p.entry_low, a.market)} – ${price(p.entry_high, a.market)}</span></dd>
      <dt>حد ضرر</dt><dd><span class="ltr">${price(p.stop, a.market)}</span></dd>
      <dt>اهداف</dt><dd><span class="ltr">${p.targets.map(t => price(t, a.market)).join(" / ")}</span></dd>
      <dt>ریسک به بازده</dt><dd>تا هدف اول ${num(p.reward_risk)}، مؤثر ${num(p.effective_reward_risk)}</dd>
      <dt>افق</dt><dd>${p.horizon_bars} کندل</dd>
      <dt>اندازه فرضی</dt><dd>${sz.ok ? `<span class="ltr">${num(sz.lots ?? sz.units, 2)}</span> ${sz.lots != null ? "لات" : "واحد"}، ریسک <span class="ltr">${num(sz.risk_amount, 0)}</span>، اهرم ${num(sz.leverage)}×` : esc((sz.notes || []).join("؛ ") || "—")}</dd></dl>
      <p class="fine">ابطال سناریو: بسته‌شدن ${p.direction > 0 ? "زیر" : "بالای"} <span class="ltr">${price(p.stop, a.market)}</span>.</p></div>`;
  }
  const risks = [...(r.vetoes || []), ...(r.cautions || [])];
  if (risks.length) html += `<div style="margin-top:12px">${risks.map(x => `<div class="alert">${esc(x)}</div>`).join("")}</div>`;
  html += `<h3>نظر عامل‌ها</h3><div class="panel">${agentsBlock(a)}</div>`;
  if (deb.bull) {
    const side = c => `<div><h4>${esc(c.role_fa)} <span class="fine">قدرت ${num(c.strength)}</span></h4><ul class="evidence">${(c.points || []).slice(0, 5).map(x => `<li>${esc(x.text_fa)}</li>`).join("") || "<li>—</li>"}</ul>
      ${(c.counterpoints || []).length ? `<p class="fine">پاسخ به طرف مقابل:</p><ul class="evidence">${c.counterpoints.map(x => `<li>${esc(x.text_fa)} ← <i>${esc(x.response_fa)}</i></li>`).join("")}</ul>` : ""}</div>`;
    html += `<h3>مناظره صعودی و نزولی</h3><div class="panel debate">${side(deb.bull)}${side(deb.bear)}</div>`;
  }
  const news = a.news_json || [];
  html += `<h3>اخبار (با زمان انتشار)</h3>${news.length ? `<div class="panel"><ul class="evidence">${news.slice(0, 8).map(n => `<li>${n.link ? `<a href="${esc(n.link)}" target="_blank" rel="noopener noreferrer">${esc(n.title)}</a>` : esc(n.title)}
     <span class="src">— ${esc(n.publisher)} · <span class="ltr">${esc(when(n.published_utc))}</span>${n.sentiment != null ? " · احساسات " + signed(n.sentiment) : ""}</span></li>`).join("")}</ul></div>` : empty("خبر تازه‌ای ثبت نشده است.")}`;
  if (a.narrative) html += `<h3>جمع‌بندی ${a.narrative_source === "llm+template" ? "(مدل زبانی + الگو)" : "(الگو)"}</h3><div class="panel" style="white-space:pre-line">${esc(a.narrative)}</div>`;
  if ((a.history || []).length > 1) html += `<h3>تحلیل‌های قبلی این نماد</h3><div class="panel">${a.history.map(h => `<div class="fine"><span class="ltr">${esc(when(h.created_utc))}</span> ${pill(h.label)}</div>`).join("")}</div>`;
  return html;
}

async function loadDetail(id, host) {
  host.innerHTML = `<p class="loading">در حال بارگذاری تحلیل…</p>`;
  try {
    const a = await api(`/api/analysis/${encodeURIComponent(id)}`);
    host.innerHTML = detailHtml(a);
    const ch = host.querySelector("#charts");
    if (ch) a.chart_json ? priceCharts(ch, a.chart_json, a.market) : (ch.innerHTML = empty("برای این تحلیل داده نمودار ذخیره نشده است."));
  } catch (e) { host.innerHTML = `<div class="alert err">بارگذاری تحلیل ناموفق بود: ${esc(e.message)}</div>`; }
}

async function marketView(title, lede, markets, extraTop = "") {
  view.innerHTML = `<h1>${title}</h1><p class="lede">${lede}</p>${extraTop}<div class="split"><div id="list" class="panel"><p class="loading">در حال بارگذاری…</p></div><div id="detail"></div></div>`;
  const all = (await Promise.all(markets.map(m => api(`/api/analyses?market=${m}`)))).flat();
  const list = $("#list"), detail = $("#detail");
  list.innerHTML = symbolTable(all);
  bindPicks(list, id => loadDetail(id, detail));
  const first = all.find(r => r.id === state.selected) || all[0];
  if (first) { state.selected = first.id; list.querySelector(`tr[data-id="${first.id}"]`)?.setAttribute("aria-selected", "true"); loadDetail(first.id, detail); }
  else detail.innerHTML = "";
}

/* ---------------------------------------------------------------- views --- */
const views = {
  async overview() {
    const o = state.overview;
    const k = o.kpis;
    view.innerHTML = `<h1>نمای کلی بازارها</h1>
      <p class="lede">بازارها به ترتیب اولویت: Forex، NASDAQ، NYSE، رمزارز، TSX، TSXV. آخرین پویش: ${o.scan_run ? `<span class="ltr">${esc(when(o.scan_run.started_utc))}</span>` : "هنوز انجام نشده"}.</p>
      <div class="kpis">
        <div class="kpi"><div class="v">${k.open_signals}</div><div class="k">سیگنال باز فرضی</div></div>
        <div class="kpi"><div class="v">${k.analyses}</div><div class="k">نماد تحلیل‌شده</div></div>
        <div class="kpi"><div class="v">${k.evaluated}</div><div class="k">سیگنال ارزیابی‌شده</div></div>
        <div class="kpi"><div class="v">${k.win_rate == null ? "—" : pct(k.win_rate, 0, false)}</div><div class="k">Win Rate ${k.evaluated && k.evaluated < 30 ? "(نمونه کم)" : ""}</div></div>
        <div class="kpi"><div class="v">${k.total_risk_pct == null ? "—" : num(k.total_risk_pct, 1) + "%"}</div><div class="k">ریسک باز از پرتفوی</div></div>
      </div>
      <div class="cols" style="margin-top:18px">
        <div><h2>فرصت‌های برتر آخرین پویش</h2><p class="fine">نتیجه پویش است، نه سیگنال نهایی؛ نامزدها باید از تحلیل عمیق و کنترل ریسک عبور کنند.</p>
          <div class="panel">${o.top.length ? `<div class="table-wrap"><table><thead><tr><th>نماد</th><th>بازار</th><th class="n">امتیاز</th><th class="n">جذابیت</th><th>نشانه‌ها</th></tr></thead><tbody>
          ${o.top.map(t => `<tr><td><b>${esc(t.symbol)}</b></td><td>${esc(MARKET_FA[t.market])}</td><td class="n">${signed(t.score)}</td><td class="n">${num(t.interest)}</td><td class="flags">${t.flags.map(esc).join("، ")}</td></tr>`).join("")}</tbody></table></div>` : empty("هنوز پویشی انجام نشده است. «پویش بازارها» را بزنید.")}</div></div>
        <div><h2>هشدارهای ریسک</h2>${o.alerts.length ? o.alerts.map(a => `<div class="alert">${esc(a)}</div>`).join("") : `<div class="panel fine">هشدار فعالی وجود ندارد.</div>`}
          ${o.last_errors.length ? `<h3>خطاهای آخرین اجرا</h3>${o.last_errors.map(x => `<div class="alert err">${esc(x)}</div>`).join("")}` : ""}
          <h2>آخرین گزارش‌ها</h2><div class="panel">${o.reports.length ? o.reports.map(r => `<div><a href="${esc(r.html)}" target="_blank" rel="noopener">${r.kind === "daily" ? "گزارش روزانه" : "گزارش تحلیل"} — <span class="ltr">${esc(when(r.created_utc))}</span></a>${r.pdf ? ` · <a href="${esc(r.pdf)}" target="_blank" rel="noopener">PDF</a>` : ""}</div>`).join("") : '<p class="fine">گزارشی تولید نشده است.</p>'}</div>
        </div></div>`;
  },
  forex() {
    return marketView("ترمینال فارکس", "جفت‌ارزها با اولویت اول. داده Forex حجم متمرکز ندارد، پس VWAP و تحلیل حجم برای آن محاسبه نمی‌شود. سشن‌ها در نوار بالای صفحه هستند.", ["forex"]);
  },
  async stocks() {
    const tabs = ["nasdaq", "nyse", "tsx", "tsxv"];
    const bar = `<div class="tabs" role="group" aria-label="بورس">${tabs.map(t => `<button type="button" data-tab="${t}" aria-pressed="${state.stockTab === t}">${MARKET_FA[t]}</button>`).join("")}</div>`;
    await marketView("بازار سهام", "NASDAQ، NYSE، TSX و TSXV با تحلیل تکنیکال و بنیادی. ارقام بنیادی از خلاصه فعلی Yahoo است و point-in-time نیست.", [state.stockTab], bar);
    view.querySelectorAll("[data-tab]").forEach(b => b.addEventListener("click", () => { state.stockTab = b.dataset.tab; state.selected = null; views.stocks(); }));
  },
  crypto() {
    return marketView("ترمینال رمزارز", "ابتدا BTC و ETH، سپس رمزارزهای نقدشونده منتخب. بازار ۲۴ ساعته است و نوسان بالاتری دارد.", ["crypto"]);
  },
  ai() {
    return marketView("مرکز هوش مصنوعی", "نظر مستقل هر عامل، مناظره صعودی و نزولی، تصمیم نهایی، میزان اطمینان و منابع. تصمیم‌ها قاعده‌محور و مبتنی بر شواهدند؛ مدل زبانی فقط متن را بازنویسی می‌کند.", ["forex", "nasdaq", "nyse", "crypto", "tsx", "tsxv", "other"]);
  },
  async risk() {
    const r = await api("/api/risk");
    const ex = r.exposure;
    const cur = Object.entries(ex.currency_net || {});
    const max = Math.max(1, ...cur.map(([, v]) => Math.abs(v)));
    view.innerHTML = `<h1>مدیریت ریسک</h1><p class="lede">پرتفوی فرضی ${num(r.portfolio_value, 0)} ${esc(r.account_currency)}، ریسک هر معامله ${r.risk_pct}%، حداقل R:R ${r.min_rr}، سقف ${r.max_open} سیگنال باز. همه‌چیز شبیه‌سازی است.</p>
      <div class="kpis"><div class="kpi"><div class="v">${ex.open_count}</div><div class="k">سیگنال باز</div></div>
        <div class="kpi"><div class="v">${num(ex.total_risk_pct, 2)}%</div><div class="k">ریسک باز مجموع</div></div>
        <div class="kpi"><div class="v">${num(ex.gross_leverage)}×</div><div class="k">اهرم ناخالص</div></div>
        <div class="kpi"><div class="v">${ex.long_short.long || 0} / ${ex.long_short.short || 0}</div><div class="k">خرید / فروش</div></div></div>
      ${ex.warnings.map(w => `<div class="alert">${esc(w)}</div>`).join("")}
      <div class="cols" style="margin-top:16px"><div><h2>سیگنال‌های باز</h2><div class="panel">${r.open.length ? `<div class="table-wrap"><table><thead><tr><th>نماد</th><th>سیگنال</th><th class="n">مبنا</th><th class="n">حد ضرر</th><th class="n">اندازه</th><th class="n">ریسک</th></tr></thead><tbody>
        ${r.open.map(s => { const z = s.sizing_json || {}; return `<tr><td><b>${esc(s.symbol)}</b><div class="fine">${esc(MARKET_FA[s.market])}</div></td><td>${pill(s.label)}</td><td class="n">${price(s.ref_price, s.market)}</td><td class="n">${price(s.stop, s.market)}</td><td class="n">${z.lots != null ? num(z.lots) + " lot" : num(z.units, 2)}</td><td class="n">${num(z.risk_amount, 0)}</td></tr>`; }).join("")}</tbody></table></div>` : empty("سیگنال باز فرضی وجود ندارد.")}</div></div>
      <div><h2>مواجهه خالص ارزی (Forex)</h2><div class="panel">${cur.length ? cur.map(([c, v]) => `<div class="stance"><span><b>${esc(c)}</b><div class="fine">${v >= 0 ? "خرید خالص" : "فروش خالص"}</div></span>
        <span class="bar"><span class="zero"></span><i style="${v >= 0 ? `left:50%;width:${Math.abs(v) / max * 50}%;background:var(--pos)` : `left:${50 - Math.abs(v) / max * 50}%;width:${Math.abs(v) / max * 50}%;background:var(--neg)`}"></i></span><span class="ltr fine">${num(v, 0)}</span></div>`).join("") : empty("مواجهه ارزی باز وجود ندارد.")}</div>
        <h2>به تفکیک بازار</h2><div class="panel">${Object.keys(ex.by_market).length ? `<table><thead><tr><th>بازار</th><th class="n">تعداد</th><th class="n">ارزش اسمی</th><th class="n">ریسک</th></tr></thead><tbody>${Object.entries(ex.by_market).map(([m, v]) => `<tr><td>${esc(MARKET_FA[m])}</td><td class="n">${v.count}</td><td class="n">${num(v.notional, 0)}</td><td class="n">${num(v.risk, 0)}</td></tr>`).join("")}</tbody></table>` : '<p class="fine">—</p>'}</div></div></div>`;
  },
  async performance() {
    const p = await api(`/api/performance?mode=${state.perfMode}`);
    const m = p.metrics;
    const tabs = `<div class="tabs" role="group" aria-label="نوع عملکرد"><button type="button" data-mode="live" aria-pressed="${state.perfMode === "live"}">سیگنال‌های زنده</button><button type="button" data-mode="backtest" aria-pressed="${state.perfMode === "backtest"}">بک‌تست (جدا)</button></div>`;
    const note = state.perfMode === "backtest" ? "بک‌تست فقط تکنیکال است، روی فهرست امروز نمادها (سوگیری بقا) و جدا از عملکرد زنده نگه داشته می‌شود." :
      "سیگنال‌های زنده پس از پایان افق، با ورود در اولین قیمت باز بعد از صدور، هزینه و لغزش ارزیابی می‌شوند.";
    view.innerHTML = `<h1>عملکرد تاریخی</h1>${tabs}<p class="lede">${note}</p>${!m.n ? empty("هنوز هیچ سیگنالی ارزیابی نشده است.") : `
      ${m.n < 30 ? `<div class="alert">نمونه آماری کم است (n=${m.n})؛ این ارقام قابل اتکا نیستند.</div>` : ""}
      <div class="kpis"><div class="kpi"><div class="v">${m.n}</div><div class="k">تعداد · ${p.period ? esc(p.period.join(" تا ")) : ""}</div></div>
      <div class="kpi"><div class="v">${pct(m.win_rate, 0, false)}</div><div class="k">Win Rate</div></div>
      <div class="kpi"><div class="v">${m.profit_factor == null ? "—" : num(m.profit_factor)}</div><div class="k">Profit Factor</div></div>
      <div class="kpi"><div class="v">${pct(m.avg_return, 2)}</div><div class="k">میانگین بازده خالص</div></div>
      <div class="kpi"><div class="v">${m.sharpe_per_trade == null ? "—" : num(m.sharpe_per_trade)}</div><div class="k">Sharpe (هر معامله)</div></div>
      <div class="kpi"><div class="v">${m.sortino_per_trade == null ? "—" : num(m.sortino_per_trade)}</div><div class="k">Sortino (هر معامله)</div></div>
      <div class="kpi"><div class="v">${pct(m.max_drawdown, 1, false)}</div><div class="k">Max Drawdown</div></div></div>
      <h2>منحنی سرمایه فرضی (ریسک ثابت هر معامله)</h2><div class="panel" id="eq"></div>
      <h2>به تفکیک بازار</h2><div class="panel"><table><thead><tr><th>بازار</th><th class="n">تعداد</th><th class="n">Win Rate</th><th class="n">میانگین بازده</th><th class="n">Max DD</th></tr></thead><tbody>
      ${Object.entries(p.by_market).map(([k, v]) => `<tr><td>${esc(MARKET_FA[k] || k)}</td><td class="n">${v.n}</td><td class="n">${pct(v.win_rate, 0, false)}</td><td class="n">${pct(v.avg_return, 2)}</td><td class="n">${pct(v.max_drawdown, 1, false)}</td></tr>`).join("")}</tbody></table></div>
      <h2>به تفکیک نوع سیگنال</h2><div class="panel"><table><thead><tr><th>سیگنال</th><th class="n">تعداد</th><th class="n">Win Rate</th><th class="n">میانگین بازده</th></tr></thead><tbody>
      ${Object.entries(p.by_label).map(([k, v]) => `<tr><td>${pill(k)}</td><td class="n">${v.n}</td><td class="n">${pct(v.win_rate, 0, false)}</td><td class="n">${pct(v.avg_return, 2)}</td></tr>`).join("")}</tbody></table></div>`}
      <h2>سیگنال‌ها</h2><div class="panel">${p.signals.length ? `<div class="table-wrap"><table><thead><tr><th>نماد</th><th>سیگنال</th><th>صدور</th><th>وضعیت</th><th class="n">بازده خالص</th><th class="n">R</th></tr></thead><tbody>
      ${p.signals.slice(0, 80).map(s => `<tr><td><b>${esc(s.symbol)}</b></td><td>${pill(s.label)}</td><td class="fine"><span class="ltr">${esc(when(s.issued_utc))}</span></td><td>${s.status === "open" ? "باز" : esc(s.exit_reason || "بسته")}</td><td class="n">${s.net_return == null ? "—" : pct(s.net_return, 2)}</td><td class="n">${s.r_multiple == null ? "—" : num(s.r_multiple)}</td></tr>`).join("")}</tbody></table></div>` : empty("سیگنالی ثبت نشده است.")}</div>`;
    view.querySelectorAll("[data-mode]").forEach(b => b.addEventListener("click", () => { state.perfMode = b.dataset.mode; views.performance(); }));
    const eq = $("#eq");
    if (eq && m.equity_curve) {
      const color = getComputedStyle(document.documentElement).getPropertyValue("--s1").trim();
      lineChart(eq, { dates: m.equity_curve.map((_, i) => `معامله ${i + 1}`), height: 220, guides: [1], yFormat: v => num(v, 3),
        series: [{ name: "سرمایه نسبی", values: m.equity_curve, color }] });
    }
  },
  async reports() {
    const rows = await api("/api/reports");
    view.innerHTML = `<h1>گزارش‌های روزانه</h1><p class="lede">بایگانی گزارش‌های فارسی (HTML و PDF). گزارش‌های قبلی هرگز بازنویسی نمی‌شوند.</p>
      <div class="panel">${rows.length ? `<table><thead><tr><th>نوع</th><th>زمان</th><th>فایل‌ها</th></tr></thead><tbody>${rows.map(r => `<tr><td>${r.kind === "daily" ? "گزارش روزانه" : "گزارش تحلیل"}</td><td><span class="ltr">${esc(when(r.created_utc))}</span></td>
      <td>${r.html ? `<a href="${esc(r.html)}" target="_blank" rel="noopener">HTML</a>` : "—"}${r.pdf ? ` · <a href="${esc(r.pdf)}" target="_blank" rel="noopener">PDF</a>` : ""}</td></tr>`).join("")}</tbody></table>` : empty("هنوز گزارشی ساخته نشده است. اجرای روزانه یا یک تحلیل را شروع کنید.")}</div>`;
  },
};

/* --------------------------------------------------------------- router --- */
async function route() {
  const name = (location.hash.replace(/^#\//, "") || "overview").split("/")[0];
  const fn = views[name] || views.overview;
  document.querySelectorAll(".rail a").forEach(a => { if (a.dataset.route !== name) a.removeAttribute("aria-current"); else a.setAttribute("aria-current", "page"); });
  try {
    state.overview = await api("/api/overview");
    state.tz = state.overview.ribbon.timezone;
    renderRibbon(state.overview.ribbon);
    renderMarkets(state.overview.markets);
    await fn();
  } catch (e) {
    view.innerHTML = `<div class="alert err">ارتباط با سرور داشبورد برقرار نشد (${esc(e.message)}). مطمئن شوید دستور serve در حال اجراست.</div>`;
  }
}
addEventListener("hashchange", () => { state.selected = state.pendingSelect || null; state.pendingSelect = null; route(); });

/* ----------------------------------------------------------------- jobs --- */
async function startJob(kind, body, after) {
  const job = $("#job");
  const buttons = document.querySelectorAll(".analyze button");
  buttons.forEach(b => b.disabled = true);
  job.textContent = kind === "analyze" ? "در حال تحلیل… (ممکن است چند دقیقه طول بکشد)" : "در حال پویش بازارها…";
  try {
    const started = await post(`/api/${kind}`, body);
    if (started.error) { job.innerHTML = `<span class="err">${esc(started.error)}</span>`; return; }
    for (;;) {
      await new Promise(r => setTimeout(r, 2500));
      const s = await api(`/api/jobs/${started.id}`);
      if (s.status === "running") continue;
      if (s.status === "done") {
        const labels = s.result.labels ? Object.entries(s.result.labels).map(([k, v]) => `${k}: ${LABEL_FA[v] || v}`).join("، ") : `تحلیل عمیق: ${(s.result.deep || []).join("، ") || "هیچ"}`;
        job.textContent = `انجام شد — ${labels}`;
        if (after) { await after(); return; }
      } else job.innerHTML = `<span class="err">ناموفق: ${esc(s.error)}</span>`;
      break;
    }
    route();
  } catch (e) { job.innerHTML = `<span class="err">${esc(e.message)}</span>`; }
  finally { buttons.forEach(b => b.disabled = false); }
}
$("#analyze-form").addEventListener("submit", e => {
  e.preventDefault();
  const symbols = $("#symbols").value.split(/[,\s]+/).map(s => s.trim()).filter(Boolean);
  if (!symbols.length) { $("#job").innerHTML = '<span class="err">حداقل یک نماد وارد کنید، مثلاً EURUSD</span>'; return; }
  startJob("analyze", { symbols });
});
$("#scan-btn").addEventListener("click", () => startJob("scan", {}));
// Gold: analysed as XAU/USD in the forex section, then shown there with its analysis selected.
$("#gold-btn").addEventListener("click", () => startJob("analyze", { symbols: ["XAUUSD"], market: "forex" }, async () => {
  const rows = await api("/api/analyses?market=forex");
  const gold = rows.find(r => r.symbol === "XAUUSD");
  if (location.hash === "#/forex") { if (gold) state.selected = gold.id; route(); }
  else { state.pendingSelect = gold ? gold.id : null; location.hash = "#/forex"; }
}));

route();
setInterval(() => { if (state.overview && !document.hidden) api("/api/overview").then(o => { state.overview = o; renderRibbon(o.ribbon); renderMarkets(o.markets); }).catch(() => {}); }, 60000);
