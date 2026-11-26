/* FightModel dashboard: statische single-page app (GitHub Pages).
   Data: data/site.json + data/backtest.json (gegenereerd door src/export/site_data.py). */
"use strict";

let D = null, BT = null;
const $ = s => document.querySelector(s);
const page = () => $("#page");

/* ------------------------------------------------------------ instellingen (per browser) */
const DEF = { bankroll: 1000, kelly: 0.25, edge: 0.03, maxBet: 0.02, maxEvent: 0.06, oddsFmt: "dec",
              tz: "Europe/Amsterdam", books: ["Unibet", "Bet365", "TOTO", "Holland Casino"] };
function loadJSON(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } }
function saveJSON(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} }
let S = { ...DEF, ...loadJSON("fm_settings", {}) };
let LOCAL_BETS = loadJSON("fm_bets", []);

/* ------------------------------------------------------------ helpers */
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (v, d = 1) => v == null || isNaN(v) ? "–" : (v * 100).toFixed(d).replace(".", ",") + "%";
const spct = (v, d = 1) => v == null || isNaN(v) ? "–" : (v > 0 ? "+" : "") + pct(v, d);
const num = (v, d = 2) => v == null || isNaN(v) ? "–" : Number(v).toFixed(d).replace(".", ",");
const eur = v => v == null || isNaN(v) ? "–" : "€" + Math.round(v).toLocaleString("nl-NL");
const seur = v => v == null || isNaN(v) ? "–" : (v >= 0 ? "+" : "−") + "€" + Math.abs(Math.round(v)).toLocaleString("nl-NL");
const amToDec = o => o == null ? null : (o > 0 ? 1 + o / 100 : 1 + 100 / Math.abs(o));
const fmtOdds = o => o == null ? "–" : S.oddsFmt === "am" ? (o > 0 ? "+" + o : String(o)) : num(amToDec(o), 2);
const oddsTitle = o => o == null ? "" : `title="${o > 0 ? "+" + o : o} (Amerikaans) · ${num(amToDec(o), 2)} (decimaal)"`;
const MONTHS = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"];
const fdate = s => { if (!s) return "–"; const d = new Date(s + (s.length === 10 ? "T12:00:00" : "")); return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`; };
const fdateShort = s => { if (!s) return "–"; const d = new Date(s + "T12:00:00"); return `${d.getDate()} ${MONTHS[d.getMonth()]} '${String(d.getFullYear()).slice(2)}`; };
const initials = n => String(n || "?").split(/\s+/).filter(Boolean).map(w => w[0]).slice(0, 2).join("").toUpperCase();
const last = n => String(n || "").split(" ").slice(-1)[0];
const cm = v => v ? Math.round(v) + " cm" : "–";
const fairP = (oa, ob) => { const a = 1 / amToDec(oa), b = 1 / amToDec(ob); return a / (a + b); };
const allFights = () => D.events.filter(e => !e.none).flatMap(e => e.fights.map(f => ({ ...f, event: e })));

/* advies opnieuw berekenen met de instellingen van deze bezoeker */
function advice(f) {
  if (f.card === "onbevestigd" || f.p_final == null) return { status: "unconfirmed" };
  if (f.locked) {   // vastgezet: het advies van dat moment, niet herberekenen
    const lb = f.locked_bet;
    if (lb) return { status: "bet", locked: true, edge: f.edge, pick: lb.pick, dec: lb.odds, stake: lb.stake, sideA: lb.pick === f.a.name, book: "Unibet" };
    return { status: f.odds_a == null ? "wait" : "none", locked: true, edge: f.edge };
  }
  if (f.odds_a == null || f.odds_b == null) return { status: "wait" };
  const mkt = fairP(f.odds_a, f.odds_b), p = f.p_final;
  const ea = p - mkt, eb = (1 - p) - (1 - mkt);
  const sideA = ea >= eb, edge = sideA ? ea : eb;
  const pm = (f.odds_info || {}).kind === "prediction market";
  const bo = betOdds(f), book = (f.odds_info || {}).bet_book || "Unibet";
  const pp = sideA ? p : 1 - p;
  if (!pm && !bo) return { status: "nobook", edge, sideA, mkt, book };
  const dec = bo ? amToDec(sideA ? bo[0] : bo[1]) : amToDec(sideA ? f.odds_a : f.odds_b);
  const ev = pp * dec - 1;
  if (edge < S.edge || pm || ev <= 0) return { status: "none", edge, sideA, mkt, ev, dec, pm, pmValue: pm && edge >= S.edge, book };
  const k = ((dec - 1) * pp - (1 - pp)) / (dec - 1);
  const stake = Math.max(0, Math.min(k * S.kelly, S.maxBet)) * S.bankroll;
  return { status: "bet", edge, sideA, mkt, ev, dec, stake, book, pick: sideA ? f.a.name : f.b.name };
}
/* prijs waar je echt inzet (Unibet); null = die bookmaker heeft (nog) geen lijn */
function betOdds(f) {
  const oi = f.odds_info || {};
  if (oi.source && oi.source !== "BestFightOdds") return f.odds_a != null ? [f.odds_a, f.odds_b] : null;  // handmatige odds
  return oi.bet_odds || null;
}
/* odds per bookmaker + lijnbeweging */
function oddsDetail(f, A, B) {
  const oi = f.odds_info;
  if (!oi) return "";
  const src = `<div class="note">Bron: ${esc(oi.source)}${oi.captured_at ? " · gemeten " + esc(oi.captured_at.replace("T", " ")) + " UTC" : ""}${oi.n_books ? ` · mediaan van ${oi.n_books} ${oi.kind === "sportsbooks" ? "bookmaker(s)" : "prediction market"}` : ""}.${oi.kind !== "sportsbooks" ? " <b class=\"warn\">Alleen Polymarket: indicatief, geen virtuele inzet.</b>" : ""}</div>`;
  const books = Object.entries(oi.books || {});
  const PM = ["Polymarket", "Kalshi"], real = books.filter(([b]) => !PM.includes(b)), pool = real.length ? real : books;
  const best = i => Math.max(...pool.map(([, v]) => amToDec(v[i])));
  const tbl = books.length ? `<table style="margin-top:10px"><tr><th>Bookmaker</th><th class="num">${esc(last(A.name))}</th><th class="num">${esc(last(B.name))}</th></tr>${books.map(([b, v]) => `<tr><td>${esc(b)}${S.books.includes(b) ? ` <span class="tag" title="KSA-vergunning, staat in je instellingen">NL</span>` : ""}</td>${v.map((o, i) => `<td class="num ${amToDec(o) === best(i) && pool.some(([pb]) => pb === b) ? "up" : ""}" ${oddsTitle(o)}>${fmtOdds(o)}</td>`).join("")}</tr>`).join("")}</table>` : "";
  const h = oi.history || [];
  let mv = "";
  if (h.length > 1) {
    const t0 = Date.parse(h[0].captured_at);
    const pts = h.map(x => [(Date.parse(x.captured_at) - t0) / 36e5, fairP(x.odds_a, x.odds_b)]);
    mv = `<h3 style="margin-top:14px">Lijnbeweging (kans ${esc(last(A.name))}, zonder marge)</h3>` + lineChart({ series: [{ pts, color: "#d20a0a" }], h: 150, yfmt: v => pct(v, 0), ylab: 3 }) +
      `<div class="note">Opening ${fmtOdds(h[0].odds_a)} → nu ${fmtOdds(h[h.length - 1].odds_a)} over ${h.length} metingen.</div>`;
  } else mv = `<div class="note">Lijnbeweging verschijnt na de volgende odds-meting.</div>`;
  return src + tbl + mv;
}
function resultTag(f) {
  const r = f.result;
  if (r.outcome !== "win") return `<span class="tag">${esc(r.outcome)}</span>`;
  const right = f.p_final != null && (f.p_final > .5) === (r.y_a === 1);
  return `<span class="tag ${right ? "ok" : "flag"}" title="${esc(r.method || "")}${r.round ? " R" + r.round : ""}">${right ? "✓" : "✗"} ${esc(last(r.winner))}</span>`;
}
function adviceTag(f, a = advice(f)) {
  if (f.result) return resultTag(f) + (a.status === "bet" ? ` <span class="tag ${f.locked_bet?.result === "W" ? "bet" : ""}">${f.locked_bet?.result === "W" ? "+" : ""}${eur(f.locked_bet?.pnl ?? 0)}</span>` : "");
  if (a.status === "bet") return `<span class="tag bet" title="Prijs bij ${esc(a.book)}${a.locked ? " · vastgezet" : ""}">${a.locked ? "🔒 " : ""}BET ${esc(last(a.pick))} @ ${num(a.dec)}</span>`;
  if (a.status === "nobook") return `<span class="tag wait" title="Er zijn odds bij andere bookmakers, maar nog niet bij ${esc(a.book)}">${a.edge >= S.edge ? "Edge +" + pct(a.edge, 0) + ", wacht op " : "Wacht op "}${esc(a.book)}</span>`;
  if (a.status === "none" && a.pm) return `<span class="tag" title="Alleen Polymarket-odds: indicatief, geen virtuele inzet">${a.pmValue ? "Indicatief +" + pct(a.edge, 0) : "Indicatief"}</span>`;
  if (a.status === "none") return `<span class="tag">Geen value</span>`;
  if (a.status === "wait") return `<span class="tag wait">Wacht op odds</span>`;
  return `<span class="tag">Onbevestigd</span>`;
}
function eventStart(e) {
  const t = (e.times && (e.times.main_card || e.times.prelims)) || "19:00";
  const hm = (t.match(/(\d{1,2}):(\d{2})/) || [0, 19, 0]).slice(1).map(Number);
  const d = new Date(e.date + "T00:00:00+01:00");
  if (/zondag|zo /i.test(t)) d.setDate(d.getDate() + 1);
  d.setHours(d.getHours() + hm[0], hm[1]);
  return d;
}

/* ------------------------------------------------------------ SVG-grafieken */
function lineChart({ series, w = 640, h = 220, yfmt = v => v, ylab = 5, xfmt, pad = [46, 14, 26, 10], baseline }) {
  const pts = series.flatMap(s => s.pts);
  if (!pts.length) return `<div class="empty">Nog geen data</div>`;
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
  let x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  if (baseline != null) { y0 = Math.min(y0, baseline); y1 = Math.max(y1, baseline); }
  if (y0 === y1) { y0 -= 1; y1 += 1; }
  const yr = y1 - y0; y0 -= yr * .06; y1 += yr * .06; if (x0 === x1) x1 = x0 + 1;
  const [L, R, B, T] = pad, X = x => L + (x - x0) / (x1 - x0) * (w - L - R), Y = y => T + (1 - (y - y0) / (y1 - y0)) * (h - T - B);
  let g = "";
  for (let i = 0; i <= ylab; i++) { const v = y0 + (y1 - y0) * i / ylab, y = Y(v); g += `<line x1="${L}" x2="${w - R}" y1="${y}" y2="${y}" stroke="#22262e"/><text x="${L - 6}" y="${y + 4}" text-anchor="end" font-size="11" fill="#8a919c">${yfmt(v)}</text>`; }
  if (baseline != null) g += `<line x1="${L}" x2="${w - R}" y1="${Y(baseline)}" y2="${Y(baseline)}" stroke="#555" stroke-dasharray="4 4"/>`;
  if (xfmt) { const n = 6; for (let i = 0; i <= n; i++) { const v = x0 + (x1 - x0) * i / n; g += `<text x="${X(v)}" y="${h - 6}" text-anchor="middle" font-size="11" fill="#8a919c">${xfmt(v)}</text>`; } }
  for (const s of series) {
    if (!s.pts.length) continue;
    const d = s.pts.map((p, i) => (i ? "L" : "M") + X(p[0]).toFixed(1) + "," + Y(p[1]).toFixed(1)).join("");
    if (s.area) g += `<path d="${d}L${X(s.pts.at(-1)[0])},${h - B}L${X(s.pts[0][0])},${h - B}Z" fill="${s.color}" opacity=".13"/>`;
    g += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="${s.width || 2.2}" ${s.dash ? `stroke-dasharray="${s.dash}"` : ""}/>`;
    if (s.dots) for (const p of s.pts) g += `<circle cx="${X(p[0])}" cy="${Y(p[1])}" r="${p[2]?.r || 3.5}" fill="${p[2]?.c || s.color}"><title>${esc(p[2]?.t || "")}</title></circle>`;
  }
  return `<svg viewBox="0 0 ${w} ${h}" width="100%" role="img">${g}</svg>`;
}
function barChart(items, { w = 420, h = 200, yfmt = v => v, zero = 0 } = {}) {
  if (!items.length) return `<div class="empty">Nog geen data</div>`;
  const L = 40, B = 24, T = 18, vals = items.map(i => i.value);
  let y0 = Math.min(zero, ...vals), y1 = Math.max(zero, ...vals); if (y0 === y1) y1 = y0 + 1;
  const Y = v => T + (1 - (v - y0) / (y1 - y0)) * (h - T - B), bw = (w - L - 10) / items.length;
  let g = `<line x1="${L}" x2="${w}" y1="${Y(zero)}" y2="${Y(zero)}" stroke="#444"/>`;
  items.forEach((it, i) => {
    const x = L + i * bw + bw * .18, y = Math.min(Y(it.value), Y(zero)), hh = Math.abs(Y(it.value) - Y(zero));
    g += `<rect x="${x}" y="${y}" width="${bw * .64}" height="${Math.max(hh, 1)}" rx="3" fill="${it.color || (it.value >= 0 ? "#22c55e" : "#d20a0a")}"><title>${esc(it.label)}: ${yfmt(it.value)}</title></rect>`;
    g += `<text x="${x + bw * .32}" y="${it.value >= 0 ? y - 5 : y + hh + 13}" text-anchor="middle" font-size="11" font-weight="700" fill="#e5e7eb">${yfmt(it.value)}</text>`;
    g += `<text x="${x + bw * .32}" y="${h - 6}" text-anchor="middle" font-size="11" fill="#8a919c">${esc(it.label)}</text>`;
  });
  return `<svg viewBox="0 0 ${w} ${h}" width="100%">${g}</svg>`;
}
function hbars(items, fmt = v => pct(v, 0)) {
  const mx = Math.max(...items.map(i => Math.abs(i.value)), 1e-9);
  return items.map(i => `<div style="display:grid;grid-template-columns:1fr 1.2fr 46px;gap:10px;align-items:center;margin:7px 0;font-size:13px">
    <span>${esc(i.label)}</span><div style="height:8px;background:var(--panel2);border-radius:4px"><div style="height:8px;width:${Math.abs(i.value) / mx * 100}%;background:${i.color || "var(--red)"};border-radius:4px"></div></div>
    <span class="num">${fmt(i.value)}</span></div>`).join("");
}
function calibChart(points, w = 360, h = 280) {
  const L = 40, B = 34, T = 10, R = 10, X = v => L + v * (w - L - R), Y = v => T + (1 - v) * (h - T - B);
  let g = `<line x1="${X(0)}" y1="${Y(0)}" x2="${X(1)}" y2="${Y(1)}" stroke="#666" stroke-dasharray="4 4"/>`;
  for (let i = 0; i <= 5; i++) { const v = i / 5; g += `<text x="${X(v)}" y="${h - 18}" text-anchor="middle" font-size="10" fill="#8a919c">${v.toFixed(1)}</text><text x="${L - 6}" y="${Y(v) + 3}" text-anchor="end" font-size="10" fill="#8a919c">${v.toFixed(1)}</text><line x1="${L}" x2="${w - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="#1d2027"/>`; }
  const P = points.filter(p => p.n >= 10);
  g += `<path d="${P.map((p, i) => (i ? "L" : "M") + X(p.predicted) + "," + Y(p.actual)).join("")}" fill="none" stroke="#4c86ff" stroke-width="2"/>`;
  const mx = Math.max(...P.map(p => p.n));
  for (const p of P) g += `<circle cx="${X(p.predicted)}" cy="${Y(p.actual)}" r="${3 + 6 * Math.sqrt(p.n / mx)}" fill="#4c86ff" fill-opacity=".85"><title>voorspeld ${pct(p.predicted)} · werkelijk ${pct(p.actual)} · n=${p.n}</title></circle>`;
  g += `<text x="${(L + w) / 2}" y="${h - 2}" text-anchor="middle" font-size="11" fill="#8a919c">Voorspelde kans</text>`;
  g += `<text transform="translate(11,${(T + h - B) / 2}) rotate(-90)" text-anchor="middle" font-size="11" fill="#8a919c">Werkelijke winst%</text>`;
  return `<svg viewBox="0 0 ${w} ${h}" width="100%">${g}</svg>`;
}
function radar(axes, a, b, w = 300, h = 260) {
  const cx = w / 2, cy = h / 2 + 6, r = Math.min(w, h) / 2 - 38, n = axes.length;
  const P = (i, v) => [cx + Math.sin(2 * Math.PI * i / n) * r * v, cy - Math.cos(2 * Math.PI * i / n) * r * v];
  let g = "";
  for (const k of [.25, .5, .75, 1]) g += `<polygon points="${axes.map((_, i) => P(i, k).join(",")).join(" ")}" fill="none" stroke="#2a2e36"/>`;
  axes.forEach((ax, i) => { const [x, y] = P(i, 1.18); g += `<line x1="${cx}" y1="${cy}" x2="${P(i, 1)[0]}" y2="${P(i, 1)[1]}" stroke="#2a2e36"/><text x="${x}" y="${y + 4}" text-anchor="middle" font-size="11" fill="#a3a9b3">${esc(ax)}</text>`; });
  const poly = (vals, c, op) => `<polygon points="${vals.map((v, i) => P(i, Math.max(0, Math.min(1, v ?? 0))).join(",")).join(" ")}" fill="${c}" fill-opacity="${op}" stroke="${c}" stroke-width="2"/>`;
  if (b) g += poly(b, "#8a919c", .12);
  g += poly(a, "#d20a0a", .35);
  return `<svg viewBox="0 0 ${w} ${h}" width="100%">${g}</svg>`;
}
const sparkDots = arr => (arr || []).map(r => `<span class="dot ${r}">${r === "W" ? "W" : r === "L" ? "L" : "–"}</span>`).join("");

