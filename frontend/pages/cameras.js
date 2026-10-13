import { api, session } from "../js/api.js";
import { $, confirmDialog, errorToast, html, modalForm, mount, relTime, statusBadge, toast } from "../js/dashboard.js";

function cameraForm(locations, cam = {}) {
  return html`<div class="field"><label>Name</label><input name="name" required maxlength="100" value="${cam.name || ""}"></div>
    <div class="field"><label>Source type</label><select name="source_type">
      ${["FILE", "WEBCAM", "RTSP"].map((t) => html`<option value="${t}" ${cam.source_type === t ? "selected" : ""}>${t}</option>`)}</select></div>
    <div class="field"><label>Source</label><input name="source_uri" ${cam.id ? "" : "required"} maxlength="500"
      placeholder="${cam.id ? "leave empty to keep current source" : "synthetic_fire_demo.mp4 · 0 · rtsp://host/stream"}"></div>
    <p class="muted" style="font-size:12px;margin:0">FILE: a file name inside <span class="mono">data/sample_videos</span>. WEBCAM: device index (0, 1…).
      RTSP: full stream URL — credentials are stored server-side and never shown again.</p>
    <div class="field"><label>Location</label><select name="location_id"><option value="">— none —</option>
      ${locations.map((l) => html`<option value="${l.id}" ${cam.location_id === l.id ? "selected" : ""}>${l.name}</option>`)}</select></div>`;
}

export async function render(root) {
  const isAdmin = session.hasRole("ADMIN");

  async function load() {
    const [cams, locations] = await Promise.all([api.cameras(), api.locations()]);
    mount(root, html`<section class="card"><div class="card-head"><h2>Cameras (${cams.length})</h2><div class="spacer"></div>
      ${isAdmin ? html`<button class="btn primary" id="add-cam">Add camera</button>` : html`<span class="muted">Admin role required to edit</span>`}</div>
      <div class="card-body flush table-wrap"><table><thead><tr><th>ID</th><th>Name</th><th>Source</th><th>Location</th><th>Status</th><th>Last seen</th><th>Monitoring</th><th></th></tr></thead>
      <tbody>${cams.length ? cams.map((c) => html`<tr>
        <td class="mono">${c.id}</td><td><b>${c.name}</b></td><td class="mono">${c.source_type} · ${c.source_display}</td>
        <td>${c.location_name || "—"}</td><td>${statusBadge(c.status)}${c.last_error ? html`<div class="muted" style="font-size:11.5px">${c.last_error}</div>` : ""}</td>
        <td>${c.last_seen_at ? relTime(c.last_seen_at) : "never"}</td>
        <td>${c.monitoring_job_id ? html`<a href="#/monitoring" class="mono">${c.monitoring_job_id}</a>` : html`<span class="muted">idle</span>`}</td>
        <td style="text-align:right">${isAdmin ? html`<div class="btn-row" style="justify-content:flex-end"><button class="btn sm" data-edit="${c.id}">Edit</button>
          <button class="btn danger sm" data-del="${c.id}">Delete</button></div>` : ""}</td></tr>`)
        : html`<tr><td colspan="8" class="empty">No cameras yet. Run <span class="mono">python scripts/setup/seed_demo.py</span> or add one.</td></tr>`}</tbody></table></div></section>`);

    const add = $("#add-cam", root);
    if (add) add.addEventListener("click", async () => {
      const data = await modalForm("Add camera", cameraForm(locations), "Create");
      if (!data) return;
      try {
        await api.createCamera({ ...data, location_id: data.location_id ? Number(data.location_id) : null });
        toast("Camera created", "success");
        await load();
      } catch (err) { errorToast(err); }
    });

    root.querySelectorAll("[data-edit]").forEach((btn) => btn.addEventListener("click", async () => {
      const cam = cams.find((c) => c.id === Number(btn.dataset.edit));
      const data = await modalForm(`Edit ${cam.name}`, cameraForm(locations, cam), "Save");
      if (!data) return;
      const body = { name: data.name, location_id: data.location_id ? Number(data.location_id) : null };
      if (data.source_uri) { body.source_type = data.source_type; body.source_uri = data.source_uri; }
      try { await api.updateCamera(cam.id, body); toast("Camera updated", "success"); await load(); }
      catch (err) { errorToast(err); }
    }));

    root.querySelectorAll("[data-del]").forEach((btn) => btn.addEventListener("click", async () => {
      const cam = cams.find((c) => c.id === Number(btn.dataset.del));
      if (!(await confirmDialog(`Delete camera "${cam.name}"? Incident history is kept.`))) return;
      try { await api.deleteCamera(cam.id); toast("Camera deleted", "success"); await load(); }
      catch (err) { errorToast(err); }
    }));
  }
  await load();
}
