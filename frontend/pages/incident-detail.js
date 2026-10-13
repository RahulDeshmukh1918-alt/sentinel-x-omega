import { api, session } from "../js/api.js";
import {
  demoBadge, errorToast, fmtTime, html, incId, label, mount, relTime, riskMeter, severityBadge, statusBadge, toast,
} from "../js/dashboard.js";

const NEXT = {
  OPEN: ["ACKNOWLEDGED", "IN_PROGRESS", "RESOLVED", "FALSE_ALARM"],
  ACKNOWLEDGED: ["IN_PROGRESS", "RESOLVED", "FALSE_ALARM"],
  IN_PROGRESS: ["RESOLVED", "FALSE_ALARM"],
  RESOLVED: ["OPEN"],
  FALSE_ALARM: ["OPEN"],
};
const VERB = { ACKNOWLEDGED: "Acknowledge", IN_PROGRESS: "Mark in progress", RESOLVED: "Resolve", FALSE_ALARM: "False alarm", OPEN: "Re-open" };

export async function render(root, { param, refreshSummary }) {
  const id = Number(param);
  if (!id) { location.hash = "#/incidents"; return; }
  const canOperate = session.hasRole("OPERATOR");

  async function load() {
    const i = await api.incident(id);
    mount(root, html`<div><a href="#/incidents">← Incidents</a></div>
      ${i.is_demo ? html`<div class="banner warn"><div><strong>Demo detection</strong>This incident was produced by the colour-heuristic demo detector, not a trained model. Treat it as a pipeline demonstration.</div></div>` : ""}
      <section class="card"><div class="card-head">
        <h2 class="mono">${incId(i.id)}</h2>${severityBadge(i.severity)}${statusBadge(i.status)}${i.is_demo ? demoBadge() : ""}
        <span class="badge outline">${i.source.replace("_", " ")}</span><div class="spacer"></div>
        ${canOperate ? html`<div class="btn-row">${NEXT[i.status].map((s) => html`<button class="btn sm ${s === "RESOLVED" ? "primary" : ""}" data-status="${s}">${VERB[s]}</button>`)}</div>` : ""}</div>
        <div class="card-body grid cols-2">
          <dl class="kv">
            <dt>Hazard</dt><dd><b>${label(i.incident_type)}</b></dd>
            <dt>Risk score</dt><dd>${riskMeter(i.risk_score, i.severity)} ${i.risk_score === null ? "" : html`<span class="muted">/ 100 (prototype scoring model)</span>`}</dd>
            <dt>Peak confidence</dt><dd class="mono">${i.peak_confidence === null ? "—" : i.peak_confidence.toFixed(2)}</dd>
            <dt>Frames observed</dt><dd class="mono">${i.frames_observed}</dd>
          </dl>
          <dl class="kv">
            <dt>Camera</dt><dd>${i.camera_name || "—"}</dd>
            <dt>Location</dt><dd>${i.location_name || "—"}</dd>
            <dt>Source</dt><dd>${i.source_label || "—"}</dd>
            <dt>First detected</dt><dd>${fmtTime(i.detection_timestamp)}</dd>
            <dt>Last detected</dt><dd>${fmtTime(i.last_detection_at)} <span class="muted">(${relTime(i.last_detection_at)})</span></dd>
          </dl>
        </div>
        <div class="card-body" style="border-top:1px solid var(--border)"><h3 style="margin-bottom:6px">Description</h3><p style="margin:0">${i.description || "—"}</p></div>
      </section>
      <div class="grid cols-2">
        <section class="card"><div class="card-head"><h2>Recommended response</h2><div class="spacer"></div><span class="badge outline">Advisory only · not dispatched</span></div>
          <div class="card-body flush table-wrap"><table><thead><tr><th>Priority</th><th>Department</th><th>Action</th><th>Dispatch</th></tr></thead><tbody>
          ${i.response_actions.length ? i.response_actions.map((r) => html`<tr><td class="mono">${r.priority}</td><td><b>${r.recommended_department}</b></td><td>${r.recommended_action}</td><td class="muted">${r.dispatch_status.replace("_", " ")}</td></tr>`) : html`<tr><td colspan="4" class="empty">None</td></tr>`}
          </tbody></table></div></section>
        <section class="card"><div class="card-head"><h2>Alerts</h2></div><div class="card-body flush" id="det-alerts">
          ${i.alerts.length ? i.alerts.map((a) => html`<div class="alert-item">${severityBadge(a.severity)}<div class="msg"><div>${a.message}</div>
            <div class="muted" style="font-size:12px">${a.alert_type.replace(/_/g, " ")} · ${fmtTime(a.created_at)}${a.acknowledged_at ? ` · acknowledged ${relTime(a.acknowledged_at)}` : ""}</div></div>
            ${a.status === "UNACKNOWLEDGED" && canOperate ? html`<button class="btn sm" data-ack="${a.id}">Acknowledge</button>` : statusBadge(a.status)}</div>`) : html`<div class="empty">No alerts</div>`}</div></section>
      </div>
      <div class="grid cols-2">
        <section class="card"><div class="card-head"><h2>Sampled detections (${i.detections.length})</h2></div>
          <div class="card-body flush table-wrap" style="max-height:360px;overflow:auto"><table><thead><tr><th>Frame</th><th>Video time</th><th>Confidence</th><th>Label</th><th>Box [x1,y1,x2,y2]</th></tr></thead><tbody>
          ${i.detections.length ? i.detections.map((d) => html`<tr><td class="mono">${d.frame_number}</td><td class="mono">${d.video_time_s === null ? "—" : d.video_time_s.toFixed(1) + "s"}</td>
            <td class="mono">${d.confidence.toFixed(3)}</td><td class="mono">${d.raw_label || d.object_class}</td><td class="mono">${d.bbox.map((v) => Math.round(v)).join(", ")}</td></tr>`) : html`<tr><td colspan="5" class="empty">No model detections (manual report).</td></tr>`}
          </tbody></table></div></section>
        <section class="card"><div class="card-head"><h2>History (audit trail)</h2></div><div class="card-body">
          <ul class="timeline">${i.history.map((h) => html`<li class="${h.status}"><div class="t-head"><b>${h.action.replace(/_/g, " ")}</b><span class="muted mono" style="font-size:11.5px">${fmtTime(h.timestamp)}</span></div>
            <div class="dim" style="font-size:12.5px">${h.message}</div></li>`)}</ul></div></section>
      </div>`);
  }

  root.addEventListener("click", async (e) => {
    const s = e.target.closest("[data-status]");
    const a = e.target.closest("[data-ack]");
    try {
      if (s) { s.disabled = true; await api.updateIncident(id, { status: s.dataset.status }); toast(`Status set to ${s.dataset.status.replace("_", " ")}`, "success"); }
      else if (a) { a.disabled = true; await api.acknowledge(a.dataset.ack); toast("Alert acknowledged", "success"); }
      else return;
      await load();
      refreshSummary();
    } catch (err) { errorToast(err); await load().catch(() => {}); }
  });

  await load();
}