/* ------------------------------------------------------------ navigatie */
const ICONS = {
  overzicht: "M3 3h7v7H3zM14 3h7v4h-7zM14 10h7v11h-7zM3 13h7v8H3z",
  events: "M4 5h16v15H4zM4 9h16M8 3v4M16 3v4",
  fightcard: "M4 4h16v4H4zM4 10h16v4H4zM4 16h16v4H4z",
  matchup: "M5 19 19 5M5 5l4 4M15 15l4 4M14 5h5v5M10 19H5v-5",
  vechters: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
  bets: "M5 3h14v18l-3-2-2 2-2-2-2 2-2-2-3 2zM9 8h6M9 12h6",
  prestaties: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  backtest: "M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5M12 7v5l3 3",
  nieuws: "M4 5h13v14H5a1 1 0 0 1-1-1zM17 9h3v9a1 1 0 0 1-2 0M8 9h5M8 13h5",
  data: "M12 3c4.4 0 8 1.3 8 3s-3.6 3-8 3-8-1.3-8-3 3.6-3 8-3zM4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6",
  instellingen: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-2.7-1.1l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.6 1.6 0 0 0 3.6 15H3a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.1-2.7l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.6 1.6 0 0 0 9.6 4.6V4a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 2.7 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0 1.1 2.7H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z",
};
const NAV = [["overzicht", "Overzicht"], ["events", "Events"], ["fightcard", "Fight card"], ["matchup", "Matchup"], ["vechters", "Vechters"],
  ["bets", "Bet-log"], ["prestaties", "Prestaties (backtest)"], ["backtest", "Backtest"], ["nieuws", "Nieuws & kamp"], ["data", "Data-status"], ["instellingen", "Instellingen"]];
function renderNav(active) {
  $("#nav").innerHTML = NAV.map(([k, l]) => `<a href="#/${k}" class="${k === active ? "on" : ""}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="${ICONS[k]}"/></svg>${l}</a>`).join("");
}
const nextEvent = () => D.events.filter(e => !e.none).sort((a, b) => a.date.localeCompare(b.date)).find(e => eventStart(e) > new Date()) || D.events.filter(e => !e.none)[0];
const findFight = id => allFights().find(f => f.id === id);
const ph = (title, { back, sub, right } = {}) => `<div class="ph">${back ? `<a class="back" href="${back}" aria-label="Terug">←</a>` : ""}<h1>${title}</h1>${right || ""}${sub ? `<div class="sub">${sub}</div>` : ""}</div>`;
const disclaimer = `<div class="disclaimer">Persoonlijk onderzoeksproject. Er wordt niet met echt geld gewed: alle inzetten zijn virtueel (paper trading). Geen gokadvies en geen voorspelling van zekerheid. Niet gelieerd aan de UFC of andere organisaties. Wedden in Nederland alleen bij aanbieders met een vergunning van de Kansspelautoriteit, 18+. Hulp nodig? <a href="https://www.loketkansspel.nl" target="_blank" rel="noopener">loketkansspel.nl</a>. Data: Kaggle (neelagiriaditya, CC0; mdabbert, CC BY 4.0), ufcalendar.com.</div>`;

