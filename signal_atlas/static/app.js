"use strict";
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const TZ = "America/New_York";
  const COLORS = ["#0E6862", "#B08A4A", "#1F3B5A", "#8C3B3B", "#6B7A8F"];
  const CLAIM = { primary: "Primary", corroborated: "Corroborated", reported: "Reported" };
  const TYPE = { regulatory_filing: "Filing", podcast: "Podcast", newsletter_analysis: "Newsletter", news_brief: "News brief",
    news_headline: "Headline", pricing_dataset: "Pricing dataset", adoption_dataset: "Adoption dataset" };
  const STATIC = document.documentElement.dataset.mode === "static";
  const safeId = (s) => s.replace(/[^A-Za-z0-9_-]/g, "_");
  function staticPath(p) {
    const u = new URL(p, "http://x"), path = u.pathname;
    if (path === "/api/edition") return `api/edition/${u.searchParams.get("date") || "latest"}.json`;
    if (path.startsWith("/api/series/")) return `api/series/${safeId(decodeURIComponent(path.slice(12)))}.json`;
    if (path === "/api/leads") return "api/leads.json";
    return `${path.slice(1)}.json`;
  }
  const state = { editions: [], edition: null, status: null, leads: [], q: "", sector: null, aud: null, conf: null, active: 0,
    openId: null, lastFocus: null, seriesCache: new Map() };

  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : String(kid));
    return el;
  }
  const svg = (tag, attrs) => { const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v); return el; };
  async function api(path, opts) {
    const r = await fetch(STATIC ? staticPath(path) : path, opts);
    if (!r.ok) { const e = new Error(`HTTP ${r.status}`); e.status = r.status; try { e.body = await r.json(); } catch {} throw e; }
    return r.json();
  }
  const d = (s) => (s ? new Date(s.length === 10 ? s + "T12:00:00Z" : s) : null);
  const fmtDay = (s) => s ? d(s).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: s.length === 10 ? "UTC" : TZ }) : "—";
  const fmtLong = (s) => d(s).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric", timeZone: "UTC" });
  const fmtDT = (s) => s ? d(s).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: TZ }) + " ET" : "—";
  function rel(s) {
    if (!s) return "never";
    const m = Math.round((Date.now() - d(s).getTime()) / 60000);
    if (Math.abs(m) < 1) return "just now";
    if (m < 0) { const f = -m; return f < 60 ? `in ${f}m` : f < 2880 ? `in ${Math.round(f / 60)}h` : `in ${Math.round(f / 1440)}d`; }
    return m < 60 ? `${m}m ago` : m < 2880 ? `${Math.round(m / 60)}h ago` : `${Math.round(m / 1440)}d ago`;
  }
  function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 2200); }

  // ---------- small components ----------
  const confMeter = (c) => { const n = { High: 3, Medium: 2, Low: 1 }[c] || 0;
    return h("span", { class: "conf", "aria-hidden": "true" }, [1, 2, 3].map((i) => h("i", { class: i <= n ? "on" : "" }))); };



  const kicker = (sig) => h("div", { class: "kicker" }, sig.sector, h("span", { class: "sep" }, "/"), sig.direction,
    sig.is_new_in_edition ? [" ", h("span", { class: "tag tag--new" }, "New")] : null);

  // ---------- chart (only from sourced series) ----------
  async function loadSeries(ids) {
    const out = [];
    for (const id of ids) {
      if (!state.seriesCache.has(id)) state.seriesCache.set(id, api(`/api/series/${encodeURIComponent(id)}`).catch(() => null));
      const s = await state.seriesCache.get(id);
      if (s && s.points.length >= 2) out.push(s);
    }
    return out;
  }
  async function chart(sig, host) {
    if (!sig.chart) return;
    const series = await loadSeries(sig.chart.series);
    if (!series.length) {
      host.append(h("p", { class: "chart-empty" }, "Chart appears once its source series has been ingested. Nothing is drawn without retrieved data."));
      return;
    }
    const W = 640, H = 240, P = { l: 40, r: 56, t: 12, b: 26 };
    const days = [...new Set(series.flatMap((s) => s.points.map((p) => p.day)))].sort();
    const vals = series.flatMap((s) => s.points.map((p) => p.value));
    let lo = Math.min(...vals), hi = Math.max(...vals); const pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad;
    const x = (day) => P.l + (days.indexOf(day) / Math.max(1, days.length - 1)) * (W - P.l - P.r);
    const y = (v) => P.t + (1 - (v - lo) / (hi - lo)) * (H - P.t - P.b);
    const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img",
      "aria-label": series.map((s) => `${s.label}: ${s.points[0].value.toFixed(1)} on ${s.points[0].day} to ${s.points.at(-1).value.toFixed(1)} on ${s.points.at(-1).day}`).join("; ") });
    for (let i = 0; i <= 4; i++) {
      const v = lo + ((hi - lo) * i) / 4, yy = y(v);
      root.append(svg("line", { class: "grid", x1: P.l, x2: W - P.r, y1: yy, y2: yy }));
      const t = svg("text", { x: P.l - 6, y: yy + 4, "text-anchor": "end" }); t.textContent = Math.round(v); root.append(t);
    }
    [0, Math.floor((days.length - 1) / 2), days.length - 1].forEach((i, k) => {
      const t = svg("text", { x: x(days[i]), y: H - 6, "text-anchor": k === 0 ? "start" : k === 2 ? "end" : "middle" });
      t.textContent = fmtDay(days[i]).replace(/, \d{4}$/, ""); root.append(t);
    });
    const ends = [];
    series.forEach((s, i) => {
      const dpath = s.points.map((p, j) => `${j ? "L" : "M"}${x(p.day).toFixed(1)},${y(p.value).toFixed(1)}`).join("");
      const path = svg("path", { class: "line", d: dpath, stroke: COLORS[i % COLORS.length] });
      path.style.setProperty("--len", "2000"); root.append(path);
      const last = s.points.at(-1); ends.push({ x: x(last.day) + 6, y: y(last.value) + 4, v: last.value });
    });
    ends.sort((a, b) => a.y - b.y).forEach((e, i, arr) => { if (i && e.y - arr[i - 1].y < 12) e.y = arr[i - 1].y + 12;
      const t = svg("text", { x: e.x, y: e.y }); t.textContent = e.v.toFixed(0); root.append(t); });
    const src = series[0];
    host.append(h("figure", { class: "chart" }, root,
      h("div", { class: "legend" }, series.map((s, i) => { const sw = h("i"); sw.style.background = COLORS[i % COLORS.length];
        return h("span", {}, sw, `${s.label} — ${s.points.at(-1).value.toFixed(1)} (${s.points.at(-1).day})`); })),
      h("figcaption", {}, `${sig.chart.caption} Unit: ${src.unit}. ${days.length} daily observations, ${days[0]} → ${days.at(-1)}; retrieved ${fmtDT(src.updated_at)}. `,
        h("a", { href: src.source_url, target: "_blank", rel: "noopener noreferrer" }, src.attribution), ".")));
  }

  // ---------- rendering ----------
  const ROLE = { buyer: "Likely buyer", benefits: "Benefits", pressure: "Faces pressure" };
  const ROLE_ORDER = { buyer: 0, pressure: 1, benefits: 2 };
  const audiences = (s) => s.audiences || [];
  function filtered() {
    const q = state.q.trim().toLowerCase();
    return state.edition.signals.filter((s) => {
      if (state.sector && s.sector !== state.sector) return false;
      if (state.aud && !audiences(s).some((a) => a.segment === state.aud)) return false;
      if (state.conf && s.confidence !== state.conf) return false;
      if (!q) return true;
      const hay = [s.title, s.dek, s.takeaway, s.sector, s.what_changed, s.market_indication, s.card_implication,
        ...(s.themes || []), ...(s.value_chain || []),
        ...audiences(s).flatMap((a) => [a.segment, a.who, a.impact, a.action]),
        ...(s.implications || []).flatMap((i) => Object.values(i)),
        ...s.evidence.flatMap((e) => [e.statement, e.title, e.source_name])].join(" ").toLowerCase();
      return q.split(/\s+/).every((t) => hay.includes(t));
    });
  }
  const confLine = (s) => h("span", {}, confMeter(s.confidence), `${s.confidence} confidence`);
  function audList(s, opts = {}) {
    const a = audiences(s); if (!a.length) return null;
    return h("div", { class: "aud" + (opts.dark ? " aud--dark" : "") }, h("span", { class: "aud__label" }, "Matters to"),
      h("ul", {}, a.map((x) => h("li", { class: `aud__i aud__i--${x.role}`, title: ROLE[x.role] }, x.segment,
        h("span", { class: "sr-only" }, ` (${ROLE[x.role]})`)))));
  }
  function stamps(s, compact) {
    const rows = [];
    if (state.status?.last_success_at) rows.push(["Data fetched", rel(state.status.last_success_at), fmtDT(state.status.last_success_at)]);
    if (s.evidence_reviewed_at) rows.push(["Evidence reviewed", fmtDT(s.evidence_reviewed_at), fmtDT(s.evidence_reviewed_at)]);
    if (s.updated_at) rows.push(["Thesis revised", fmtDT(s.updated_at), fmtDT(s.updated_at)]);
    return h("dl", { class: "stamps" + (compact ? " stamps--compact" : ""), title: "Fetching data does not re-review a thesis." },
      rows.map(([k, v, t]) => h("div", {}, h("dt", {}, k), h("dd", { title: t }, v))));
  }

  function renderHero() {
    const ed = state.edition, latest = state.editions[0]?.edition_date, note = ed.note;
    $("#editionLabel").textContent = `Edition · ${fmtLong(ed.edition_date)}` + (ed.edition_date !== latest ? " · archived snapshot" : "");
    $("#heroHeadline").textContent = note.headline;
    $("#heroSummary").textContent = note.summary;
    const tk = note.takeaways || [];
    $("#takeawaysLabel").hidden = !tk.length;
    $("#takeawaysLabel").textContent = note.auto ? "Current top theses" : "Three takeaways";
    $("#heroTakeaways").replaceChildren(...tk.map((t) => h("li", {}, t)));
    $("#exportLink").href = `${STATIC ? "" : "/"}api/export/${ed.edition_date}.md`;
    document.title = `Market Trends → Theses — Edition ${fmtDay(ed.edition_date)}`;
    const top = ed.signals[0], lead = $("#leadSignal"); lead.replaceChildren();
    if (!top) return;
    const chartHost = h("div");
    lead.append(h("p", { class: "lead__label" }, "Top thesis"), kicker(top), h("h2", {}, top.title),
      h("p", { class: "lead__takeaway" }, top.takeaway || top.dek),
      top.caveats?.length ? h("p", { class: "lead__caveat" }, h("strong", {}, "Keep in mind: "), top.caveats[0]) : null,
      chartHost,
      h("div", { class: "meta" }, confLine(top), h("span", {}, top.corroboration)),
      h("p", {}, h("button", { class: "btn btn--ghost", type: "button", onclick: () => openSignal(top.id) }, "Read the full thesis →")));
    chart(top, chartHost);
  }
  function renderControls() {
    const sigs = state.edition.signals;
    const sectors = [...new Set(sigs.map((s) => s.sector))];
    const segs = [...new Set(sigs.flatMap((s) => audiences(s).map((a) => a.segment)))];
    const mk = (label, val, key) => h("button", { class: "chip", type: "button", "aria-pressed": String(state[key] === val),
      onclick: () => { state[key] = state[key] === val ? null : val; renderControls(); renderFeed(); } }, label);
    $("#sectorChips").replaceChildren(mk("All", null, "sector"), ...sectors.map((t) => mk(t, t, "sector")));
    $("#audChips").parentElement.hidden = !segs.length;
    $("#audChips").replaceChildren(mk("Everyone", null, "aud"), ...segs.map((t) => mk(t, t, "aud")));
    $("#confFilter").replaceChildren(mk("Any", null, "conf"), ...["High", "Medium", "Low"].map((c) => mk(c, c, "conf")));
  }
  function quiet(s) {
    const c = { primary: 0, corroborated: 0, reported: 0 }, ch = s.evidence.filter((e) => e.stance === "challenges").length;
    s.evidence.forEach((e) => c[e.claim_type]++);
    return h("p", { class: "quiet" }, `${c.primary} primary · ${c.corroborated} corroborated · ${c.reported} reported · ${ch} counter · `,
      h("span", { title: "Editorial prioritization points, not a probability" }, `priority ${s.scores.composite.toFixed(2)}`));
  }
  function renderFeed() {
    const list = $("#feedList"), items = filtered(); list.replaceChildren();
    $("#feedEmpty").hidden = items.length > 0;
    items.forEach((s, i) => {
      const feature = i < 2 && items.length > 2;
      const open = h("button", { class: "item__open", type: "button", "data-id": s.id, onclick: () => openSignal(s.id),
        "aria-label": `${s.title}. Open thesis.` }, kicker(s), h("h3", {}, s.title));
      const impl = s.card_implication ? h("p", { class: "impl" }, h("span", { class: "impl__label" }, "Practical implication"), s.card_implication) : null;
      const body = [open, h("p", { class: "dek" }, s.dek), impl];
      const side = [audList(s), h("div", { class: "meta" }, confLine(s), h("span", {}, s.corroboration)), quiet(s)];
      const rank = h("span", { class: "item__rank", "aria-hidden": "true" }, String(s.rank).padStart(2, "0"));
      const li = feature ? h("li", { class: "item item--feature" }, rank, ...body, ...side)
        : h("li", { class: "item item--row" }, rank, h("div", {}, ...body), h("div", { class: "item__side" }, ...side));
      li.style.animationDelay = `${Math.min(i, 8) * 45}ms`;
      list.append(li);
    });
    state.active = Math.min(state.active, Math.max(0, items.length - 1));
  }
  function whyMatch(m) {
    const t = m.terms;
    if (t && !Array.isArray(t) && t.why) return t.why;
    return Array.isArray(t) && t.length ? `Shared terms: ${t.join(", ")}` : "Matched on shared terms";
  }
  function renderWire() {
    const host = $("#wireList"); host.replaceChildren();
    $("#wireCount").textContent = state.leads.length ? `${state.leads.length} leads, last 3 days` : "";
    if (!state.leads.length) { host.append(h("p", { class: "wire__empty" }, "No ingested leads in the last three days yet. Leads appear after a scheduled ingestion run succeeds.")); return; }
    const groups = new Map();
    state.leads.forEach((l) => { const k = l.cluster_id ?? `d${l.id}`; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(l); });
    const titles = Object.fromEntries(state.edition.signals.map((s) => [s.id, s.title]));
    const MARKET = /\b(ai|gpu|gpus|chip|chips|semiconductor|nvidia|intel|amd|data.?center|cloud|compute|software|saas|pricing|token|tokens|model|models|agent|agents|energy|power|grid|5g|network|telecom|enterprise|earnings|ipo|filing|sec|memory|supply|tariff|robot|automation|fintech|bank|startup|venture|funding|anthropic|openai|spacex|microsoft|google|amazon|meta|apple)\b/i;
    const clusterCard = (g) => {
      const matches = g.flatMap((l) => l.matches || []).filter((m) => m && m.signal);
      const bySig = new Map(); matches.forEach((m) => { if (!bySig.has(m.signal)) bySig.set(m.signal, m); });
      return h("article", { class: "cluster" },
        h("div", {}, h("span", { class: "tag tag--muted" }, TYPE[g[0].source_type] || g[0].source_type), g.length > 1 ? [" ", h("span", { class: "tag" }, `${g.length} related`)] : null),
        h("h3", {}, g[0].title),
        h("ul", {}, g.slice(0, 4).map((l) => h("li", {}, h("span", { class: "src" }, l.source_name || "Source"), " — ",
          h("a", { href: l.url, target: "_blank", rel: "noopener noreferrer" }, l.title),
          h("div", { class: "when" }, `published ${fmtDT(l.published_at)} · first seen ${fmtDT(l.first_seen_at)}`)))),
        bySig.size ? h("div", { class: "match" }, [...bySig.values()].map((m) => h("p", {}, h("strong", {}, "Why this matches: "),
          `${whyMatch(m)} Related thesis: ${titles[m.signal] || m.signal}.`))) : null);
    };
    const matched = (g) => g.some((l) => (l.matches || []).length);
    const score = (g) => (matched(g) ? 4 : 0) + (g.length > 1 ? 2 : 0) + (g.some((l) => MARKET.test(l.title + " " + (l.excerpt || ""))) ? 1 : 0);
    const all = [...groups.values()].sort((a, b) => score(b) - score(a));
    const relevant = all.filter((g) => score(g) > 0), other = all.filter((g) => score(g) === 0);
    host.append(h("p", { class: "wire__sub" }, `Possibly market-relevant (${relevant.length})`), h("div", { class: "wire__grid" }, relevant.slice(0, 24).map(clusterCard)));
    if (other.length) host.append(h("details", { class: "wire__more" }, h("summary", {}, `Other headlines captured (${other.length}), likely off-topic`),
      h("div", { class: "wire__grid" }, other.slice(0, 40).map(clusterCard))));
  }
  function renderMethod() {
    const r = state.edition.ranking;
    $("#rankingMethod").replaceChildren(h("li", {}, r.scale),
      ...Object.entries(r.components).map(([k, v]) => h("li", {}, h("strong", {}, `${k[0].toUpperCase() + k.slice(1)} (${Math.round(r.weights[k] * 100)}%). `), v)));
    $("#sourceList").replaceChildren(...(state.status?.sources || []).map((s) => h("li", {}, h("strong", {}, s.name), ` — ${s.kind}. ${s.access_note || ""}`)));
  }
  function renderStatus() {
    const s = state.status; if (!s) return;
    if (STATIC) s.stale = !!s.last_success_at && Date.now() > d(s.next_scheduled).getTime() + (s.stale_grace_minutes || 90) * 60000;
    const rs = s.refresh_summary, partial = !!(rs && rs.issues.length);
    const pill = $("#statusPill"), never = !s.last_success_at;
    pill.dataset.state = s.running ? "running" : never ? "never" : s.stale ? "stale" : partial ? "partial" : "fresh";
    $("#statusText").textContent = s.running ? "Refreshing data…" : never ? "No data refresh yet"
      : matchMedia("(max-width: 720px)").matches ? `${s.stale ? "Stale · " : ""}Fetched ${rel(s.last_success_at)}${partial ? " · partial" : ""}`
      : `${s.stale ? "Stale · " : ""}Data fetched ${rel(s.last_success_at)}${partial ? ` · ${rs.ok} of ${rs.total} sources` : ""}`;
    const b = $("#staleBanner");
    b.classList.toggle("banner--info", !(never || s.stale) && partial);
    if (never || s.stale) {
      b.hidden = false;
      b.replaceChildren(h("div", { class: "wrap" }, h("strong", {}, never ? "No data refresh has completed yet." : "Data may be stale."),
        h("span", {}, never ? "Showing the reviewed first edition only." : `Last successful data fetch ${fmtDT(s.last_success_at)}; the ${fmtDT(s.previous_slot)} scheduled refresh has not completed. Published theses are preserved.`)));
    } else if (partial) {
      b.hidden = false;
      b.replaceChildren(h("div", { class: "wrap" }, h("strong", {}, "Latest data refresh was partial."),
        h("span", {}, `${rs.ok} of ${rs.total} sources updated ${fmtDT(rs.finished_at)}. ${rs.issues.map((x) => `${x.source}: ${x.reason}`).join("; ")}. Theses are unchanged and were not re-reviewed by this refresh. `,
          h("a", { href: "#pipeline" }, "Diagnostics"))));
    } else b.hidden = true;
    const sch = s.scheduler, lr = s.last_run;
    const kv = [["Schedule", s.schedule], ["Next scheduled", fmtDT(s.next_scheduled)],
      ["Data last fetched", s.last_success_at ? `${fmtDT(s.last_success_at)} (${rel(s.last_success_at)})` : "none yet"],
      ["Latest refresh", rs ? `${rs.status} · ${rs.ok} of ${rs.total} sources ok` : lr ? lr.status : "none"],
      ["Scheduler", STATIC ? "GitHub Actions workflow · 08:00 & 16:00 ET" : sch.alive ? `running · heartbeat ${rel(sch.heartbeat_at)}` : sch.heartbeat_at ? `not responding · last heartbeat ${rel(sch.heartbeat_at)}` : "not detected"],
      ["Freshness", s.stale ? "stale" : "current"],
      ["Archive", `${s.counts.snapshots} snapshots · ${s.counts.documents} documents · ${s.counts.clusters} story clusters`],
      ["Manual refresh", STATIC ? "maintainers only (workflow dispatch)" : s.manual_refresh_enabled ? "enabled (token required)" : "disabled on this server"]];
    $("#pipelineKv").replaceChildren(...kv.flatMap(([k, v]) => [h("dt", {}, k),
      h("dd", { class: /stale|not |failed|partial|none yet|disabled/.test(v) ? "warn" : /running|current|success/.test(v) ? "ok" : "" }, v)]));
    $("#sourceRows").replaceChildren(...s.sources.map((x) => h("tr", {},
      h("td", {}, h("a", { href: x.homepage, target: "_blank", rel: "noopener noreferrer" }, x.name)),
      h("td", {}, x.kind), h("td", {}, x.last_success_at ? rel(x.last_success_at) : "—"),
      h("td", {}, h("span", { class: `badge badge--${x.last_status || "none"}` }, x.last_status || "not run"),
        x.plain_error ? h("span", { class: "err" }, x.plain_error) : null,
        x.plain_error && x.last_error ? h("details", { class: "diag" }, h("summary", {}, "Technical detail"), h("code", {}, x.last_error)) : null))));
    $("#refreshForm").querySelector("button").disabled = !s.manual_refresh_enabled || s.running;
    $("#refreshForm").hidden = STATIC;
  }
  function renderEditionNav() {
    const sel = $("#editionSelect"), cur = state.edition.edition_date;
    sel.replaceChildren(...state.editions.map((e) => h("option", { value: e.edition_date, selected: e.edition_date === cur },
      `${fmtDay(e.edition_date)} · ${e.snapshots} snapshot${e.snapshots > 1 ? "s" : ""}`)));
    const i = state.editions.findIndex((e) => e.edition_date === cur);
    $("#prevEdition").disabled = i < 0 || i >= state.editions.length - 1;
    $("#nextEdition").disabled = i <= 0;
  }

  // ---------- thesis detail ----------
  const ext = (href, text) => h("a", { href, target: "_blank", rel: "noopener noreferrer" }, text);
  function evItem(e) {
    return h("li", {}, h("div", {}, h("span", { class: `claim claim--${e.claim_type}` }, CLAIM[e.claim_type]), " ",
        e.stance === "context" ? h("span", { class: "tag tag--muted" }, "Context") : null),
      h("div", { class: "stmt" }, e.statement),
      h("div", { class: "src" }, ext(e.url, `${e.source_name || "Source"} — ${e.title}`)),
      h("div", { class: "prov" }, `${TYPE[e.source_type] || e.source_type} · published ${e.published_at ? fmtDay(e.published_at.slice(0, 10)) : "n/a"} · event ${e.event_date ? fmtDay(e.event_date) : "n/a"} · first seen ${fmtDT(e.first_seen_at)} · retrieved ${fmtDT(e.retrieved_at)}`));
  }
  const INF = () => h("span", { class: "claim claim--inference" }, "Analyst inference");
  function part(n, id, title, kids, opts = {}) {
    return h("section", { class: "part" + (opts.cls ? ` ${opts.cls}` : ""), "aria-labelledby": id },
      h("h3", { class: "part__title", id }, n ? h("span", { class: "part__num", "aria-hidden": "true" }, n) : null, title, opts.inference ? INF() : null), ...kids);
  }
  const sub = (title, ...kids) => h("div", { class: "subsec" }, h("h4", {}, title), ...kids);
  function sinceLast(s) {
    const c = s.since_last; if (!c) return null;
    const li = [];
    (c.new_evidence || []).forEach((e) => li.push(h("li", {}, h("span", { class: `claim claim--${e.claim_type}` }, CLAIM[e.claim_type]), " New evidence: ", e.statement)));
    (c.revised || []).forEach((r) => li.push(h("li", {}, `${r.what} revised. Previously: “${r.from}”`)));
    if (c.confidence) li.push(h("li", {}, `Confidence changed from ${c.confidence.from} to ${c.confidence.to}.`));
    (c.validation_outcomes || []).forEach((v) => li.push(h("li", {}, `Validation: ${v.outcome || v.step || JSON.stringify(v)}`)));
    (c.open_questions || []).forEach((q) => li.push(h("li", { class: "muted" }, `Still open: ${q}`)));
    return part(null, "pSince", `Since the last edition (${fmtDay(c.previous_edition)})`, [h("ul", { class: "bullets" }, li)], { cls: "part--since" });
  }
  function openSignal(id, push = true) {
    const s = state.edition.signals.find((x) => x.id === id); if (!s) return;
    state.openId = id; state.lastFocus = document.activeElement;
    if (push) history.replaceState(null, "", `#/${state.edition.edition_date}/${id}`);
    const panel = $("#drawerPanel"), chartHost = h("div");
    const sup = s.evidence.filter((e) => e.stance !== "challenges"), ch = s.evidence.filter((e) => e.stance === "challenges");
    const weight = { primary: 0, corroborated: 1, reported: 2 };
    const key = sup.filter((e) => e.stance === "supports").sort((a, b) => weight[a.claim_type] - weight[b.claim_type]).slice(0, 3);
    const copy = async () => {
      try { await navigator.clipboard.writeText(s.thesis_sentence); toast("Thesis sentence copied"); }
      catch { const t = h("textarea", {}, s.thesis_sentence); document.body.append(t); t.select(); document.execCommand("copy"); t.remove(); toast("Thesis sentence copied"); }
    };
    const w = state.edition.ranking.weights;
    const auds = audiences(s).slice().sort((a, b) => ROLE_ORDER[a.role] - ROLE_ORDER[b.role]);
    const impls = s.implications || [];
    panel.replaceChildren(
      h("header", { class: "d-head" },
        h("div", { class: "d-head__top" }, kicker(s), h("button", { class: "d-close", type: "button", "aria-label": "Close thesis", "data-close": "" }, "✕")),
        h("h2", { id: "dTitle" }, s.title),
        h("div", { class: "meta" }, confLine(s), h("span", {}, s.corroboration), h("span", {}, `Priority #${s.rank} in the ${fmtDay(state.edition.edition_date)} edition`))),
      h("div", { class: "d-body" },
        part("1", "pTake", "The takeaway", [
          h("p", { class: "lede" }, s.takeaway || s.dek),
          s.caveats?.length ? h("div", { class: "caveats" }, h("h4", {}, "Keep in mind"), h("ul", {}, s.caveats.map((c) => h("li", {}, c)))) : null,
          stamps(s),
          h("div", { class: "thesis" }, h("div", { class: "thesis__row" }, h("span", { class: "thesis__label" }, "Slide-ready sentence · working hypothesis"),
            h("button", { class: "btn btn--small", type: "button", onclick: copy }, "Copy ", h("kbd", {}, "c"))), h("p", { id: "thesisText" }, s.thesis_sentence))]),
        sinceLast(s),
        auds.length ? part("2", "pWho", "Who this matters to", [
          h("p", { class: "note" }, "Who benefits, who faces pressure and who might buy a solution can be different businesses."),
          h("div", { class: "aud-grid" }, auds.map((a) => h("article", { class: `aud-card aud-card--${a.role}` },
            h("header", {}, h("h4", {}, a.segment), h("span", { class: `role role--${a.role}` }, ROLE[a.role])),
            h("dl", {}, h("dt", {}, "Who"), h("dd", {}, a.who), h("dt", {}, "Impact"), h("dd", {}, a.impact),
              h("dt", {}, "Possible action"), h("dd", {}, a.action), h("dt", {}, "Trigger to watch"), h("dd", {}, a.trigger)))))], { inference: true }) : null,
        part(auds.length ? "3" : "2", "pWhat", "What changed", [
          s.changed_points?.length ? h("ul", { class: "bullets" }, s.changed_points.map((p) => h("li", {}, p))) : h("p", {}, s.what_changed),
          s.chart ? h("div", { class: "chart-wrap" }, chartHost) : null,
          sub(h("span", {}, "Why now ", INF()), h("p", {}, s.why_now)),
          key.length ? sub("Key supporting evidence", h("ul", { class: "ev ev--compact" }, key.map(evItem)), h("p", { class: "note" }, "Full evidence, with timestamps, is under Sources and methodology.")) : null]),
        part(auds.length ? "4" : "3", "pImpl", "Business implications", [
          impls.length ? h("ol", { class: "chains" }, impls.map((i) => h("li", { class: "chain-row" },
            [["Trend", i.trend], ["Business problem", i.problem], ["Buyer", i.buyer], ["Potential solution", i.solution], ["Investigate", i.investigate]]
              .map(([k, v]) => h("div", { class: "chain-step" }, h("span", {}, k), h("p", {}, v))))))
            : h("div", {}, s.startup_opportunity ? sub("Startup opportunity", h("p", {}, s.startup_opportunity)) : null,
              s.corporate_buyer ? sub("Corporate buyer & use case", h("p", {}, s.corporate_buyer)) : null),
          sub("Market indication", h("p", {}, s.market_indication)),
          sub("Next validation step", h("div", { class: "callout" },
            s.customer_validation ? h("p", {}, h("strong", {}, "Customer validation: "), s.customer_validation) : null,
            h("p", {}, h("strong", {}, "Evidence to check: "), s.next_validation)))], { inference: true }),
        part(auds.length ? "5" : "4", "pView", "What could change our view", [
          sub(`Counterevidence (${ch.length})`, h("ul", { class: "ev" }, ch.map(evItem))),
          sub("This would weaken the thesis", h("div", { class: "callout callout--falsify" }, s.falsifier)),
          s.view_triggers?.length ? sub("Validation triggers to watch", h("ul", { class: "bullets" }, s.view_triggers.map((t) => h("li", {}, t)))) : null]),
        part(auds.length ? "6" : "5", "pSrc", "Sources and methodology", [
          h("details", { class: "more" }, h("summary", {}, `Supporting and context evidence (${sup.length})`), h("ul", { class: "ev" }, sup.map(evItem))),
          h("details", { class: "more" }, h("summary", {}, "Confidence rationale"), h("p", {}, s.confidence_rationale)),
          h("details", { class: "more" }, h("summary", {}, "Ranking breakdown"),
            h("p", { class: "note" }, "Editorial prioritization only: these points order the feed and are not probabilities."),
            h("table", { class: "scores" }, h("tbody", {},
              ["novelty", "evidence", "relevance", "impact"].map((k) => h("tr", {}, h("td", {}, `${k[0].toUpperCase() + k.slice(1)} × ${w[k]}`), h("td", {}, s.scores[k].toFixed(2)))),
              h("tr", {}, h("td", {}, h("strong", {}, "Composite priority points")), h("td", {}, h("strong", {}, s.scores.composite.toFixed(2))))))),
          s.value_chain?.length ? h("details", { class: "more" }, h("summary", {}, "Affected value chain"),
            h("div", { class: "chain" }, s.value_chain.flatMap((v, i) => [i ? h("i", { "aria-hidden": "true" }, "→") : null, h("span", {}, v)]))) : null,
          h("details", { class: "more" }, h("summary", {}, `Unreviewed mentions (${s.unreviewed_mentions.length}) — not evidence`),
            s.unreviewed_mentions.length
              ? h("ul", { class: "mentions" }, s.unreviewed_mentions.map((m) => h("li", {}, ext(m.url, m.title), ` — ${m.source_name || ""}, seen ${fmtDT(m.matched_at)}`, h("div", { class: "note" }, whyMatch(m)))))
              : h("p", {}, "None. New leads that name a thesis-specific term appear here for review; they never count as evidence.")),
          s.discovery ? h("p", { class: "note" }, "First surfaced via ", ext(s.discovery.url, s.discovery.label), ". Discovery sources are treated as reported narratives until validated.") : null,
          h("p", { class: "note" }, `First published ${fmtDT(s.first_published_at)} · revised ${fmtDT(s.updated_at)} · ${s.revision_count} saved revision${s.revision_count === 1 ? "" : "s"}.`)])));
    $("#drawer").hidden = false; document.body.style.overflow = "hidden";
    panel.scrollTop = 0; panel.focus();
    chart(s, chartHost);
  }
  function closeSignal() {
    if ($("#drawer").hidden) return;
    $("#drawer").hidden = true; document.body.style.overflow = ""; state.openId = null;
    history.replaceState(null, "", `#/${state.edition.edition_date}`);
    if (state.lastFocus && document.contains(state.lastFocus)) state.lastFocus.focus();
  }

  // ---------- data flow ----------
  async function loadStatus() { try { state.status = await api("/api/status"); renderStatus(); } catch { $("#statusText").textContent = "Status unavailable"; } }
  async function loadEdition(date) {
    state.edition = await api("/api/edition" + (date ? `?date=${encodeURIComponent(date)}` : ""));
    if (!state.edition.signals.some((s) => s.sector === state.sector)) state.sector = null;
    if (!state.edition.signals.some((s) => audiences(s).some((a) => a.segment === state.aud))) state.aud = null;
    renderHero(); renderControls(); renderFeed(); renderEditionNav(); renderMethod(); renderWire();
  }
  async function route() {
    const [, date, id] = (location.hash.match(/^#\/(\d{4}-\d{2}-\d{2})?\/?([\w-]+)?/) || []);
    if (!state.edition || (date && date !== state.edition.edition_date)) {
      try { await loadEdition(date); } catch { await loadEdition(); }
    }
    if (id && id !== state.openId) openSignal(id, false); else if (!id) closeSignal();
  }
  function goEdition(date) { closeSignal(); location.hash = `#/${date}`; }

  // ---------- events ----------
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-close]")) closeSignal();
    if (e.target.closest('a[href="#wire"]')) $("#wireDetails").open = true;
  });
  $("#statusPill").addEventListener("click", () => $("#pipeline").scrollIntoView());
  $("#clearFilters").addEventListener("click", () => { state.sector = state.aud = state.conf = null; state.q = ""; $("#search").value = ""; renderControls(); renderFeed(); });
  $("#editionSelect").addEventListener("change", (e) => goEdition(e.target.value));
  $("#prevEdition").addEventListener("click", () => { const i = state.editions.findIndex((x) => x.edition_date === state.edition.edition_date); if (state.editions[i + 1]) goEdition(state.editions[i + 1].edition_date); });
  $("#nextEdition").addEventListener("click", () => { const i = state.editions.findIndex((x) => x.edition_date === state.edition.edition_date); if (i > 0) goEdition(state.editions[i - 1].edition_date); });
  let deb; $("#search").addEventListener("input", (e) => { clearTimeout(deb); deb = setTimeout(() => { state.q = e.target.value; renderFeed(); }, 120); });
  window.addEventListener("hashchange", route);
  document.addEventListener("keydown", (e) => {
    const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName);
    const drawerOpen = !$("#drawer").hidden;
    if (e.key === "Escape") { if (drawerOpen) closeSignal(); else if (typing) document.activeElement.blur(); return; }
    if (drawerOpen) {
      if (e.key === "c" && !typing && !e.metaKey && !e.ctrlKey) { e.preventDefault(); $("#drawerPanel .thesis button").click(); }
      if (e.key === "Tab") { // focus trap
        const f = [...$("#drawerPanel").querySelectorAll("a[href],button,summary,[tabindex='0']")].filter((x) => x.offsetParent !== null); if (!f.length) return;
        const panel = $("#drawerPanel"), cur = document.activeElement;
        if (cur === panel || !panel.contains(cur)) { e.preventDefault(); (e.shiftKey ? f.at(-1) : f[0]).focus(); }
        else if (e.shiftKey && cur === f[0]) { e.preventDefault(); f.at(-1).focus(); }
        else if (!e.shiftKey && cur === f.at(-1)) { e.preventDefault(); f[0].focus(); }
      }
      return;
    }
    if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "/") { e.preventDefault(); $("#search").focus(); }
    if (e.key === "j" || e.key === "k") {
      const btns = [...document.querySelectorAll("#feedList .item__open")]; if (!btns.length) return;
      const cur = btns.indexOf(document.activeElement);
      state.active = cur < 0 ? 0 : Math.max(0, Math.min(btns.length - 1, cur + (e.key === "j" ? 1 : -1)));
      document.querySelectorAll("#feedList .item").forEach((li, i) => li.classList.toggle("is-active", i === state.active));
      btns[state.active].focus(); btns[state.active].scrollIntoView({ block: "center", behavior: "smooth" });
    }
  });
  $("#refreshForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("#adminToken"), msg = $("#refreshMsg"), token = input.value; input.value = "";
    msg.textContent = "Requesting…";
    try {
      await api("/api/admin/refresh", { method: "POST", headers: { Authorization: `Bearer ${token}` } });
      msg.textContent = "Ingestion started. Status will update when it finishes.";
      const t0 = Date.now();
      const poll = async () => { await loadStatus(); if (state.status?.running && Date.now() - t0 < 180000) setTimeout(poll, 4000);
        else { msg.textContent = `Run finished: ${state.status?.last_run?.status || "unknown"}.`; await refreshAll(); } };
      setTimeout(poll, 2500);
    } catch (err) { msg.textContent = err.body?.detail || `Refresh failed (${err.status || "network"})`; }
  });
  async function refreshAll() {
    state.editions = await api("/api/editions"); state.leads = await api("/api/leads?days=3&limit=120").catch(() => []);
    state.seriesCache.clear(); await loadStatus(); await loadEdition(state.edition?.edition_date === state.editions[1]?.edition_date ? state.edition.edition_date : undefined);
  }

  (async () => {
    [state.editions, state.leads] = await Promise.all([api("/api/editions"), api("/api/leads?days=3&limit=120").catch(() => [])]);
    await loadStatus();
    await route();
    setInterval(loadStatus, 60000); // UI status display only; ingestion runs server-side on its own schedule
  })().catch((err) => { $("#heroHeadline").textContent = "Market Trends → Theses is temporarily unavailable"; $("#heroSummary").textContent = String(err.message || err); });
})();
