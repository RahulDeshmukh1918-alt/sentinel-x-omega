// App shell: authentication, layout, hash router and periodic refresh.
import { api, session, setUnauthorizedHandler } from "./api.js";
import { $, $$, errorToast, html, modelBadge, mount, raw } from "./dashboard.js";

const ICON = {
  overview: '<path d="M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z"/>',
  monitoring: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  cameras: '<path d="M23 7l-7 5 7 5V7z"/><rect x="1" y="5" width="15" height="14" rx="2"/>',
  incidents: '<path d="M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0zM12 9v4M12 17h.01"/>',
  alerts: '<path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 01-3.4 0"/>',
  map: '<path d="M1 6v16l7-4 8 4 7-4V2l-7 4-8-4-7 4zM8 2v16M16 6v16"/>',
  analytics: '<path d="M18 20V10M12 20V4M6 20v-6"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z"/>',
};

const ROUTES = [
  { path: "overview", title: "Overview", module: "../pages/overview.js" },
  { path: "monitoring", title: "Live monitoring", module: "../pages/monitoring.js" },
  { path: "cameras", title: "Cameras", module: "../pages/cameras.js" },
  { path: "incidents", title: "Incidents", module: "../pages/incidents.js" },
  { path: "alerts", title: "Alerts", module: "../pages/alerts.js" },
  { path: "map", title: "Locations", module: "../pages/map.js" },
  { path: "analytics", title: "Analytics", module: "../pages/analytics.js" },
  { path: "settings", title: "Settings", module: "../pages/settings.js" },
];
const DETAIL_ROUTE = { path: "incident", title: "Incident detail", module: "../pages/incident-detail.js" };

const state = { cleanup: null, timer: null, summary: null, renderSeq: 0 };

const icon = (name) => raw(`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[name]}</svg>`);

// ---------------------------------------------------------------- login
function renderLogin(message) {
  stopShell();
  mount($("#app"), html`<div class="login-wrap"><div class="login">
    <div class="brand-mark"><div class="sigil">Ω</div><div><div class="brand-name">SENTINEL-X OMEGA</div>
    <div class="brand-sub">Hazard detection & incident response</div></div></div>
    <form id="login-form">
      <div class="field"><label for="email">E-mail</label><input id="email" name="email" type="email" autocomplete="username" required></div>
      <div class="field"><label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password" required minlength="8"></div>
      <button class="btn primary" type="submit">Sign in</button>
      <div id="login-msg" class="muted" role="alert">${message || ""}</div>
    </form>
    <p class="note">No account yet? Create an administrator with <span class="mono">python scripts/setup/create_admin.py</span>.</p>
  </div></div>`);
  $("#login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const btn = e.target.querySelector("button");
    btn.disabled = true;
    try {
      const res = await api.login(f.get("email"), f.get("password"));
      session.save(res.access_token, res.user);
      if (!location.hash) location.hash = "#/overview";
      renderShell();
    } catch (err) {
      $("#login-msg").textContent = err.message;
    } finally {
      btn.disabled = false;
    }
  });
}

// ---------------------------------------------------------------- shell
function renderShell() {
  const user = session.user;
  mount($("#app"), html`<div class="shell">
    <aside class="sidebar">
      <div class="brand"><div class="brand-mark"><div class="sigil">Ω</div><div>
        <div class="brand-name">SENTINEL-X</div><div class="brand-sub">OMEGA · Ops console</div></div></div></div>
      <nav class="nav" aria-label="Main">${ROUTES.map((r) => html`<a href="#/${r.path}" data-route="${r.path}">${icon(r.path)}<span class="label">${r.title}</span>${r.path === "alerts" ? raw('<span class="count hidden" id="alert-count"></span>') : ""}</a>`)}</nav>
      <div class="sidebar-foot"><div>${user ? user.name : ""}</div><div class="muted">${user ? user.role : ""}</div></div>
    </aside>
    <div class="main">
      <header class="topbar"><h1 id="page-title">—</h1><span id="model-badge"></span><div class="spacer"></div>
        <div class="clock" id="clock"></div>
        <button class="btn ghost sm" id="logout">Sign out</button></header>
      <main class="content" id="view"></main>
    </div></div>`);
  $("#logout").addEventListener("click", () => { session.clear(); renderLogin("Signed out."); });
  tickClock();
  refreshSummary();
  state.timer = setInterval(() => { tickClock(); }, 1000);
  state.summaryTimer = setInterval(refreshSummary, 10000);
  route();
}

function stopShell() {
  clearInterval(state.timer);
  clearInterval(state.summaryTimer);
  if (state.cleanup) { try { state.cleanup(); } catch { /* ignore */ } state.cleanup = null; }
}

function tickClock() {
  const el = $("#clock");
  if (!el) return;
  const now = new Date();
  el.innerHTML = String(html`${now.toLocaleTimeString()} local<br>${now.toISOString().slice(11, 19)} UTC`);
}

async function refreshSummary() {
  try {
    state.summary = await api.summary(14);
    const count = $("#alert-count");
    if (count) {
      const n = state.summary.unacknowledged_alerts;
      count.textContent = n > 99 ? "99+" : String(n);
      count.classList.toggle("hidden", n === 0);
    }
    const mb = $("#model-badge");
    if (mb) mb.innerHTML = String(modelBadge(state.summary.model));
  } catch (err) {
    if (err.status !== 401) console.warn("summary refresh failed", err);
  }
}

// ---------------------------------------------------------------- router
async function route() {
  if (!session.token) return renderLogin();
  const [, path = "overview", param] = (location.hash || "#/overview").split("/");
  const def = path === "incident" ? DETAIL_ROUTE : ROUTES.find((r) => r.path === path) || ROUTES[0];
  $$(".nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === (path === "incident" ? "incidents" : def.path)));
  const title = $("#page-title");
  if (title) title.textContent = def.title;
  document.title = `${def.title} · SENTINEL-X OMEGA`;
  if (state.cleanup) { try { state.cleanup(); } catch { /* ignore */ } state.cleanup = null; }
  const old = $("#view");
  if (!old) return;
  const view = old.cloneNode(false); // fresh element: drops event listeners of the previous page
  old.replaceWith(view);
  const seq = ++state.renderSeq;
  view.innerHTML = '<div class="muted">Loading…</div>';
  try {
    const mod = await import(def.module);
    if (seq !== state.renderSeq) return;
    state.cleanup = (await mod.render(view, { param, refreshSummary, getSummary: () => state.summary })) || null;
  } catch (err) {
    if (seq !== state.renderSeq) return;
    view.innerHTML = String(html`<div class="banner danger"><div><strong>Could not load this page</strong>${err.message}</div></div>`);
    if (err.status !== 401) errorToast(err);
  }
}

setUnauthorizedHandler(() => { session.clear(); renderLogin("Your session has expired. Please sign in again."); });
window.addEventListener("hashchange", () => { if (session.token) route(); });
session.token ? renderShell() : renderLogin();