/* ------------------------------------------------------------ 1. overzicht */
function settledBets() { return LOCAL_BETS.filter(b => b.result === "W" || b.result === "L"); }
function betPnl(b) { return b.result === "W" ? b.stake * (b.odds - 1) : b.result === "L" ? -b.stake : 0; }
/* mijn advies per event: live picks uit advice() + handgeschreven toelichting (data/advies/advies.json) */
function adviesCard(e) {
  const A = (D.advies || {})[e.id], fs = e.fights.filter(f => f.card !== "onbevestigd");
  const adv = fs.map(f => ({ f, a: advice(f) }));
  const bets = adv.filter(x => x.a.status === "bet");
  const near = adv.filter(x => x.a.status !== "bet" && x.a.edge >= .02);
  const wait = adv.filter(x => x.a.status === "wait" || x.a.status === "nobook");
  const pass = fs.length - bets.length - near.length - wait.length;
  const nm = x => esc(x.a.sideA ? x.f.a.name : x.f.b.name);
  return `<div class="card" style="margin-bottom:14px;border-left:4px solid var(--red2)">
    <h3>Mijn advies voor ${esc(e.name.split(":")[0])}${A ? ` <span class="mut" style="font-weight:400;font-size:12px">· toelichting ${esc(A.geschreven.replace("T", " "))}</span>` : ""}</h3>
    ${A ? `<div style="font:700 17px var(--head);margin:4px 0 12px">${esc(A.kort)}</div>` : ""}
    <div class="grid g2">
      <div>
        <div class="srow"><b>Inzetten (${bets.length})</b><span class="mut">nu, Unibet</span></div>
        ${bets.length ? bets.map(x => `<div class="srow cl" data-href="#/matchup/${x.f.id}"><span>✅ <b>${esc(x.a.pick)}</b> <span class="mut">@ ${num(x.a.dec)} · edge ${spct(x.a.edge)}</span></span><b>${eur(x.a.stake)}</b></div>`).join("") : `<div class="srow"><span class="mut">Niets: geen gevecht met genoeg voordeel.</span></div>`}
        <div class="srow" style="margin-top:8px"><b>Net niet (${near.length})</b><span class="mut">edge ≥ 2%, geen value</span></div>
        ${near.map(x => `<div class="srow cl" data-href="#/matchup/${x.f.id}"><span>👀 ${nm(x)} <span class="mut">edge ${spct(x.a.edge)}${x.a.ev != null ? " · rendement " + spct(x.a.ev) : ""}</span></span></div>`).join("") || `<div class="srow"><span class="mut">–</span></div>`}
        <div class="srow" style="margin-top:8px"><span>⏸ Wacht op odds: ${wait.length ? wait.map(x => esc(last(x.f.a.name)) + " vs " + esc(last(x.f.b.name))).join(", ") : "geen"}</span></div>
        <div class="srow"><span>✋ Passen: <b>${pass}</b> gevechten (model ≈ markt)</span></div>
      </div>
      <div>${A ? `<ul style="margin:0;padding-left:18px;line-height:1.5">${A.uitleg.map(t => `<li style="margin-bottom:6px">${esc(t)}</li>`).join("")}</ul>` : `<div class="empty">Nog geen toelichting voor dit event.</div>`}</div>
    </div>
    <div class="note">${A ? esc(A.regel) + " " : ""}De lijst links rekent live mee met de nieuwste odds (2× per dag); de toelichting rechts is van het genoemde moment.</div>
  </div>`;
}
function pageOverzicht() {
  const PP = D.paper || {}, MB = D.bets || [];
  const sb = MB.filter(b => ["W", "L", "push"].includes(b.result)), pnl = PP.pnl || 0, staked = PP.staked || 0;
  const ev = nextEvent(), fights = ev.fights.filter(f => f.card !== "onbevestigd");
  const vb = allFights().map(f => ({ f, a: advice(f) })).filter(x => x.a.status === "bet");
  const nOdds = fights.filter(f => f.odds_a != null).length;
  const flags = fights.reduce((s, f) => s + (f.flags || []).filter(x => x.type !== "data").length, 0);
  const curve = modelCurve();
  const warn = [
    ...D.status.sources.filter(s => s.status !== "ok").map(s => ({ t: `${s.name}: ${s.note}`, lvl: s.status === "fout" ? "down" : "warn" })),
  ];
  return ph("Overzicht") + `
  <div class="kpis">
    <div class="kpi"><div class="l">Bankroll (virtueel)</div><div class="v">${eur(D.meta.bankroll + pnl)}</div><div class="s ${pnl >= 0 ? "up" : "down"}">${sb.length ? spct(pnl / D.meta.bankroll) : "start 5 dec"}</div></div>
    <div class="kpi"><div class="l">Model-bets</div><div class="v">${MB.length}</div><div class="s">${MB.length ? sb.length + " afgerekend" : "vastgezet op de vechtdag"}</div></div>
    <div class="kpi"><div class="l">ROI</div><div class="v ${staked ? (pnl >= 0 ? "up" : "down") : ""}">${staked ? spct(PP.roi) : "–"}</div><div class="s">${staked ? "over " + eur(staked) + " inzet" : "nog geen uitslagen"}</div></div>
    <div class="kpi"><div class="l">Gem. CLV</div><div class="v">${PP.avg_clv != null ? spct(PP.avg_clv) : "–"}</div><div class="s">t.o.v. Unibet-slotodds</div></div>
    <div class="kpi"><div class="l">Gevechten goed</div><div class="v">${PP.fights ? pct(PP.accuracy) : "–"}</div><div class="s">${PP.fights ? PP.fights + " gevechten" : "nog geen uitslagen"}</div></div>
    <div class="kpi"><div class="l">Log-loss model / markt</div><div class="v">${PP.n_market ? num(PP.model_log_loss_same, 3) + `<span class="mut" style="font-size:15px"> / ${num(PP.market_log_loss, 3)}</span>` : "–"}</div><div class="s">${PP.n_market ? (PP.model_log_loss_same < PP.market_log_loss ? "▲ beter dan markt" : "▼ markt is beter") : "lager = beter"}</div></div>
  </div>
  ${adviesCard(ev)}
  <div class="grid g21">
    <div class="card"><h3>Bankroll (paper trading)</h3>
      ${curve.length > 1 ? lineChart({ series: [{ pts: curve, color: "#22c55e", area: true }], yfmt: v => "€" + Math.round(v).toLocaleString("nl-NL"), xfmt: v => fdateShort(new Date(v).toISOString().slice(0, 10)), baseline: D.meta.bankroll }) : `<div class="empty">Nog geen resultaten: de test begint op 5 december.<br>Hier verschijnt dan de bankroll van de model-bets.</div>`}
      <div class="note">Alleen echte vastgezette model-bets, afgerekend op de uitslag. Hoe het model het historisch had gedaan staat apart onder <a href="#/prestaties" style="text-decoration:underline">Prestaties (backtest)</a>.</div></div>
    <div class="card"><h3>Volgend event</h3>
      <div style="font:800 22px var(--head)">${esc(ev.name)}</div>
      <div class="rec">${fdate(ev.date)} · ${esc(ev.location)}</div>
      <div class="rec">${Object.entries(ev.times || {}).map(([k, v]) => `${k === "main_card" ? "Main card" : "Prelims"} ${esc(v)}`).join(" · ")} (NL)</div>
      <div id="cd" style="font:800 34px var(--head);margin:12px 0;color:var(--red2)"></div>
      <div class="evstats" style="justify-content:space-between">
        <div><b>${fights.length}</b><span>Gevechten</span></div><div><b>${nOdds}</b><span>Met odds</span></div>
        <div><b class="up">${ev.fights.filter(f => advice(f).status === "bet").length}</b><span>Value bets</span></div><div><b class="warn">${flags}</b><span>Vlaggen</span></div>
      </div>
      <a class="btn" style="margin-top:16px;width:100%;justify-content:center" href="#/fightcard/${ev.id}">Naar fight card →</a>
    </div>
  </div>
  <div class="grid g2" style="margin-top:14px">
    <div class="card"><h3>Value bets komende events (${vb.length})</h3>
      ${vb.length ? `<div class="tw"><table><tr><th>Gevecht</th><th>Pick</th><th class="num">Odds</th><th class="num">Edge</th><th class="num">Inzet</th></tr>
      ${vb.map(({ f, a }) => `<tr class="cl" data-href="#/matchup/${f.id}"><td>${esc(last(f.a.name))} vs ${esc(last(f.b.name))}</td><td>${esc(a.pick)}</td><td class="num">${num(a.dec)}</td><td class="num up">${spct(a.edge)}</td><td class="num">${eur(a.stake)}</td></tr>`).join("")}</table></div>`
      : `<div class="empty">Geen value bets met je huidige drempel (${pct(S.edge, 0)} edge).<br>${allFights().filter(f => f.odds_a != null).length} van ${allFights().filter(f => f.card !== "onbevestigd").length} gevechten hebben al odds.</div>`}</div>
    <div class="card"><h3>Laatste resultaten (${sb.length})</h3>
      ${sb.length ? sb.slice(-5).reverse().map(b => `<div class="srow"><span>${b.result === "W" ? "✅" : b.result === "L" ? "❌" : "➖"} ${esc(b.fight || b.fight_id)}</span><b class="${b.pnl >= 0 ? "up" : "down"}">${seur(b.pnl)}</b></div>`).join("") : `<div class="empty">Nog geen afgerekende model-bets (eerste event: 5 dec).</div>`}
      <h3 style="margin-top:16px">Waarschuwingen</h3>
      ${warn.map(w => `<div class="srow"><span class="${w.lvl}">⚠</span><span style="flex:1">${esc(w.t)}</span></div>`).join("")}
    </div>
  </div>` + disclaimer;
}
function modelCurve() {
  let bank = D.meta.bankroll; const pts = [];
  (D.bets || []).filter(b => ["W", "L", "push"].includes(b.result)).sort((a, b) => String(a.event_date).localeCompare(String(b.event_date)))
    .forEach(b => { bank += b.pnl || 0; pts.push([new Date(String(b.event_date).slice(0, 10)).getTime(), bank]); });
  return pts.length ? [[pts[0][0] - 864e5, D.meta.bankroll], ...pts] : [];
}
function liveCurve() {
  let bank = S.bankroll; const pts = [];
  settledBets().sort((a, b) => a.date.localeCompare(b.date)).forEach(b => { bank += betPnl(b); pts.push([new Date(b.date).getTime(), bank]); });
  return pts.length ? [[pts[0][0] - 864e5, S.bankroll], ...pts] : [];
}

/* ------------------------------------------------------------ 2. events */
function pageEvents() {
  const tab = loadJSON("fm_evtab", "up");
  const up = D.events, past = D.past_events;
  const year = loadJSON("fm_evyear", "alle"), type = loadJSON("fm_evtype", "alle"), onlyBets = loadJSON("fm_evbets", false);
  const years = [...new Set(past.map(e => e.date.slice(0, 4)))];
  let body = "";
  if (tab === "up") {
    body = up.map(e => e.none ? `<div class="card evcard"><div class="evimg" style="opacity:.4">–</div><div><div class="nm" style="font-size:17px">Weekend ${esc(e.weekend.replace("/", "–"))}</div><div class="rec">${esc(e.note || "Geen event")}</div></div></div>` : evCard(e)).join("");
  } else {
    const list = past.filter(e => (year === "alle" || e.date.startsWith(year)) && (type === "alle" || e.type === type));
    body = `<div class="card tw"><table><tr><th>Event</th><th>Datum</th><th>Locatie</th><th class="num">Gevechten</th></tr>
    ${list.map(e => `<tr><td><span class="tag ${e.type === "PPV" ? "ppv" : "fn"}">${e.type}</span> <b>${esc(e.name)}</b></td><td>${fdate(e.date)}</td><td class="rec">${esc(e.location)}</td><td class="num">${e.n_fights}</td></tr>`).join("")}</table>
    <div class="note">Historische events uit de trainingsdata (t/m 8 aug 2026). Het model heeft hier niet live op voorspeld; de backtest staat onder Prestaties.</div></div>`;
  }
  return ph("Events") + `<div class="filters">
    <button class="tab ${tab === "up" ? "on" : ""}" data-evtab="up">Komend (${up.filter(e => !e.none).length})</button>
    <button class="tab ${tab === "past" ? "on" : ""}" data-evtab="past">Afgelopen (${past.length})</button>
    ${tab === "past" ? `<select data-evyear><option value="alle">Alle jaren</option>${years.map(y => `<option ${y === year ? "selected" : ""}>${y}</option>`).join("")}</select>
    <select data-evtype><option value="alle">Alle types</option><option ${type === "PPV" ? "selected" : ""}>PPV</option><option ${type === "Fight Night" ? "selected" : ""}>Fight Night</option></select>` : ""}
  </div>${body}` + disclaimer;
}
function evCard(e) {
  const fs = e.fights.filter(f => f.card !== "onbevestigd");
  const title = e.name.split(":")[0];
  return `<a class="card evcard" href="#/fightcard/${e.id}">
    <div class="evimg">${esc(title)}</div>
    <div><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><span class="nm" style="font-size:18px">${esc(e.name)}</span><span class="tag ${e.type === "PPV" ? "ppv" : "fn"}">${e.type}</span></div>
      <div class="rec">📅 ${fdate(e.date)} · ${esc(Object.values(e.times || {}).join(" / "))} (NL)</div><div class="rec">📍 ${esc(e.location)}</div></div>
    <div class="evstats"><div><b>${fs.length}</b><span>Gevechten</span></div><div><b>${fs.filter(f => f.odds_a != null).length}</b><span>Met odds</span></div><div><b class="up">${fs.filter(f => advice(f).status === "bet").length}</b><span>Value bets</span></div></div>
    <div><span class="tag ${e.complete ? "ok" : "wait"}">${e.complete ? "Kaart compleet" : "Nog onvolledig"}</span></div></a>`;
}

