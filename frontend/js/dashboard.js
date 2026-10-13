// Shared UI building blocks: safe HTML templating, badges, formatters, charts, modal, toasts.

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const escapeHtml = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ESC[c]);

class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
export const raw = (s) => new Raw(s);

/** Tagged template that escapes every interpolation unless wrapped in raw(). Arrays are joined. */
export function html(strings, ...values) {
  let out = strings[0];
  values.forEach((v, i) => {
    if (Array.isArray(v)) out += v.map((x) => (x instanceof Raw ? x.s : escapeHtml(x))).join("");
    else if (v instanceof Raw) out += v.s;
    else if (v === false || v === null || v === undefined) out += "";
    else out += escapeHtml(v);
    out += strings[i + 1];
  });
  return raw(out);
}

export const HAZARDS = ["FIRE", "SMOKE", "ROAD_ACCIDENT", "ELECTRICAL_SPARK", "PERSON_FALL"];
export const SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];
export const STATUSES = ["OPEN", "ACKNOWLEDGED", "IN_PROGRESS", "RESOLVED", "FALSE_ALARM"];
export const SEV_COLOR = { CRITICAL: "var(--critical)", HIGH: "var(--high)", MEDIUM: "var(--medium)", LOW: "var(--low)" };
export const HAZARD_LABEL = {
  FIRE: "Fire", SMOKE: "Smoke", ROAD_ACCIDENT: "Road accident", ELECTRICAL_SPARK: "Electrical spark",
  PERSON_FALL: "Person fall",
};
export const label = (s) => HAZARD_LABEL[s] || String(s ?? "").replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());

