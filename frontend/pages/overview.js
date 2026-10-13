import { api, session } from "../js/api.js";
import {
  $, SEVERITIES, SEV_COLOR, demoBadge, errorToast, hbars, html, incId, label, modelBanner, mount, raw, relTime,
  riskMeter, severityBadge, statusBadge, toast,
} from "../js/dashboard.js";

export function incidentRows(items) {
  if (!items.length) return html`<tr><td colspan="8" class="empty">No incidents match.</td></tr>`;
  return html`${items.map((i) => html`<tr class="clickable row-${i.severity}" data-href="#/incident/${i.id}">
    <td class="mono">${incId(i.id)}</td>
    <td>${label(i.incident_type)} ${i.is_demo ? demoBadge() : ""}</td>
    <td>${severityBadge(i.severity)}</td>
    <td>${riskMeter(i.risk_score, i.severity)}</td>
    <td>${i.camera_name || i.source_label || "—"}<div class="muted" style="font-size:12px">${i.location_name || ""}</div></td>
    <td><span title="${i.detection_timestamp}">${relTime(i.detection_timestamp)}</span></td>
    <td>${statusBadge(i.status)}</td>
    <td class="truncate" title="${i.recommended_action || ""}">${i.recommended_department ? html`<b>${i.recommended_department}</b> · ` : ""}${i.recommended_action || "—"}</td>
  </tr>`)}`;
}
export const INCIDENT_HEAD = raw("<tr><th>Incident</th><th>Hazard</th><th>Severity</th><th>Risk</th><th>Camera / location</th><th>Detected</th><th>Status</th><th>Recommended action</th></tr>");

export function bindRowLinks(root) {
  root.addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-href]");
    if (tr && !e.target.closest("button,a")) location.hash = tr.dataset.href;
  });
}

export async function render(root) {
  async function load() {
    const [s, incidents, alerts] = await Promise.all([
      api.summary(14),
      api.incidents({ page_size: 8 }),
      api.alerts({ status: "UNACKNOWLEDGED", page_size: 6 }),
    ]);
    mount(root, html`
      ${modelBanner(s.model)}
      <section class="stats" aria-label="Key figures">
        <div class="stat high"><div class="stat-label">Active incidents</div><div class="stat-value">${s.active_incidents}</div><div class="stat-sub">open, acknowledged or in progress</div></div>
        <div class="stat critical"><div class="stat-label">Critical incidents</div><div class="stat-value">${s.critical_incidents}</div><div class="stat-sub">active with CRITICAL severity</div></div>
        <div class="stat ok"><div class="stat-label">Online cameras</div><div class="stat-value">${s.online_cameras}<span class="muted" style="font-size:16px"> / ${s.total_cameras}</span></div><div class="stat-sub">last opened successfully</div></div>
        <div class="stat accent"><div class="stat-label">Unacknowledged alerts</div><div class="stat-value">${s.unacknowledged_alerts}</div><div class="stat-sub">dashboard alerts awaiting an operator</div></div>
        <div class="stat"><div class="stat-label">Resolved incidents</div><div class="stat-value">${s.resolved_incidents}</div><div class="stat-sub">of ${s.total_incidents} recorded${s.demo_incidents ? ` · ${s.demo_incidents} demo` : ""}</div></div>
      </section>
      <div class="grid split">
        <section class="card"><div class="card-head"><h2>Latest incidents</h2><div class="spacer"></div><a href="#/incidents">View all</a></div>
          <div class="card-body flush table-wrap"><table><thead>${INCIDENT_HEAD}</thead><tbody id="ov-rows">${incidentRows(incidents.items)}</tbody></table></div></section>
        <div class="grid">
          <section class="card"><div class="card-head"><h2>Unacknowledged alerts</h2><div class="spacer"></div><a href="#/alerts">All alerts</a></div>
            <div class="card-body flush" id="ov-alerts">${alerts.items.length ? alerts.items.map((a) => html`<div class="alert-item">
              ${severityBadge(a.severity)}<div class="msg"><div>${a.message}</div><div class="muted" style="font-size:12px">
              <a href="#/incident/${a.incident_id}">${incId(a.incident_id)}</a> · ${relTime(a.created_at)}</div></div>
              ${session.hasRole("OPERATOR") ? html`<button class="btn sm" data-ack="${a.id}">Acknowledge</button>` : ""}</div>`) : html`<div class="empty">No unacknowledged alerts.</div>`}</div></section>
          <section class="card"><div class="card-head"><h2>Active incidents by severity</h2></div>
            <div class="card-body">${hbars(SEVERITIES.slice().reverse().map((k) => [k, s.by_severity[k]]), (k) => SEV_COLOR[k])}</div></section>
        </div>
      </div>`);
    bindRowLinks($("#ov-rows", root));
    $("#ov-alerts", root).addEventListener("click", async (e) => {
      const btn = e.target.closest("[data-ack]");
      if (!btn) return;
      btn.disabled = true;
      try { await api.acknowledge(btn.dataset.ack); toast("Alert acknowledged", "success"); await load(); }
      catch (err) { errorToast(err); btn.disabled = false; }
    });
  }
  await load();
  const t = setInterval(() => load().catch(() => {}), 10000);
  return () => clearInterval(t);
}