/* ------------------------------------------------------------ 3. fight card */
function pageFightcard(id) {
  const e = D.events.find(x => x.id === id) || nextEvent();
  const filt = loadJSON("fm_fcfilter", "alle");
  const fs = e.fights;
  const adv = fs.map(f => ({ f, a: advice(f) }));
  const vb = adv.filter(x => x.a.status === "bet");
  const flagged = f => (f.flags || []).some(x => x.type !== "data");
  const show = ({ f, a }) => filt === "alle" || (filt === "value" && a.status === "bet") || (filt === "flags" && flagged(f)) || (filt === "main" && f.card === "main") || (filt === "prelims" && f.card === "prelims");
  let rows = "", lastSec = "";
  for (const x of adv.filter(show)) {
    const { f, a } = x;
    if (f.card !== lastSec) { rows += `<tr class="sec"><td colspan="10">${{ main: "Main card", prelims: "Prelims", onbevestigd: "Onbevestigd" }[f.card] || f.card}</td></tr>`; lastSec = f.card; }
    const conf = f.card === "onbevestigd";
    const pa = f.p_final;
    rows += `<tr class="${conf ? "" : "cl"}" ${conf ? "" : `data-href="#/matchup/${f.id}"`} style="${conf ? "opacity:.55" : ""}">
      <td><div class="nm">${esc(f.a.name)} <span class="mut">vs</span> ${esc(f.b.name)}</div><div class="rec">${esc(f.a.record || "?")} · ${esc(f.b.record || "?")}</div></td>
      <td>${esc(f.weight_class)}</td><td>${f.rounds === 5 ? `<span class="tag five">5</span>` : "3"}</td>
      <td>${pa == null ? "–" : `<div class="pbar"><i style="width:${pa * 100}%">${Math.round(pa * 100)}%</i><b style="width:${(1 - pa) * 100}%">${Math.round((1 - pa) * 100)}%</b></div>`}</td>
      <td class="num">${f.odds_a == null ? `<span class="mut">–</span>` : `${pct(fairP(f.odds_a, f.odds_b))} / ${pct(1 - fairP(f.odds_a, f.odds_b))}`}</td>
      <td class="num" ${oddsTitle(betOdds(f)?.[0])}>${betOdds(f) ? `${fmtOdds(betOdds(f)[0])} / ${fmtOdds(betOdds(f)[1])}` : `<span class="mut">–</span>`}</td>
      <td class="num ${a.edge > 0 ? "up" : a.edge < 0 ? "down" : ""}">${a.edge == null ? "–" : spct(a.edge)}</td>
      <td>${adviceTag(f, a)}</td><td class="num">${a.status === "bet" ? eur(a.stake) : "–"}</td>
      <td>${(f.flags || []).filter(x => x.type !== "data").map(x => `<span class="tag flag" title="${esc(x.text)}">⚠ ${esc(x.type)}</span>`).join(" ")}</td></tr>`;
  }
  const chips = [["alle", `Alle (${fs.length})`], ["value", `Value bets (${vb.length})`], ["flags", `Met vlaggen (${fs.filter(flagged).length})`], ["main", `Main card (${fs.filter(f => f.card === "main").length})`], ["prelims", `Prelims (${fs.filter(f => f.card === "prelims").length})`]];
  return ph(esc(e.name), { back: "#/events", sub: `📅 ${fdate(e.date)} · ${esc(Object.entries(e.times || {}).map(([k, v]) => (k === "main_card" ? "main card " : "prelims ") + v).join(" · "))} (NL) · 📍 ${esc(e.location)} <span class="tag ${e.type === "PPV" ? "ppv" : "fn"}">${e.type}</span>`,
    right: `<div class="evstats" style="margin-left:auto"><div><b>${fs.filter(f => f.card !== "onbevestigd").length}</b><span>Gevechten</span></div><div><b>${fs.filter(f => f.odds_a != null).length}</b><span>Met odds</span></div><div><b class="up">${vb.length}</b><span>Value bets</span></div><div><b>${eur(vb.reduce((s, x) => s + x.a.stake, 0))}</b><span>Totale inzet</span></div></div>` }) +
    (e.note ? `<div class="advice" style="margin:0 0 14px"><span class="warn">⚠</span>${esc(e.note)}</div>` : "") +
    `<div class="card" style="padding:10px 14px;margin-bottom:14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap"><span class="mut">Voorspellingen gemaakt:</span> <b>${fdate(D.meta.generated_at.slice(0, 10))}</b> · model ${esc(D.meta.version)} · data t/m ${fdate(D.meta.trained_until)} ${e.locked_at ? `<span class="tag ok" style="margin-left:auto">🔒 Vastgezet ${esc(e.locked_at.slice(0, 16).replace("T", " "))}</span>` : `<span class="tag wait" style="margin-left:auto">Nog niet vastgezet: gebeurt automatisch op de vechtdag (09:00)</span>`}</div>
    ${adviesCard(e)}
    <div class="filters">${chips.map(([k, l]) => `<button class="tab ${k === filt ? "on" : ""}" data-fcf="${k}">${l}</button>`).join("")}</div>
    <div class="card tw"><table><tr><th>Gevecht</th><th>Klasse</th><th>Rnd</th><th>Model (A / B)</th><th class="num">Markt</th><th class="num">Unibet</th><th class="num">Edge</th><th>Advies</th><th class="num">Inzet</th><th>Vlaggen</th></tr>${rows}</table>
    <div class="note">Model = model gecombineerd met de markt (waar odds zijn) · Markt = kans zonder marge (mediaan van alle bookmakers) · Unibet = de prijs waar je inzet: advies en inzet rekenen daarmee · Advies bij edge ≥ ${pct(S.edge, 0)}, ${S.kelly} Kelly, max ${pct(S.maxBet, 0)} per gevecht (aanpasbaar in Instellingen). Klik een gevecht voor de uitleg.</div></div>` + disclaimer;
}

/* ------------------------------------------------------------ 4. matchup */
const STYLE_ROWS = [["slpm", "Sig. strikes per minuut", 8, v => num(v, 2)], ["sapm", "Geïncasseerd per minuut", 8, v => num(v, 2)], ["sig_acc", "Striking-nauwkeurigheid", 1, v => pct(v, 0)],
  ["sig_def", "Striking-verdediging", 1, v => pct(v, 0)], ["td15", "Takedowns / 15 min", 5, v => num(v, 2)], ["td_def", "Takedown-verdediging", 1, v => pct(v, 0)],
  ["ctrl_share", "Controletijd", .6, v => pct(v, 0)], ["sub15", "Submission-pogingen / 15 min", 2, v => num(v, 2)], ["kd15", "Knockdowns / 15 min", 1.2, v => num(v, 2)]];
function pageMatchup(id) {
  const f = (id && findFight(id)) || allFights().find(x => x.card === "main");
  const e = f.event, a = advice(f), A = f.a, B = f.b, pa = f.p_final;
  const tape = [["Record", A.record, B.record], ["UFC-gevechten", A.n_ufc, B.n_ufc], ["Elo", Math.round(A.elo), Math.round(B.elo)], ["Leeftijd", A.age ? Math.floor(A.age) : "–", B.age ? Math.floor(B.age) : "–"],
    ["Lengte", cm(A.height_cm), cm(B.height_cm)], ["Reach", cm(A.reach_cm), cm(B.reach_cm)], ["Stance", A.stance || "–", B.stance || "–"],
    ["Laatste gevecht", A.last_date ? fdateShort(A.last_date) : "debuut", B.last_date ? fdateShort(B.last_date) : "debuut"], ["Reeks", streakTxt(A.streak), streakTxt(B.streak)], ["KO-verliezen", A.ko_losses ?? "–", B.ko_losses ?? "–"]];
  const ma = f.method?.a || {}, mb = f.method?.b || {};
  const mseg = (v, c, l) => v > .02 ? `<div style="width:${v * 100}%;background:${c}" title="${l} ${pct(v)}">${v > .07 ? l + " " + Math.round(v * 100) + "%" : ""}</div>` : "";
  const ca = D.fighters[A.id]?.cardio || [], cb = D.fighters[B.id]?.cardio || [];
  return ph(`${esc(e.name.split(":")[0])} <span class="mut">/</span> ${esc(last(A.name))} vs ${esc(last(B.name))}`, { back: `#/fightcard/${e.id}`, sub: `${esc(f.weight_class)} · ${f.rounds} rondes · ${{ main: "main card", prelims: "prelims" }[f.card] || ""} · ${fdate(e.date)}` }) + `
  <div class="card vs">
    <a class="fx" href="#/vechters/${A.id}"><div class="av a">${initials(A.name)}</div><div><div class="n">${esc(A.name)}</div><div class="rec">${esc(A.record || "")} · Elo ${Math.round(A.elo)}</div><div style="margin-top:6px"><span class="tag" ${oddsTitle(f.odds_a)}>${fmtOdds(f.odds_a)}</span> ${sparkDots(A.last5)}</div></div></a>
    <div class="vsmid">VS</div>
    <a class="fx r" href="#/vechters/${B.id}"><div class="av b">${initials(B.name)}</div><div><div class="n">${esc(B.name)}</div><div class="rec">${esc(B.record || "")} · Elo ${Math.round(B.elo)}</div><div style="margin-top:6px">${sparkDots(B.last5)} <span class="tag" ${oddsTitle(f.odds_b)}>${fmtOdds(f.odds_b)}</span></div></div></a>
    <div style="grid-column:1/-1;margin-top:10px"><div style="text-align:center;font-weight:700;color:var(--muted);font-size:12px;letter-spacing:.8px;text-transform:uppercase">Modelkans${f.odds_a != null ? " (model + markt)" : ""}</div>
      <div class="bigbar"><i style="width:${pa * 100}%">${pct(pa)}</i><b style="width:${(1 - pa) * 100}%">${pct(1 - pa)}</b></div>
      <div class="legend" style="justify-content:space-between;margin-top:6px"><span>Alleen model: ${pct(f.p_model)}</span><span>${f.odds_a != null ? `Markt (zonder marge): ${pct(fairP(f.odds_a, f.odds_b))} / ${pct(1 - fairP(f.odds_a, f.odds_b))}` : "Nog geen odds"}</span></div></div>
  </div>
  <div class="grid g3" style="margin-top:14px">
    <div class="card"><h3>Belangrijkste redenen</h3>
      ${(f.reasons || []).map(r => `<div class="reason"><span>${r.pp >= 0 ? "▲" : "▼"} ${esc(r.label)}</span><b class="${r.pp >= 0 ? "blue" : "down"}">${r.pp >= 0 ? "+" : ""}${num(r.pp, 1)} pp</b></div>`).join("") || `<div class="empty">Geen uitleg beschikbaar</div>`}
      <div class="note">Bijdrage aan de kans van <b class="blue">${esc(last(A.name))}</b> (blauw = in zijn/haar voordeel, rood = in het voordeel van ${esc(last(B.name))}), uit het logistische model.</div></div>
    <div class="card"><h3>Odds & markt</h3>
      ${f.odds_a != null ? `${barChart([{ label: "Model " + last(A.name), value: f.p_model, color: "#2f6bff" }, { label: "Markt " + last(A.name), value: fairP(f.odds_a, f.odds_b), color: "#6b717c" }, { label: "Eind " + last(A.name), value: pa, color: "#4c86ff" }], { yfmt: v => pct(v, 0), h: 180 })}
      ${oddsDetail(f, A, B)}` : `<div class="empty">Nog geen odds voor dit gevecht.<br>Advies volgt zodra de lijn uitkomt.</div>`}</div>
    <div class="card"><h3>Wat zeggen anderen</h3>
      ${(f.tips || []).length ? f.tips.map(t => `<div class="srow"><span style="flex:1">${esc(t.source)}</span><b>${esc(last(t.pick))}${t.prob != null ? ` <span class="mut">${pct(t.prob, 0)}</span>` : ""}</b>${t.correct != null ? ` <span class="tag ${t.correct ? "ok" : "flag"}">${t.correct ? "✓" : "✗"}</span>` : ""}</div>`).join("") : `<div class="empty">Nog geen picks van tipsters.</div>`}
      <h3 style="margin-top:16px">Nieuws & kamp</h3>
      ${(f.flags || []).map(x => `<div class="srow"><span class="tag ${x.type === "data" ? "" : "flag"}">${esc(x.type)}</span><span style="flex:1">${x.fighter ? `<b>${esc(x.fighter)}</b>: ` : ""}${esc(x.text)}</span></div>`).join("") || `<div class="empty">Geen vlaggen</div>`}
      <div class="note">Nieuws, trainingskamp en weigh-ins worden nog niet automatisch verzameld (fase 7).</div></div>
  </div>
  <div class="advice ${a.status === "bet" ? "go" : ""}">
    ${a.status === "bet" ? `<b class="up" style="font-size:16px">✔ Advies: BET ${esc(a.pick)} @ ${num(a.dec)}</b><span>Edge: <b class="up">${spct(a.edge)}</b></span><span>EV: ${spct(a.ev)}</span><span style="margin-left:auto">Aanbevolen inzet (virtueel): <b class="up">${eur(a.stake)}</b></span><button class="btn sm" data-addbet="${f.id}">+ In bet-log</button>`
      : a.status === "none" ? `<b>Geen value</b><span class="mut">Grootste edge ${spct(a.edge)} is kleiner dan je drempel (${pct(S.edge, 0)}).</span>`
      : `<b class="warn">Wacht op odds</b><span class="mut">Het model heeft een kans, maar zonder odds is er geen advies.</span>`}
  </div>
  <div class="grid g3" style="margin-top:14px">
    <div class="card"><h3>Tale of the tape</h3><table class="tape">${tape.map(([l, x, y]) => `<tr><td><b>${esc(x ?? "–")}</b></td><td>${l}</td><td><b>${esc(y ?? "–")}</b></td></tr>`).join("")}</table></div>
    <div class="card"><h3>Stijl (gewogen, recente gevechten zwaarder)</h3>
      ${STYLE_ROWS.map(([k, l, mx, fm]) => { const x = A.style?.[k], y = B.style?.[k]; return `<div class="mirror"><span class="lab">${l}</span><span>${x == null ? "–" : fm(x)}</span><div class="bl"><i style="width:${Math.min(1, (x || 0) / mx) * 100}%"></i></div><div class="br"><i style="width:${Math.min(1, (y || 0) / mx) * 100}%"></i></div><span class="vr">${y == null ? "–" : fm(y)}</span></div>`; }).join("")}
      <div class="legend"><span><i style="background:var(--blue)"></i>${esc(A.name)}</span><span><i style="background:var(--red)"></i>${esc(B.name)}</span></div>
      ${A.n_ufc === 0 || B.n_ufc === 0 ? `<div class="note warn">⚠ UFC-debuut: geen UFC-statistieken beschikbaar.</div>` : ""}</div>
    <div class="card"><h3>Methode van winst (schatting)</h3>
      <div class="method">${mseg(ma.ko, "#2f6bff", "KO")}${mseg(ma.sub, "#1e4fc0", "SUB")}${mseg(ma.dec, "#5b8be0", "DEC")}${mseg(mb.dec, "#e0767a", "DEC")}${mseg(mb.sub, "#9f1414", "SUB")}${mseg(mb.ko, "#d20a0a", "KO")}</div>
      <div class="note">Links ${esc(last(A.name))}, rechts ${esc(last(B.name))}. Kans op een beslissing: <b>${pct((ma.dec || 0) + (mb.dec || 0), 0)}</b>. Eenvoudige schatting uit winkans × eigen finish-historie.</div>
      <h3 style="margin-top:18px">Cardio: sig. strikes per ronde</h3>
      ${ca.length || cb.length ? lineChart({ series: [{ pts: ca.map(r => [r.round, r.v]), color: "#2f6bff", dots: true }, { pts: cb.map(r => [r.round, r.v]), color: "#d20a0a", dots: true }], h: 160, w: 360, ylab: 3, yfmt: v => v.toFixed(0), xfmt: v => Number.isInteger(+v.toFixed(2)) ? "R" + v.toFixed(0) : "" }) : `<div class="empty">Geen rondedata</div>`}
    </div>
  </div>
  <div class="card" style="margin-top:14px"><h3>Gemeenschappelijke tegenstanders</h3>
    ${f.common?.length ? `<table><tr><th>Tegenstander</th><th>${esc(A.name)}</th><th>${esc(B.name)}</th></tr>${f.common.map(c => `<tr><td>${esc(c.opp)}</td><td>${sparkDots([c.a])}</td><td>${sparkDots([c.b])}</td></tr>`).join("")}</table>` : `<div class="mut">Geen gemeenschappelijke tegenstanders in de UFC-data.</div>`}</div>` + disclaimer;
}
const streakTxt = s => s == null || s === 0 ? "–" : s > 0 ? `${s}W` : `${-s}L`;