// ---------- formatters ----------
export function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
export function relTime(iso) {
  if (!iso) return "";
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.max(s, 0)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
export const fmtPct = (x) => (x === null || x === undefined ? "—" : `${Math.round(x * 100)}%`);
export const incId = (id) => `INC-${String(id).padStart(5, "0")}`;

// ---------- badges ----------
export const severityBadge = (s) => html`<span class="badge sev-${s}">${s}</span>`;
export const demoBadge = () => html`<span class="badge demo" title="Produced by the colour-heuristic demo detector, not a trained model">Demo</span>`;
export function statusBadge(s) {
  const cls = { OPEN: "bad", ACKNOWLEDGED: "warn", IN_PROGRESS: "warn", RESOLVED: "ok", FALSE_ALARM: "outline",
    ONLINE: "ok", OFFLINE: "outline", ERROR: "bad", UNKNOWN: "outline", RUNNING: "ok", QUEUED: "warn",
    COMPLETED: "outline", STOPPED: "outline", FAILED: "bad", UNACKNOWLEDGED: "bad" }[s] || "outline";
  const live = s === "RUNNING" || s === "OPEN" || s === "UNACKNOWLEDGED";
  return html`<span class="badge ${cls}">${live ? raw('<span class="dot pulse"></span>') : ""}${String(s).replace(/_/g, " ")}</span>`;
}
export function riskMeter(score, severity) {
  if (score === null || score === undefined) return html`<span class="muted mono">n/a</span>`;
  return html`<span class="risk"><span class="risk-bar"><i style="width:${Math.min(100, score)}%;background:${raw(SEV_COLOR[severity] || "var(--low)")}"></i></span>${score.toFixed(1)}</span>`;
}
export function modelBadge(model) {
  if (!model) return "";
  const st = model.model_status;
  if (st === "READY") return html`<span class="badge ok" title="${model.message}">Model ready</span>`;
  if (st === "DEMO_MODE") return html`<span class="badge demo" title="${model.message}">Demo detector</span>`;
  return html`<span class="badge bad" title="${model.message}">Model not available</span>`;
}
export function modelBanner(model) {
  if (!model || model.model_status === "READY") return "";
  if (model.model_status === "DEMO_MODE") {
    return html`<div class="banner warn"><div><strong>Demonstration mode</strong>
      Detections come from a colour heuristic that flags fire-like regions only. It is not a validated hazard
      detector; incidents it creates are tagged <b>Demo</b>. Supported: ${model.supported_hazards.join(", ")}.
      Not supported without a trained model: ${model.unsupported_hazards.join(", ")}.</div></div>`;
  }
  return html`<div class="banner danger"><div><strong>Detection model not available</strong>${model.message}</div></div>`;
}

// ---------- charts (pure SVG, driven by API data) ----------
export function columnChart(points, { height = 170, color = "var(--accent)" } = {}) {
  if (!points.length) return html`<div class="empty">No data</div>`;
  const w = 1000, pad = { l: 34, r: 8, t: 10, b: 24 };
  const max = Math.max(1, ...points.map((p) => p.value));
  const bw = (w - pad.l - pad.r) / points.length;
  const ih = height - pad.t - pad.b;
  const ticks = [0, Math.ceil(max / 2), max];
  const every = Math.ceil(points.length / 10);
  const bars = points.map((p, i) => {
    const h = (p.value / max) * ih;
    const x = pad.l + i * bw + bw * 0.15;
    const lbl = i % every === 0 ? `<text x="${x + bw * 0.35}" y="${height - 6}" text-anchor="middle">${escapeHtml(p.label)}</text>` : "";
    return `<rect x="${x}" y="${pad.t + ih - h}" width="${bw * 0.7}" height="${Math.max(h, p.value ? 1 : 0)}" rx="2" fill="${color}"><title>${escapeHtml(p.label)}: ${p.value}</title></rect>${lbl}`;
  }).join("");
  const grid = ticks.map((t) => {
    const y = pad.t + ih - (t / max) * ih;
    return `<line x1="${pad.l}" x2="${w - pad.r}" y1="${y}" y2="${y}" stroke="var(--border)"/><text x="${pad.l - 6}" y="${y + 3}" text-anchor="end">${t}</text>`;
  }).join("");
  return raw(`<div class="chart"><svg viewBox="0 0 ${w} ${height}" role="img" aria-label="column chart">${grid}${bars}</svg></div>`);
}
export function hbars(entries, colorFor = () => "var(--accent)", fmt = (v) => v) {
  const max = Math.max(1, ...entries.map(([, v]) => v || 0));
  return raw(entries.map(([k, v]) => `<div class="hbar"><span>${escapeHtml(label(k))}</span>
    <span class="track"><i style="width:${((v || 0) / max) * 100}%;background:${colorFor(k)}"></i></span>
    <span class="n">${v === null || v === undefined ? "—" : escapeHtml(fmt(v))}</span></div>`).join(""));
}

// ---------- DOM helpers ----------
export function mount(root, content) { root.innerHTML = String(content); return root; }
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function toast(message, kind = "info", ms = 4200) {
  const box = document.getElementById("toasts");
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = message;
  box.appendChild(el);
  setTimeout(() => el.remove(), ms);
}
export function errorToast(err) { toast(err && err.message ? `${err.code ? err.code + ": " : ""}${err.message}` : String(err), "error", 6500); }

/** Opens a modal with a form body; resolves with FormData object on submit, or null on cancel. */
export function modalForm(title, bodyHtml, submitLabel = "Save") {
  return new Promise((resolve) => {
    const back = document.createElement("div");
    back.className = "modal-back";
    back.innerHTML = String(html`<div class="modal" role="dialog" aria-modal="true" aria-label="${title}">
      <div class="card-head"><h2>${title}</h2></div>
      <form class="card-body">${bodyHtml}
        <div class="btn-row" style="justify-content:flex-end"><button type="button" class="btn ghost" data-cancel>Cancel</button>
        <button class="btn primary" type="submit">${submitLabel}</button></div></form></div>`);
    const close = (val) => { back.remove(); document.removeEventListener("keydown", onKey); resolve(val); };
    const onKey = (e) => { if (e.key === "Escape") close(null); };
    document.addEventListener("keydown", onKey);
    back.addEventListener("click", (e) => { if (e.target === back || e.target.hasAttribute("data-cancel")) close(null); });
    back.querySelector("form").addEventListener("submit", (e) => { e.preventDefault(); close(Object.fromEntries(new FormData(e.target))); });
    document.body.appendChild(back);
    const first = back.querySelector("input,select,textarea");
    if (first) first.focus();
  });
}
export function confirmDialog(message) {
  return modalForm("Please confirm", html`<p>${message}</p>`, "Confirm").then((v) => v !== null);
}

export const options = (values, selected, { blank } = {}) =>
  html`${blank !== undefined ? html`<option value="">${blank}</option>` : ""}${values.map((v) =>
    html`<option value="${v}" ${v === selected ? raw("selected") : ""}>${label(v)}</option>`)}`;
