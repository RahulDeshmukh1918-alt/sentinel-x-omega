import { api, session } from "../js/api.js";
import { $, HAZARDS, SEVERITIES, STATUSES, errorToast, html, modalForm, mount, options, toast } from "../js/dashboard.js";
import { INCIDENT_HEAD, bindRowLinks, incidentRows } from "./overview.js";

export async function render(root) {
  const filters = { hazard_type: "", severity: "", status: "", date_from: "", date_to: "", active_only: false, page: 1, page_size: 25 };

  mount(root, html`<section class="card"><div class="card-head"><h2>Incidents</h2><div class="spacer"></div>
      ${session.hasRole("OPERATOR") ? html`<button class="btn" id="report">Report incident manually</button>` : ""}</div>
    <div class="card-body"><form class="toolbar" id="filters">
      <div class="field"><label for="f-h">Hazard</label><select id="f-h" name="hazard_type">${options(HAZARDS, "", { blank: "All hazards" })}</select></div>
      <div class="field"><label for="f-s">Severity</label><select id="f-s" name="severity">${options(SEVERITIES, "", { blank: "All severities" })}</select></div>
      <div class="field"><label for="f-st">Status</label><select id="f-st" name="status">${options(STATUSES, "", { blank: "All statuses" })}</select></div>
      <div class="field"><label for="f-from">From</label><input id="f-from" type="date" name="date_from"></div>
      <div class="field"><label for="f-to">To</label><input id="f-to" type="date" name="date_to"></div>
      <label class="check"><input type="checkbox" name="active_only"> Active only</label>
      <button class="btn primary" type="submit">Apply</button><button class="btn ghost" type="reset">Reset</button>
    </form></div>
    <div class="card-body flush table-wrap"><table><thead>${INCIDENT_HEAD}</thead><tbody id="inc-rows"></tbody></table></div>
    <div class="pager" id="pager"></div></section>`);

  async function load() {
    const q = { ...filters };
    if (q.date_from) q.date_from = new Date(`${q.date_from}T00:00:00`).toISOString();
    if (q.date_to) q.date_to = new Date(`${q.date_to}T23:59:59.999`).toISOString();
    q.active_only = q.active_only ? "true" : "";
    const page = await api.incidents(q);
    $("#inc-rows", root).innerHTML = String(incidentRows(page.items));
    $("#pager", root).innerHTML = String(html`<span class="muted">${page.total} incidents · page ${page.page} of ${page.pages}</span>
      <button class="btn sm" data-page="${page.page - 1}" ${page.page <= 1 ? "disabled" : ""}>Previous</button>
      <button class="btn sm" data-page="${page.page + 1}" ${page.page >= page.pages ? "disabled" : ""}>Next</button>`);
  }

  const form = $("#filters", root);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const f = new FormData(form);
    Object.assign(filters, Object.fromEntries(["hazard_type", "severity", "status", "date_from", "date_to"].map((k) => [k, f.get(k) || ""])));
    filters.active_only = f.get("active_only") === "on";
    filters.page = 1;
    load().catch(errorToast);
  });
  form.addEventListener("reset", () => setTimeout(() => form.requestSubmit(), 0));
  $("#pager", root).addEventListener("click", (e) => {
    const b = e.target.closest("[data-page]");
    if (!b || b.disabled) return;
    filters.page = Number(b.dataset.page);
    load().catch(errorToast);
  });
  bindRowLinks($("#inc-rows", root));

  const report = $("#report", root);
  if (report) report.addEventListener("click", async () => {
    const cams = await api.cameras().catch(() => []);
    const data = await modalForm("Report incident", html`
      <div class="banner info"><div>Manual reports are stored with source <b>MANUAL</b> and have no model risk score.</div></div>
      <div class="field"><label>Hazard</label><select name="incident_type">${options(HAZARDS, "FIRE")}</select></div>
      <div class="field"><label>Severity</label><select name="severity">${options(SEVERITIES, "MEDIUM")}</select></div>
      <div class="field"><label>Camera</label><select name="camera_id"><option value="">— none —</option>${cams.map((c) => html`<option value="${c.id}">${c.name}</option>`)}</select></div>
      <div class="field"><label>Description</label><textarea name="description" maxlength="2000"></textarea></div>`, "Create incident");
    if (!data) return;
    try {
      const inc = await api.reportIncident({ incident_type: data.incident_type, severity: data.severity,
        description: data.description || null, camera_id: data.camera_id ? Number(data.camera_id) : null });
      toast("Incident reported", "success");
      location.hash = `#/incident/${inc.id}`;
    } catch (err) { errorToast(err); }
  });

  await load();
  const t = setInterval(() => load().catch(() => {}), 15000);
  return () => clearInterval(t);
}