/* ------------------------------------------------------------ 5. vechter */
function pageVechter(id) {
  const ids = Object.keys(D.fighters);
  if (!id || !D.fighters[id]) {
    return ph("Vechters", { sub: "Alle vechters op de komende kaarten. Gebruik de zoekbalk om snel te zoeken." }) + `<div class="grid g4">${allFights().filter(f => f.card !== "onbevestigd").flatMap(f => [f.a, f.b]).map(x => {
      const F = D.fighters[x.id]; return `<a class="card" href="#/vechters/${x.id}" style="display:flex;gap:12px;align-items:center"><div class="av sm a">${initials(x.name)}</div><div><div class="nm">${esc(x.name)}</div><div class="rec">${esc(F?.weight_class || "")} · ${esc(x.record || "")}</div></div></a>`; }).join("")}</div>` + disclaimer;
  }
  const F = D.fighters[id], tab = loadJSON("fm_ftab", "overzicht");
  const h = F.history || [], eh = F.elo_history || [];
  const ufcW = h.filter(x => x.result === "W").length;
  const fight = allFights().find(f => f.a.id === id || f.b.id === id);
  const me = fight ? (fight.a.id === id ? fight.a : fight.b) : null;
  const st = me?.style || {}, dv = F.division_avg || {};
  const age = F.dob ? Math.floor((Date.now() - new Date(F.dob)) / 3.15576e10) : null;
  const norm = (k, mx) => st[k] == null ? 0 : Math.min(1, st[k] / mx), normd = (k, mx) => dv[k] == null ? 0 : Math.min(1, dv[k] / mx);
  const axes = ["Striking", "Nauwkeurigheid", "Grappling", "Controle", "Submissions", "Verdediging"];
  const keys = [["slpm", 7], ["sig_acc", .7], ["td15", 4], ["ctrl_share", .5], ["sub15", 1.5], ["sig_def", .75]];
  let body = "";
  if (tab === "gevechten" || tab === "overzicht") {
    body += `<div class="card tw" style="${tab === "overzicht" ? "" : ""}"><h3>${tab === "overzicht" ? "Laatste 5 gevechten" : "Alle UFC-gevechten"}</h3><table><tr><th>Datum</th><th>Tegenstander</th><th>Uitslag</th><th>Methode</th><th class="num">Ronde</th><th class="num">Odds vooraf</th><th>Event</th></tr>
      ${(tab === "overzicht" ? h.slice(0, 5) : h).map(x => `<tr><td>${fdateShort(x.date)}</td><td>${esc(x.opp)}</td><td>${sparkDots([x.result])}</td><td>${esc(x.method || "")}<div class="rec">${esc(x.method_detail || "")}</div></td><td class="num">${x.end_round ?? ""}</td><td class="num" ${oddsTitle(x.odds)}>${fmtOdds(x.odds)}</td><td class="rec">${esc(x.event || "")}</td></tr>`).join("") || `<tr><td colspan="7" class="mut">Geen UFC-gevechten in de data (debuut of na 8 aug 2026).</td></tr>`}</table></div>`;
  }
  if (tab === "statistieken" || tab === "overzicht") {
    body += `<div class="card"><h3>Kerncijfers (UFC, gewogen recente vorm)</h3>${STYLE_ROWS.map(([k, l, , fm]) => `<div class="srow"><span>${l}</span><b>${st[k] == null ? "–" : fm(st[k])}</b><span class="mut" style="width:90px;text-align:right">div. ${dv[k] == null ? "–" : fm(dv[k])}</span></div>`).join("")}<div class="note">"div." = mediaan van de gewichtsklasse (laatste 3 jaar).</div></div>`;
  }
  if (tab === "stijl" || tab === "overzicht") {
    body += `<div class="card"><h3>Stijlprofiel (t.o.v. divisie)</h3>${radar(axes, keys.map(([k, m]) => norm(k, m)), keys.map(([k, m]) => normd(k, m)))}<div class="legend" style="justify-content:center"><span><i style="background:var(--red)"></i>${esc(last(F.name))}</span><span><i style="background:#8a919c"></i>Divisiemediaan</span></div></div>`;
  }
  return ph("Vechterprofiel", { back: "#/vechters" }) + `
  <div class="card hero">
    <div class="av b" style="width:120px;height:120px;font-size:40px">${initials(F.name)}</div>
    <div><div class="n">${esc(F.name)}</div>${F.nickname ? `<div class="mut">"${esc(F.nickname)}"</div>` : ""}
      <div class="rec" style="margin-top:6px">${esc(F.weight_class)} · ${esc(F.stance || "stance onbekend")}${age ? ` · ${age} jaar` : ""}</div>
      <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap"><span class="tag">Pro ${esc(F.record_pro || "?")}</span><span class="tag">UFC ${esc(F.record_ufc || "0-0-0")}</span><span class="tag">${cm(F.height_cm)}</span><span class="tag">reach ${cm(F.reach_cm)}</span></div>
      ${fight ? `<a class="btn sm" style="margin-top:12px" href="#/matchup/${fight.id}">Komend: vs ${esc(fight.a.id === id ? fight.b.name : fight.a.name)} →</a>` : ""}</div>
    <div><div style="display:flex;justify-content:space-between"><b>Elo-rating</b>${eh.length ? `<b>${Math.round(eh.at(-1).elo)}</b>` : ""}</div>
      ${eh.length > 1 ? lineChart({ series: [{ pts: eh.map(x => [new Date(x.date).getTime(), x.elo, { c: x.result === "W" ? "#22c55e" : x.result === "L" ? "#d20a0a" : "#888", t: x.date + " " + (x.result || "") }]), color: "#22c55e", area: true, dots: true }], h: 170, w: 420, ylab: 4, yfmt: v => Math.round(v), xfmt: v => new Date(v).getFullYear() }) : `<div class="empty">Nog geen Elo-historie (debuut).</div>`}</div>
  </div>
  <div class="subtabs">${[["overzicht", "Overzicht"], ["gevechten", "Gevechten"], ["statistieken", "Statistieken"], ["stijl", "Stijl & profiel"]].map(([k, l]) => `<button class="tab ${k === tab ? "on" : ""}" data-ftab="${k}">${l}</button>`).join("")}</div>
  <div class="grid ${tab === "overzicht" ? "g3" : ""}">${body}</div>` + disclaimer;
}

