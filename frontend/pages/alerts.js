import { api, session } from "../js/api.js";
import { $, SEVERITIES, errorToast, fmtTime, html, incId, mount, options, relTime, severityBadge, statusBadge, toast } from "../js/dashboard.js";

export async function render(root, { refreshSummary }) {
  const state = { status: "UNACKNOWLEDGED", severity: "", page: 1 };
  const canOperate = session.hasRole("OPERATOR");

  mount(root, html`<section class="card"><div class="card-head"><h2>Alerts</h2><div class="spacer"></div>
      <span class="muted" style="font-size:12px">Alerts are shown on this dashboard only — no SMS, e-mail or dispatch integration exists.</span></div>
    <div class="card-body"><div class="toolbar">
      <div class="field"><label for="a-st">Status</label><select id="a-st">${options(["UNACKNOWLEDGED", "ACKNOWLEDGED"], state.status, { blank: "All" })}</select></div>
      <div class="field"><label for="a-sev">Severity</label><select id="a-sev">${options(SEVERITIES, "", { blank: "All" })}</select></div></div></div>
    <div class="card-body flush" id="alert-list"></div><div class="pager" id="a-pager"></div></section>`);

  async function load() {
    const page = await api.alerts({ status: state.status, severity: state.severity, page: state.page, page_size: 25 });
    $("#alert-list", root).innerHTML = String(page.items.length ? html`${page.items.map((a) => html`<div class="alert-item">
      ${severityBadge(a.severity)}<div class="msg"><div>${a.message}</div><div class="muted" style="font-size:12px">
        <a href="#/incident/${a.incident_id}">${incId(a.incident_id)}</a> · ${a.alert_type.replace(/_/g, " ")} · ${fmtTime(a.created_at)} (${relTime(a.created_at)})
        ${a.acknowledged_at ? ` · acknowledged ${fmtTime(a.acknowledged_at)}` : ""}</div></div>
      ${a.status === "UNACKNOWLEDGED" && canOperate ? html`<button class="btn sm" data-ack="${a.id}">Acknowledge</button>` : statusBadge(a.status)}</div>`)}`
      : html`<div class="empty">No alerts match.</div>`);
    $("#a-pager", root).innerHTML = String(html`<span class="muted">${page.total} alerts · page ${page.page} of ${page.pages}</span>
      <button class="btn sm" data-page="${page.page - 1}" ${page.page <= 1 ? "disabled" : ""}>Previous</button>
      <button class="btn sm" data-page="${page.page + 1}" ${page.page >= page.pages ? "disabled" : ""}>Next</button>`);
  }

  $("#a-st", root).addEventListener("change", (e) => { state.status = e.target.value; state.page = 1; load().catch(errorToast); });
  $("#a-sev", root).addEventListener("change", (e) => { state.severity = e.target.value; state.page = 1; load().catch(errorToast); });
  root.addEventListener("click", async (e) => {
    const ack = e.target.closest("[data-ack]");
    const pg = e.target.closest("[data-page]");
    if (pg && !pg.disabled) { state.page = Number(pg.dataset.page); return load().catch(errorToast); }
    if (!ack) return;
    ack.disabled = true;
    try { await api.acknowledge(ack.dataset.ack); toast("Alert acknowledged", "success"); await load(); refreshSummary(); }
    catch (err) { errorToast(err); ack.disabled = false; }
  });

  await load();
  const t = setInterval(() => load().catch(() => {}), 8000);
  return () => clearInterval(t);
}
