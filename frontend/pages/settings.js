import { api, apiBase, session, setApiBase } from "../js/api.js";
import { $, errorToast, fmtTime, html, mount, toast } from "../js/dashboard.js";

export async function render(root) {
  const user = session.user;
  const [cfg, health] = await Promise.all([api.config(), api.health()]);
  const canAudit = session.hasRole("OPERATOR");
  const thr = Object.entries(cfg.confidence_thresholds);
  const bands = Object.entries(cfg.severity_bands);

  mount(root, html`<div class="grid cols-2">
    <section class="card"><div class="card-head"><h2>Account</h2></div><div class="card-body"><dl class="kv">
      <dt>Name</dt><dd>${user.name}</dd><dt>E-mail</dt><dd>${user.email}</dd><dt>Role</dt><dd>${user.role}</dd></dl></div></section>
    <section class="card"><div class="card-head"><h2>System</h2></div><div class="card-body"><dl class="kv">
      <dt>API</dt><dd class="mono">${apiBase()}</dd><dt>Status</dt><dd>${health.status} · database ${health.database}</dd>
      <dt>Version</dt><dd>${cfg.app_version} (${cfg.environment})</dd><dt>Detector mode</dt><dd>${cfg.detector_mode} · weights file ${cfg.model_weights_file} ${health.model_weights_present ? "(present)" : "(missing)"}</dd>
      <dt>External dispatch</dt><dd>${cfg.external_dispatch}</dd></dl>
      <form id="api-form" class="toolbar" style="margin-top:12px"><div class="field" style="flex:1"><label for="api-base">API base URL override (this browser)</label>
        <input id="api-base" name="base" placeholder="${apiBase()}"></div><button class="btn" type="submit">Save</button></form></div></section>
  </div>
  <section class="card"><div class="card-head"><h2>Detection & risk configuration</h2><div class="spacer"></div><span class="muted" style="font-size:12px">Read-only; change values in <span class="mono">.env</span> and restart</span></div>
    <div class="card-body grid cols-3">
      <dl class="kv"><dt>Frame stride</dt><dd class="mono">every ${cfg.frame_stride} frames</dd><dt>Max frame width</dt><dd class="mono">${cfg.max_frame_width}px</dd>
        <dt>Temporal window</dt><dd class="mono">${cfg.temporal_min_hits} of ${cfg.temporal_window_frames} sampled frames</dd>
        <dt>Event ends after</dt><dd class="mono">${cfg.temporal_end_after_missed} missed frames</dd><dt>De-dup window</dt><dd class="mono">${cfg.incident_dedup_window_seconds}s</dd>
        <dt>Max upload</dt><dd class="mono">${cfg.max_upload_mb} MB</dd></dl>
      <dl class="kv"><dt>Weights</dt><dd class="mono">conf ${cfg.risk_weights.confidence} · persist ${cfg.risk_weights.persistence} · sev ${cfg.risk_weights.severity}</dd>
        <dt>Persistence saturates</dt><dd class="mono">${cfg.persistence_saturation_frames} frames</dd>
        ${bands.map(([k, [a, b]]) => html`<dt>${k}</dt><dd class="mono">${a} – ${b}</dd>`)}</dl>
      <dl class="kv">${thr.map(([k, v]) => html`<dt>${k}</dt><dd class="mono">conf ≥ ${v} · factor ${cfg.hazard_severity_factors[k]}</dd>`)}</dl>
    </div><div class="card-body" style="border-top:1px solid var(--border)"><p class="muted" style="margin:0;font-size:12px">Weights, severity factors and bands are prototype design parameters. The risk score has not been experimentally validated.</p></div></section>
  ${canAudit ? html`<section class="card"><div class="card-head"><h2>Audit log</h2></div><div class="card-body flush table-wrap"><table>
    <thead><tr><th>Time</th><th>Module</th><th>Action</th><th>Status</th><th>Message</th></tr></thead><tbody id="logs"></tbody></table></div>
    <div class="pager" id="log-pager"></div></section>` : ""}`);

  $("#api-form", root).addEventListener("submit", (e) => {
    e.preventDefault();
    const v = new FormData(e.target).get("base");
    setApiBase(v || null);
    toast(v ? `API base set to ${v}` : "API base reset", "success");
  });

  if (!canAudit) return;
  let page = 1;
  async function loadLogs() {
    const res = await api.logs({ page, page_size: 20 });
    $("#logs", root).innerHTML = String(html`${res.items.map((l) => html`<tr><td class="mono" style="white-space:nowrap">${fmtTime(l.timestamp)}</td>
      <td class="mono">${l.module}</td><td>${l.action.replace(/_/g, " ")}</td><td><span class="badge ${l.status === "FAILURE" ? "bad" : l.status === "WARNING" ? "warn" : "outline"}">${l.status}</span></td>
      <td class="dim">${l.message}</td></tr>`)}`);
    $("#log-pager", root).innerHTML = String(html`<span class="muted">${res.total} entries · page ${res.page} of ${res.pages}</span>
      <button class="btn sm" data-p="${page - 1}" ${page <= 1 ? "disabled" : ""}>Previous</button><button class="btn sm" data-p="${page + 1}" ${page >= res.pages ? "disabled" : ""}>Next</button>`);
  }
  $("#log-pager", root).addEventListener("click", (e) => {
    const b = e.target.closest("[data-p]");
    if (b && !b.disabled) { page = Number(b.dataset.p); loadLogs().catch(errorToast); }
  });
  await loadLogs();
}