/* ------------------------------------------------------------ 6. bet-log */
/* tipsters vs model */
function tipstersCard() {
  const T = D.tipsters || [];
  const row = t => `<tr><td><b>${esc(t.name)}</b><div class="rec">${esc(t.type || "")}</div></td><td class="num">${t.picks}</td><td class="num">${t.settled}</td>
    <td class="num">${t.accuracy != null ? pct(t.accuracy) : "–"}</td><td class="num">${t.model_accuracy_same != null ? pct(t.model_accuracy_same) : "–"}</td>
    <td class="num">${t.fav_accuracy_same != null ? pct(t.fav_accuracy_same) : "–"}</td><td class="num">${t.fav_share != null ? pct(t.fav_share, 0) : "–"}</td>
    <td class="num ${t.roi > 0 ? "up" : t.roi < 0 ? "down" : ""}">${t.roi != null ? spct(t.roi) : "–"}</td><td class="num ${t.avg_clv > 0 ? "up" : t.avg_clv < 0 ? "down" : ""}">${t.avg_clv != null ? spct(t.avg_clv) : "–"}</td></tr>`;
  return `<div class="card" style="margin-bottom:14px"><h3>Tipsters vs. model</h3>
    ${T.length ? `<div class="tw"><table><tr><th>Bron</th><th class="num">Picks</th><th class="num">Uitslag</th><th class="num">% goed</th><th class="num">Model (zelfde)</th><th class="num">Favoriet (zelfde)</th><th class="num">Kiest favoriet</th><th class="num">ROI</th><th class="num">CLV</th></tr>${T.map(row).join("")}</table></div>`
      : `<div class="empty">Nog geen picks vastgelegd.</div>`}
    <div class="note">Picks worden vóór het event met tijdstip vastgelegd. "Model (zelfde)" en "Favoriet (zelfde)" = hoe vaak ons model en simpelweg de favoriet goed zaten op precies dezelfde gevechten. ROI = 1 eenheid per pick op de Unibet-prijs van dat moment. Pas na veel picks zegt dit iets.</div></div>`;
}
/* automatisch vastgezette model-bets (zelfde voor iedereen) */
function modelBetsCard() {
  const P = D.paper || {}, B = D.bets || [];
  const k = (l, v, sub = "") => `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div><div class="s">${sub}</div></div>`;
  return `<div class="card" style="margin-bottom:14px"><h3>Model-bets (automatisch vastgezet op de vechtdag)</h3>
    <div class="kpis">${k("Afgerekende gevechten", P.fights ?? 0, P.fights ? "goed: " + pct(P.accuracy) : "na 5 dec")}
      ${k("Log-loss model / markt", P.n_market ? `${num(P.model_log_loss_same, 3)} / ${num(P.market_log_loss, 3)}` : "–", "lager = beter, zelfde gevechten")}
      ${k("Virtuele bets", P.bets ?? 0, P.bets ? "geraakt: " + pct(P.hit) : "")}
      ${k("W/V · ROI", P.bets ? `${eur(P.pnl)} · ${spct(P.roi)}` : "–")}
      ${k("Gem. CLV", P.avg_clv != null ? spct(P.avg_clv) : "–", "t.o.v. Unibet-slotodds")}</div>
    ${B.length ? `<div class="tw"><table><tr><th>Datum</th><th>Gevecht</th><th>Pick</th><th class="num">Odds</th><th class="num">Inzet</th><th>Uitslag</th><th class="num">Slotodds</th><th class="num">CLV</th><th class="num">W/V</th></tr>
      ${B.map(b => `<tr><td>${fdateShort(String(b.event_date || b.placed_at).slice(0, 10))}</td><td>${esc(b.fight || b.fight_id)}</td><td><b>${esc(b.pick_name)}</b></td><td class="num">${num(b.odds_taken)}</td><td class="num">${eur(b.stake)}</td>
        <td>${b.result === "open" ? `<span class="tag wait">open</span>` : `<span class="tag ${b.result === "W" ? "bet" : ""}">${esc(b.result)}</span>`}</td>
        <td class="num">${b.odds_closing ? num(b.odds_closing) : "–"}</td><td class="num ${b.clv > 0 ? "up" : b.clv < 0 ? "down" : ""}">${b.clv != null ? spct(b.clv) : "–"}</td>
        <td class="num ${b.pnl > 0 ? "up" : b.pnl < 0 ? "down" : ""}">${b.pnl != null ? eur(b.pnl) : "–"}</td></tr>`).join("")}</table></div>`
      : `<div class="empty">Nog geen vastgezette model-bets. Op de vechtdag om 09:00 zet de ververs-taak de voorspellingen en bets vast; na het event worden ze afgerekend.</div>`}
    <div class="note">CLV = genomen odds ÷ slotodds − 1. Positief over veel bets = het model vindt echt betere prijzen dan de markt.</div></div>`;
}
function pageBets() {
  const fs = loadJSON("fm_betfilter", "alle");
  const list = LOCAL_BETS.filter(b => fs === "alle" || (fs === "open" ? b.result === "open" : b.result !== "open"));
  const sb = settledBets(), pnl = sb.reduce((s, b) => s + betPnl(b), 0), stk = sb.reduce((s, b) => s + b.stake, 0);
  const totalStake = LOCAL_BETS.reduce((s, b) => s + b.stake, 0);
  const avgOdds = LOCAL_BETS.length ? LOCAL_BETS.reduce((s, b) => s + b.odds, 0) / LOCAL_BETS.length : null;
  const advised = allFights().map(f => ({ f, a: advice(f) })).filter(x => x.a.status === "bet" && !LOCAL_BETS.some(b => b.fight_id === x.f.id));
  const opts = allFights().filter(f => f.card !== "onbevestigd").map(f => `<option value="${f.id}">${esc(f.event.name.split(":")[0])}: ${esc(f.a.name)} vs ${esc(f.b.name)}</option>`).join("");
  return ph("Bet-log (paper trading)", { sub: "Je virtuele inzetten worden alleen in deze browser bewaard. Vastzetten vóór het gevecht, daarna niet meer wijzigen: dat houdt de test eerlijk." }) + modelBetsCard() + tipstersCard() + `
  <div class="kpis">
    <div class="kpi"><div class="l">Totaal bets</div><div class="v">${LOCAL_BETS.length}</div></div>
    <div class="kpi"><div class="l">Winst%</div><div class="v">${sb.length ? pct(sb.filter(b => b.result === "W").length / sb.length) : "–"}</div></div>
    <div class="kpi"><div class="l">ROI</div><div class="v ${pnl >= 0 ? "up" : "down"}">${stk ? spct(pnl / stk) : "–"}</div></div>
    <div class="kpi"><div class="l">Totale inzet</div><div class="v">${eur(totalStake)}</div></div>
    <div class="kpi"><div class="l">W/V</div><div class="v ${pnl >= 0 ? "up" : "down"}">${sb.length ? seur(pnl) : "–"}</div></div>
    <div class="kpi"><div class="l">Gem. odds</div><div class="v">${avgOdds ? num(avgOdds) : "–"}</div></div>
  </div>
  ${advised.length ? `<div class="advice go" style="margin-bottom:14px"><b>${advised.length} geadviseerde value bet(s) nog niet in je log</b>${advised.map(({ f, a }) => `<button class="btn sm" data-addbet="${f.id}">+ ${esc(a.pick)} @ ${num(a.dec)} (${eur(a.stake)})</button>`).join("")}</div>` : ""}
  <div class="filters">${[["alle", "Alle"], ["open", "Open"], ["af", "Afgerekend"]].map(([k, l]) => `<button class="tab ${k === fs ? "on" : ""}" data-betf="${k}">${l}</button>`).join("")}
    <button class="btn" style="margin-left:auto" id="newbet">+ Nieuwe bet (virtueel)</button></div>
  <div class="card" id="betform" style="display:none;margin-bottom:14px"><h3>Nieuwe virtuele bet</h3>
    <div class="grid g4"><label>Gevecht<br><select id="bf_fight" style="width:100%">${opts}</select></label>
      <label>Pick<br><select id="bf_pick" style="width:100%"></select></label>
      <label>Odds (decimaal)<br><input id="bf_odds" type="number" step="0.01" min="1.01" style="width:100%"></label>
      <label>Inzet (€)<br><input id="bf_stake" type="number" step="1" min="1" style="width:100%"></label></div>
    <div style="margin-top:12px;display:flex;gap:8px"><button class="btn" id="bf_save">Opslaan</button><button class="btn ghost" id="bf_cancel">Annuleren</button></div></div>
  <div class="card tw"><table><tr><th>Datum</th><th>Event</th><th>Gevecht</th><th>Pick</th><th class="num">Odds</th><th class="num">Inzet</th><th>Uitslag</th><th class="num">Slotodds</th><th class="num">CLV</th><th class="num">W/V</th><th></th></tr>
  ${list.map(b => `<tr><td>${fdateShort(b.date)}</td><td class="rec">${esc(b.event)}</td><td>${esc(b.fight)}</td><td><b>${esc(b.pick)}</b></td><td class="num">${num(b.odds)}</td><td class="num">${eur(b.stake)}</td>
    <td><select data-res="${b.id}"><option value="open" ${b.result === "open" ? "selected" : ""}>Open</option><option value="W" ${b.result === "W" ? "selected" : ""}>Gewonnen</option><option value="L" ${b.result === "L" ? "selected" : ""}>Verloren</option><option value="void" ${b.result === "void" ? "selected" : ""}>Geannuleerd</option></select></td>
    <td class="num"><input type="number" step="0.01" min="1.01" value="${b.closing ?? ""}" data-close="${b.id}" style="width:74px" placeholder="–"></td>
    <td class="num ${b.closing ? (b.odds > b.closing ? "up" : "down") : ""}">${b.closing ? spct(b.odds / b.closing - 1) : "–"}</td>
    <td class="num ${betPnl(b) >= 0 ? "up" : "down"}">${b.result === "W" || b.result === "L" ? seur(betPnl(b)) : "–"}</td>
    <td><button class="btn ghost sm" data-del="${b.id}" title="Verwijderen">✕</button></td></tr>`).join("") || `<tr><td colspan="11"><div class="empty">Nog geen virtuele bets. Voeg geadviseerde value bets toe, of maak er zelf een.</div></td></tr>`}</table>
  <div class="note">CLV = jouw odds ÷ slotodds − 1. Positieve CLV over veel bets is de beste aanwijzing dat het model echt iets weet.</div></div>
  <div style="margin-top:12px;display:flex;gap:8px"><button class="btn ghost sm" id="exportcsv">Exporteer CSV</button></div>` + disclaimer;
}
function addBetFromFight(fid) {
  const f = findFight(fid), a = advice(f);
  if (a.status !== "bet") return;
  LOCAL_BETS.push({ id: Date.now().toString(36), fight_id: f.id, date: f.event.date, event: f.event.name.split(":")[0], fight: `${f.a.name} vs ${f.b.name}`,
    pick: a.pick, odds: +a.dec.toFixed(2), stake: Math.round(a.stake), prob: a.sideA ? f.p_final : 1 - f.p_final, result: "open", model: D.meta.version, placed: new Date().toISOString() });
  saveJSON("fm_bets", LOCAL_BETS);
}

/* ------------------------------------------------------------ 7. prestaties */
function pagePrestaties() {
  const P = D.performance, tab = loadJSON("fm_ptab", "overzicht");
  const mm = P.metrics.find(m => m.model === "mm"), mk = P.metrics.find(m => m.model === "mkt_p");
  const names = { elo_prob: "Alleen Elo", blend: "Model (zonder odds)", mm: "Model + markt", mkt_p: "Markt (slotodds)" };
  const kp = `<div class="kpis">
    <div class="kpi"><div class="l">ROI (backtest)</div><div class="v ${P.sim.roi >= 0 ? "up" : "down"}">${spct(P.sim.roi)}</div><div class="s">${P.sim.bets} bets</div></div>
    <div class="kpi"><div class="l">Winst%</div><div class="v">${pct(P.sim.hit)}</div><div class="s">van de bets</div></div>
    <div class="kpi"><div class="l">Accuracy</div><div class="v">${pct(mm.accuracy)}</div><div class="s">markt ${pct(mk.accuracy)}</div></div>
    <div class="kpi"><div class="l">Log-loss</div><div class="v">${num(mm.log_loss, 4)}</div><div class="s">markt ${num(mk.log_loss, 4)}</div></div>
    <div class="kpi"><div class="l">Brier-score</div><div class="v">${num(mm.brier, 4)}</div><div class="s">markt ${num(mk.brier, 4)}</div></div>
    <div class="kpi"><div class="l"># voorspellingen</div><div class="v">${mm.n.toLocaleString("nl-NL")}</div><div class="s">met odds, 2017-2026</div></div></div>`;
  const cal = `<div class="card"><h3>Kalibratie (betrouwbaarheid)</h3>${calibChart(P.calibration)}<div class="note">Op de stippellijn = de kansen kloppen. Puntgrootte = aantal gevechten.</div></div>`;
  const roi = `<div class="card"><h3>ROI per jaar (backtest)</h3>${barChart(P.roi_year.map(r => ({ label: String(r.year), value: r.roi })), { yfmt: v => spct(v, 1) })}<div class="note">Gesimuleerd op slotodds, ${S.kelly} Kelly, edge ≥ ${pct(D.meta.edge_min, 0)}.</div></div>`;
  const imp = n => `<div class="card"><h3>Feature importance (top ${n})</h3>${hbars(P.importance.slice(0, n).map(i => ({ label: i.label, value: i.weight })))}<div class="note">Relatief gewicht in het logistische model.</div></div>`;
  const comp = `<div class="card tw"><h3>Model vs. markt (gevechten met odds)</h3><table><tr><th>Model</th><th class="num">n</th><th class="num">Accuracy</th><th class="num">Log-loss</th><th class="num">Brier</th></tr>${P.metrics.map(m => `<tr><td>${names[m.model] || m.model}</td><td class="num">${m.n}</td><td class="num">${pct(m.accuracy)}</td><td class="num ${m.model === "mm" && m.log_loss < mk.log_loss ? "up" : ""}">${num(m.log_loss, 4)}</td><td class="num">${num(m.brier, 4)}</td></tr>`).join("")}</table>
    <div class="note"><b>Eerlijke conclusie:</b> het model zonder odds is duidelijk slechter dan de markt. Gecombineerd met de markt is het net iets beter (log-loss ${num(mm.log_loss, 4)} vs ${num(mk.log_loss, 4)}), maar te weinig om na kosten winst te bewijzen. Paper trading moet uitwijzen of er echte edge is.</div></div>`;
  const ll = `<div class="card"><h3>Log-loss per jaar</h3>${lineChart({ series: [{ pts: P.by_year.map(r => [r.year, r.blend]), color: "#8a919c", dots: true, dash: "4 4" }, { pts: P.by_year.map(r => [r.year, r.mm]), color: "#2f6bff", dots: true }, { pts: P.by_year.map(r => [r.year, r.mkt_p]), color: "#d20a0a", dots: true }], h: 220, yfmt: v => v.toFixed(3), xfmt: v => Math.round(v) })}
    <div class="legend"><span><i style="background:#2f6bff"></i>Model + markt</span><span><i style="background:#d20a0a"></i>Markt</span><span><i style="background:#8a919c"></i>Model zonder odds</span></div></div>`;
  const seg = `<div class="card tw"><h3>Per segment (backtest-bets)</h3><table><tr><th>Segment</th><th class="num">Bets</th><th class="num">Winst%</th><th class="num">ROI</th><th>Significant</th></tr>${P.segments.map(s => `<tr><td>${esc(s.segment)}</td><td class="num">${s.bets}</td><td class="num">${pct(s.hit)}</td><td class="num ${s.roi >= 0 ? "up" : "down"}">${spct(s.roi)}</td><td>${s.significant ? `<span class="tag ok">ja</span>` : `<span class="tag">te weinig</span>`}</td></tr>`).join("")}</table><div class="note">Pas vanaf ~300 bets zegt een segment iets. Niet gaan cherry-picken op toeval.</div></div>`;
  const miss = `<div class="card tw"><h3>Grootste missers</h3><table><tr><th>Datum</th><th>Gevecht</th><th>Pick model</th><th class="num">Kans</th></tr>${P.misses.map(m => `<tr><td>${fdateShort(m.date)}</td><td>${esc(m.fight)}</td><td>${esc(m.pick)}</td><td class="num down">${pct(m.prob)}</td></tr>`).join("")}</table></div>`;
  let body = "";
  if (tab === "overzicht") body = kp + `<div class="grid g3">${cal}${roi}${imp(6)}</div><div class="grid g2" style="margin-top:14px">${comp}${ll}</div>`;
  if (tab === "kalibratie") body = `<div class="grid g2">${cal}${ll}</div><div style="margin-top:14px">${comp}</div>`;
  if (tab === "features") body = imp(15);
  if (tab === "segmenten") body = `<div class="grid g2">${seg}${miss}</div>`;
  return ph("Modelprestaties (backtest)", { sub: `Walk-forward backtest: per jaar getraind op alleen eerdere gevechten. Model ${esc(D.meta.version)}.` }) +
    `<div class="advice" style="margin:0 0 14px"><span class="warn">⚠</span>Dit is een <b>simulatie op historische data</b>, geen echte resultaten. Het model zet pas sinds 5 december 2026 (virtueel) in; die echte resultaten staan op het Overzicht en in de Bet-log.</div>` +
    `<div class="tabs">${[["overzicht", "Overzicht"], ["kalibratie", "Kalibratie"], ["features", "Feature importance"], ["segmenten", "Segmenten & missers"]].map(([k, l]) => `<button class="tab ${k === tab ? "on" : ""}" data-ptab="${k}">${l}</button>`).join("")}</div>` + body + disclaimer;
}

/* ------------------------------------------------------------ 8. backtest-verkenner */
function runBacktest(cfg, col) {
  const R = BT.rows, c = Object.fromEntries(BT.cols.map((k, i) => [k, i]));
  let bank = 1000, peak = 1000, mdd = 0, n = 0, wins = 0, staked = 0; const pts = [[new Date(R[0][c.date]).getTime(), 1000]];
  let curDate = null, evStake = 0;
  for (const r of R) {
    const date = r[c.date]; if (date !== curDate) { curDate = date; evStake = 0; }
    const da = amToDec(r[c.odds_a]), db = amToDec(r[c.odds_b]), mkt = r[c.mkt_p], y = r[c.y];
    let p, sideA, dec, pp;
    if (col === "fav") { sideA = da <= db; dec = sideA ? da : db; const stake = 10; const won = (y === 1) === sideA; bank += won ? stake * (dec - 1) : -stake; n++; wins += won; staked += stake; peak = Math.max(peak, bank); mdd = Math.max(mdd, 1 - bank / peak); pts.push([new Date(date).getTime(), bank]); continue; }
    p = r[c[col]]; const ea = p - mkt, eb = (1 - p) - (1 - mkt); sideA = ea >= eb; const edge = sideA ? ea : eb;
    if (edge < cfg.edge) continue;
    dec = sideA ? da : db; pp = sideA ? p : 1 - p;
    const k = ((dec - 1) * pp - (1 - pp)) / (dec - 1);
    let stake = Math.max(0, Math.min(k * cfg.kelly, cfg.maxBet)) * bank;
    stake = Math.min(stake, Math.max(0, cfg.maxEvent * bank - evStake)); if (stake <= 0) continue;
    evStake += stake; const won = (y === 1) === sideA;
    bank += won ? stake * (dec - 1) : -stake; n++; wins += won; staked += stake;
    peak = Math.max(peak, bank); mdd = Math.max(mdd, 1 - bank / peak); pts.push([new Date(date).getTime(), bank]);
  }
  return { pts: pts.filter((_, i) => i % 3 === 0 || i === pts.length - 1), n, hit: n ? wins / n : null, roi: staked ? (bank - 1000) / staked : null, bank, mdd };
}
function pageBacktest() {
  const cfg = { edge: S.edge, kelly: S.kelly, maxBet: S.maxBet, maxEvent: S.maxEvent, model: "mm", ...loadJSON("fm_btcfg", {}) };
  const sl = (k, l, min, max, step, fmt) => `<label>${l}</label><div class="slider"><input type="range" min="${min}" max="${max}" step="${step}" value="${cfg[k]}" data-bt="${k}"><b id="btv_${k}">${fmt(cfg[k])}</b></div>`;
  return ph("Backtest-verkenner", { sub: "Speel met de instellingen en zie wat het historisch (2017-2026, op slotodds) had opgeleverd. Verleden is geen garantie." }) + `
  <div class="grid g12"><div class="card"><h3>Instellingen</h3>
    <label>Model</label><select data-btm style="width:100%;margin:6px 0 14px"><option value="mm" ${cfg.model === "mm" ? "selected" : ""}>Model + markt</option><option value="blend" ${cfg.model === "blend" ? "selected" : ""}>Model zonder odds</option></select>
    ${sl("edge", "Edge-drempel", 0, .15, .005, v => pct(v, 1))}${sl("kelly", "Kelly-fractie", .05, 1, .05, v => num(v, 2))}${sl("maxBet", "Per bet maximaal (bankroll)", .005, .1, .005, v => pct(v, 1))}${sl("maxEvent", "Per event maximaal (bankroll)", .01, .3, .01, v => pct(v, 0))}
    <button class="btn" id="btrun" style="width:100%;justify-content:center">Backtest uitvoeren</button></div>
    <div class="card"><h3>Resultaat</h3><div id="btres"><div class="empty">Laden…</div></div></div></div>` + disclaimer;
}
async function drawBacktest() {
  if (!BT) BT = await fetch("data/backtest.json?t=" + Date.now(), { cache: "no-store" }).then(r => r.json());
  const cfg = { edge: S.edge, kelly: S.kelly, maxBet: S.maxBet, maxEvent: S.maxEvent, model: "mm", ...loadJSON("fm_btcfg", {}) };
  const cur = runBacktest(cfg, cfg.model), cons = runBacktest({ edge: .05, kelly: .125, maxBet: .01, maxEvent: .04 }, cfg.model), fav = runBacktest(cfg, "fav");
  const row = (l, r, c) => `<tr><td><i style="display:inline-block;width:10px;height:10px;background:${c};border-radius:2px"></i> ${l}</td><td class="num">${r.n}</td><td class="num">${pct(r.hit)}</td><td class="num ${r.roi >= 0 ? "up" : "down"}">${spct(r.roi)}</td><td class="num">${eur(r.bank)}</td><td class="num">${pct(r.mdd, 0)}</td></tr>`;
  $("#btres").innerHTML = lineChart({ series: [{ pts: fav.pts, color: "#8a919c", dash: "4 4", width: 1.6 }, { pts: cons.pts, color: "#2f6bff" }, { pts: cur.pts, color: "#22c55e", area: true }], h: 260, yfmt: v => "€" + Math.round(v).toLocaleString("nl-NL"), xfmt: v => new Date(v).getFullYear(), baseline: 1000 }) +
    `<div class="tw"><table><tr><th>Strategie</th><th class="num">Bets</th><th class="num">Winst%</th><th class="num">ROI</th><th class="num">Eindstand</th><th class="num">Max drawdown</th></tr>${row("Jouw instellingen", cur, "#22c55e")}${row("Conservatief (5% edge, ⅛ Kelly)", cons, "#2f6bff")}${row("Altijd favoriet (flat €10)", fav, "#8a919c")}</table></div>
    <div class="note">Gesimuleerd op slotodds uit de data. In het echt zet je eerder in (andere odds) en beperken bookmakers winnende spelers.</div>`;
}

/* ------------------------------------------------------------ 9. nieuws & kamp */
function pageNieuws() {
  const tab = loadJSON("fm_ntab", "vlaggen");
  const flags = allFights().filter(f => f.card !== "onbevestigd").flatMap(f => (f.flags || []).filter(x => x.type !== "data").map(x => ({ ...x, f })));
  const icon = { debuut: "🆕", layoff: "⏸", blessure: "🩹", gewicht: "⚖", kamp: "🏠" };
  return ph("Nieuws & kamp") + `<div class="tabs"><button class="tab ${tab === "feed" ? "on" : ""}" data-ntab="feed">Nieuwsfeed (0)</button><button class="tab ${tab === "vlaggen" ? "on" : ""}" data-ntab="vlaggen">Kampvlaggen (${flags.length})</button></div>
  ${tab === "feed" ? `<div class="card"><div class="empty"><b>Nieuwsfeed nog niet gekoppeld</b><br><br>In fase 7 haalt een script nieuws op (MMA-sites, persconferenties, weigh-ins) en vat Claude elk bericht samen tot een voorgestelde vlag:<br>kampwissel · blessure · korte voorbereiding · gewichtsprobleem · privéomstandigheden.<br>Jij accepteert of wijst af; alleen geaccepteerde vlaggen tellen mee in het model.</div></div>`
    : `<div class="grid g2"><div class="card tw"><h3>Kampvlaggen (automatisch)</h3><table><tr><th>Vechter</th><th>Vlag</th><th>Betekenis</th><th>Gevecht</th></tr>
      ${flags.map(x => `<tr class="cl" data-href="#/matchup/${x.f.id}"><td><b>${esc(x.fighter || "–")}</b></td><td><span class="tag flag">${icon[x.type] || "⚠"} ${esc(x.type)}</span></td><td>${esc(x.text)}</td><td class="rec">${esc(last(x.f.a.name))} vs ${esc(last(x.f.b.name))}</td></tr>`).join("") || `<tr><td colspan="4" class="mut">Geen vlaggen</td></tr>`}</table></div>
      <div class="card"><h3>Hoe vlaggen werken</h3><div class="srow"><span class="tag flag">🆕 debuut</span><span style="flex:1">Geen UFC-statistieken: het model leunt dan op gemiddelden. Lage betrouwbaarheid.</span></div>
      <div class="srow"><span class="tag flag">⏸ layoff</span><span style="flex:1">Meer dan een jaar verschil in tijd sinds het laatste gevecht (ringroest).</span></div>
      <div class="srow"><span class="tag">data</span><span style="flex:1">Statistieken lopen t/m 8 aug 2026: recentere gevechten ontbreken nog.</span></div>
      <div class="note">Handmatige vlaggen (blessure, kampwissel, weigh-in) volgen met de nieuwsfeed.</div></div></div>`}` + disclaimer;
}

/* ------------------------------------------------------------ 10. data-status */
function pageData() {
  const st = D.status, c = st.counts, g = st.gaps;
  const lbl = { ok: "✔ Up-to-date", achter: "⚠ Verouderd", deels: "⚠ Deels", fout: "✖ Fout", uit: "– Nog niet actief" };
  return ph("Data-status", { sub: `Laatste export: ${D.meta.generated_at.replace("T", " ")} · model ${esc(D.meta.version)} getraind t/m ${fdate(D.meta.trained_until)}` }) + `
  <div class="grid g3">${st.sources.map(s => `<div class="card"><div class="mut" style="font-size:12px;font-weight:700">${esc(s.name)}</div><div class="st ${s.status}" style="font-size:15px;margin:6px 0">${lbl[s.status] || s.status}</div><div class="rec">${esc(s.source)}${s.until ? " · t/m " + fdate(s.until) : ""}</div><div class="rec">${esc(s.note)}</div></div>`).join("")}</div>
  <div class="grid g2" style="margin-top:14px">
    <div class="card"><h3>Database</h3>${Object.entries(c).map(([k, v]) => `<div class="srow"><span>${esc(k)}</span><b>${Number(v).toLocaleString("nl-NL")}</b></div>`).join("")}</div>
    <div class="card"><h3>Datapijplijn</h3>${st.pipeline.map(p => `<div class="srow"><span>${esc(p.step)}</span><span class="st ${p.ok ? "ok" : "uit"}">${p.ok ? "✔" : "○ nog niet"}</span></div>`).join("")}</div>
    <div class="card"><h3>Gaten in de data</h3>
      <div class="srow"><span>Vechters zonder reach</span><b>${g.fighters_no_reach}</b></div><div class="srow"><span>Vechters zonder geboortedatum</span><b>${g.fighters_no_dob}</b></div>
      <div class="srow"><span>Gevechten zonder odds (mrt 2010 - mrt 2026)</span><b>${g.fights_no_odds_since_2010}</b></div><div class="srow"><span>Odds niet te koppelen aan gevecht</span><b>${g.odds_unmatched}</b></div>
      <div class="srow"><span>Events zonder statistieken</span><b>${g.events_no_stats}</b></div></div>
    <div class="card"><h3>Bijwerken</h3><div class="note" style="margin:0 0 10px">De site is statisch; bijwerken gebeurt lokaal en daarna push naar GitHub:</div>
      <pre style="background:var(--bg2);border:1px solid var(--line);border-radius:8px;padding:12px;overflow:auto;font-size:12px">.venv/bin/python -m src.importers.kaggle --download
.venv/bin/python -m src.models.train
.venv/bin/python -m src.predict.upcoming
.venv/bin/python -m src.export.site_data
git add docs && git commit -m "Data update" && git push</pre></div>
  </div>` + disclaimer;
}

/* ------------------------------------------------------------ 11. instellingen */
function pageInstellingen() {
  const books = ["Unibet", "Bet365", "TOTO", "Holland Casino", "BetCity", "Jacks"];
  return ph("Instellingen", { sub: "Opgeslagen in deze browser. Adviezen en inzetten op de hele site rekenen direct met deze waarden." }) + `
  <div class="grid g2"><div class="card"><h3>Betting & bankroll</h3><div class="form">
    <label>Startbankroll (€)</label><input type="number" data-set="bankroll" value="${S.bankroll}" min="10" step="10">
    <label>Kelly-fractie</label><select data-set="kelly">${[[.125, "⅛ Kelly"], [.25, "¼ Kelly"], [.5, "½ Kelly"], [1, "Volle Kelly (riskant)"]].map(([v, l]) => `<option value="${v}" ${S.kelly == v ? "selected" : ""}>${l}</option>`).join("")}</select>
    <label>Edge-drempel (%)</label><input type="number" data-set="edge" data-pct value="${(S.edge * 100).toFixed(1)}" min="0" max="20" step="0.5">
    <label>Max. inzet per gevecht (% bankroll)</label><input type="number" data-set="maxBet" data-pct value="${(S.maxBet * 100).toFixed(1)}" min="0.5" max="10" step="0.5">
    <label>Max. inzet per event (% bankroll)</label><input type="number" data-set="maxEvent" data-pct value="${(S.maxEvent * 100).toFixed(1)}" min="1" max="30" step="1">
  </div></div>
  <div class="card"><h3>Algemeen</h3><div class="form">
    <label>Tijdzone</label><select data-set="tz"><option>Europe/Amsterdam</option></select>
    <label>Odds-formaat</label><select data-set="oddsFmt"><option value="dec" ${S.oddsFmt === "dec" ? "selected" : ""}>Decimaal (1,68)</option><option value="am" ${S.oddsFmt === "am" ? "selected" : ""}>Amerikaans (−147)</option></select>
  </div>
  <h3 style="margin-top:18px">Bookmakers (alleen met KSA-vergunning)</h3>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">${books.map(b => `<label class="toggle"><input type="checkbox" data-book="${b}" ${S.books.includes(b) ? "checked" : ""}> ${b}</label>`).join("")}</div>
  <div class="note">Odds per bookmaker komen van BestFightOdds; in de matchup-pagina zie je ze naast elkaar. Van deze lijst staat daar nu alleen Unibet tussen.</div>
  <div style="margin-top:18px;display:flex;gap:8px"><button class="btn ghost" id="reset">Standaardwaarden</button><button class="btn ghost" id="clearbets">Bet-log wissen</button></div></div></div>` + disclaimer;
}

/* ------------------------------------------------------------ router */
const ROUTES = { overzicht: pageOverzicht, events: pageEvents, fightcard: pageFightcard, matchup: pageMatchup, vechters: pageVechter,
  bets: pageBets, prestaties: pagePrestaties, backtest: pageBacktest, nieuws: pageNieuws, data: pageData, instellingen: pageInstellingen };
let cdTimer = null;
function render() {
  const [, r = "overzicht", arg] = (location.hash || "#/overzicht").split("/");
  const fn = ROUTES[r] || pageOverzicht;
  renderNav(ROUTES[r] ? r : "overzicht");
  page().innerHTML = fn(arg ? decodeURIComponent(arg) : undefined);
  $("#side").classList.remove("open");
  wire(r);
  window.scrollTo(0, 0);
}
function rerender() { const y = window.scrollY; render(); window.scrollTo(0, y); }
function setKV(k, v) { saveJSON(k, v); rerender(); }
function wire(r) {
  page().querySelectorAll("[data-href]").forEach(el => el.onclick = () => location.hash = el.dataset.href);
  page().querySelectorAll("[data-chart]").forEach(el => el.onclick = () => setKV("fm_chart", el.dataset.chart));
  page().querySelectorAll("[data-evtab]").forEach(el => el.onclick = () => setKV("fm_evtab", el.dataset.evtab));
  page().querySelectorAll("[data-evyear]").forEach(el => el.onchange = () => setKV("fm_evyear", el.value));
  page().querySelectorAll("[data-evtype]").forEach(el => el.onchange = () => setKV("fm_evtype", el.value));
  page().querySelectorAll("[data-evbets]").forEach(el => el.onchange = () => setKV("fm_evbets", el.checked));
  page().querySelectorAll("[data-fcf]").forEach(el => el.onclick = () => setKV("fm_fcfilter", el.dataset.fcf));
  page().querySelectorAll("[data-ftab]").forEach(el => el.onclick = () => setKV("fm_ftab", el.dataset.ftab));
  page().querySelectorAll("[data-ptab]").forEach(el => el.onclick = () => setKV("fm_ptab", el.dataset.ptab));
  page().querySelectorAll("[data-ntab]").forEach(el => el.onclick = () => setKV("fm_ntab", el.dataset.ntab));
  page().querySelectorAll("[data-betf]").forEach(el => el.onclick = () => setKV("fm_betfilter", el.dataset.betf));
  page().querySelectorAll("[data-addbet]").forEach(el => el.onclick = () => { addBetFromFight(el.dataset.addbet); location.hash = "#/bets"; render(); });
  page().querySelectorAll("[data-res]").forEach(el => el.onchange = () => { const b = LOCAL_BETS.find(x => x.id === el.dataset.res); b.result = el.value; saveJSON("fm_bets", LOCAL_BETS); rerender(); });
  page().querySelectorAll("[data-close]").forEach(el => el.onchange = () => { const b = LOCAL_BETS.find(x => x.id === el.dataset.close); b.closing = el.value ? +el.value : null; saveJSON("fm_bets", LOCAL_BETS); rerender(); });
  page().querySelectorAll("[data-del]").forEach(el => el.onclick = () => { if (confirm("Deze virtuele bet verwijderen?")) { LOCAL_BETS = LOCAL_BETS.filter(x => x.id !== el.dataset.del); saveJSON("fm_bets", LOCAL_BETS); rerender(); } });
  const nb = $("#newbet");
  if (nb) {
    const fill = () => { const f = findFight($("#bf_fight").value); $("#bf_pick").innerHTML = [f.a, f.b].map((x, i) => `<option value="${i}">${esc(x.name)}</option>`).join(""); const o = betOdds(f) ? amToDec(betOdds(f)[0]) : ""; $("#bf_odds").value = o ? o.toFixed(2) : ""; $("#bf_stake").value = Math.round(S.bankroll * .01); };
    nb.onclick = () => { $("#betform").style.display = "block"; fill(); };
    $("#bf_fight").onchange = fill;
    $("#bf_pick").onchange = () => { const f = findFight($("#bf_fight").value), o = $("#bf_pick").value === "0" ? f.odds_a : f.odds_b; $("#bf_odds").value = o != null ? amToDec(o).toFixed(2) : ""; };
    $("#bf_cancel").onclick = () => $("#betform").style.display = "none";
    $("#bf_save").onclick = () => {
      const f = findFight($("#bf_fight").value), i = $("#bf_pick").value, odds = +$("#bf_odds").value, stake = +$("#bf_stake").value;
      if (!(odds > 1) || !(stake > 0)) { alert("Vul geldige odds en inzet in."); return; }
      LOCAL_BETS.push({ id: Date.now().toString(36), fight_id: f.id, date: f.event.date, event: f.event.name.split(":")[0], fight: `${f.a.name} vs ${f.b.name}`, pick: i === "0" ? f.a.name : f.b.name, odds, stake, result: "open", model: D.meta.version, placed: new Date().toISOString(), manual: true });
      saveJSON("fm_bets", LOCAL_BETS); rerender();
    };
    $("#exportcsv").onclick = () => {
      const cols = ["date", "event", "fight", "pick", "odds", "stake", "result", "closing", "model", "placed"];
      const csv = [cols.join(";"), ...LOCAL_BETS.map(b => cols.map(c => String(b[c] ?? "").replace(/;/g, ",")).join(";"))].join("\n");
      const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" })); a.download = "fightmodel-bets.csv"; a.click();
    };
  }
  if (r === "backtest") {
    const cfgGet = () => ({ edge: S.edge, kelly: S.kelly, maxBet: S.maxBet, maxEvent: S.maxEvent, model: "mm", ...loadJSON("fm_btcfg", {}) });
    const fmts = { edge: v => pct(v, 1), kelly: v => num(v, 2), maxBet: v => pct(v, 1), maxEvent: v => pct(v, 0) };
    page().querySelectorAll("[data-bt]").forEach(el => el.oninput = () => { const c = cfgGet(); c[el.dataset.bt] = +el.value; saveJSON("fm_btcfg", c); $("#btv_" + el.dataset.bt).textContent = fmts[el.dataset.bt](+el.value); });
    page().querySelector("[data-btm]").onchange = e => { const c = cfgGet(); c.model = e.target.value; saveJSON("fm_btcfg", c); drawBacktest(); };
    $("#btrun").onclick = drawBacktest;
    drawBacktest();
  }
  page().querySelectorAll("[data-set]").forEach(el => el.onchange = () => { let v = el.type === "number" ? +el.value : el.value; if (el.dataset.pct !== undefined) v = v / 100; if (el.dataset.set === "kelly") v = +v; S[el.dataset.set] = v; saveJSON("fm_settings", S); });
  page().querySelectorAll("[data-book]").forEach(el => el.onchange = () => { S.books = el.checked ? [...new Set([...S.books, el.dataset.book])] : S.books.filter(b => b !== el.dataset.book); saveJSON("fm_settings", S); });
  if ($("#reset")) $("#reset").onclick = () => { S = { ...DEF }; saveJSON("fm_settings", S); rerender(); };
  if ($("#clearbets")) $("#clearbets").onclick = () => { if (confirm("Alle virtuele bets in deze browser wissen?")) { LOCAL_BETS = []; saveJSON("fm_bets", []); rerender(); } };
  clearInterval(cdTimer);
  if ($("#cd")) {
    const t = eventStart(nextEvent());
    const tick = () => { const ms = t - new Date(); if (!$("#cd")) return clearInterval(cdTimer); if (ms <= 0) { $("#cd").textContent = "Bezig / afgelopen"; return; } const d = Math.floor(ms / 864e5), h = Math.floor(ms % 864e5 / 36e5), m = Math.floor(ms % 36e5 / 6e4); $("#cd").textContent = `${d}d ${String(h).padStart(2, "0")}u ${String(m).padStart(2, "0")}m`; };
    tick(); cdTimer = setInterval(tick, 30000);
  }
}

/* ------------------------------------------------------------ zoeken */
function wireSearch() {
  const q = $("#q"), box = $("#sres");
  q.oninput = () => {
    const s = q.value.trim().toLowerCase();
    if (s.length < 2) { box.style.display = "none"; return; }
    const fr = Object.values(D.fighters).filter(f => f.name.toLowerCase().includes(s)).slice(0, 6).map(f => `<a href="#/vechters/${f.id}">🥊 ${esc(f.name)} <span class="rec">${esc(f.weight_class)}</span></a>`);
    const ev = D.events.filter(e => !e.none && e.name.toLowerCase().includes(s)).map(e => `<a href="#/fightcard/${e.id}">📅 ${esc(e.name)}</a>`);
    const pe = D.past_events.filter(e => e.name.toLowerCase().includes(s)).slice(0, 4).map(e => `<a href="#/events">📁 ${esc(e.name)} <span class="rec">${fdate(e.date)}</span></a>`);
    const all = [...fr, ...ev, ...pe];
    box.innerHTML = all.join("") || `<a class="mut">Niets gevonden (alleen vechters op komende kaarten)</a>`;
    box.style.display = "block";
  };
  box.onclick = () => { box.style.display = "none"; q.value = ""; };
  document.addEventListener("click", e => { if (!e.target.closest(".search")) box.style.display = "none"; });
  $("#burger").onclick = () => $("#side").classList.toggle("open");
}

/* ------------------------------------------------------------ start */
fetch("data/site.json?t=" + Date.now(), { cache: "no-store" }).then(r => r.json()).then(d => {
  D = d;
  $("#ver").textContent = d.meta.version;
  $("#upd").textContent = "Data bijgewerkt: " + fdate(d.meta.generated_at.slice(0, 10)) + " " + d.meta.generated_at.slice(11, 16);
  wireSearch();
  window.addEventListener("hashchange", render);
  render();
}).catch(err => { page().innerHTML = `<div class="empty">Kon data niet laden (${esc(err.message)}). Open de site via een webserver, niet als los bestand.</div>`; });
