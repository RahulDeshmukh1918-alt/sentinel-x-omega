import { api, session } from "../js/api.js";
import {
  $, demoBadge, errorToast, fmtPct, html, incId, label, modelBanner, mount, raw, relTime, statusBadge, toast,
} from "../js/dashboard.js";

export async function render(root) {
  let selectedJob = null;
  let snapshotUrl = null;
  const canOperate = session.hasRole("OPERATOR");

  mount(root, html`<div id="mon-banner"></div>
    <div class="grid split">
      <div class="grid">
        <section class="card"><div class="card-head"><h2>Camera sources</h2><div class="spacer"></div><span class="muted" style="font-size:12px">Start monitoring a configured webcam, RTSP stream or sample file</span></div>
          <div class="card-body flush table-wrap"><table><thead><tr><th>Camera</th><th>Source</th><th>Status</th><th>Last seen</th><th></th></tr></thead><tbody id="mon-cams"></tbody></table></div></section>
        <section class="card"><div class="card-head"><h2>Analyse a video file</h2></div>
          <div class="card-body">${canOperate ? html`<form id="upload-form" class="toolbar">
            <div class="field" style="flex:1;min-width:220px"><label for="vid">Video (mp4, avi, mov, mkv, webm)</label><input id="vid" name="file" type="file" accept="video/*,.mp4,.avi,.mov,.mkv,.webm" required></div>
            <div class="field"><label for="upcam">Link to camera (optional)</label><select id="upcam" name="camera_id"><option value="">— none —</option></select></div>
            <button class="btn primary" type="submit">Upload & analyse</button></form>
            <p class="muted" style="font-size:12px;margin:10px 0 0">Footage is processed in the background and deleted after analysis (configurable).</p>`
            : html`<p class="muted">Operator role required to run detection.</p>`}</div></section>
        <section class="card"><div class="card-head"><h2>Detection jobs</h2></div>
          <div class="card-body flush table-wrap"><table><thead><tr><th>Job</th><th>Source</th><th>Status</th><th>Progress</th><th>Frames</th><th>Incidents</th><th></th></tr></thead><tbody id="mon-jobs"></tbody></table></div></section>
      </div>
      <section class="card"><div class="card-head"><h2>Processed frame</h2><div class="spacer"></div><span id="snap-label" class="muted mono"></span></div>
        <div class="card-body"><div class="snapshot" id="snap">Select a job to view its latest analysed frame.</div>
          <p class="muted" style="font-size:12px">This is the most recent frame the pipeline analysed, with detections drawn — not a continuous video feed.</p>
          <h3 style="margin:14px 0 8px">Recent detections</h3><div id="snap-dets" class="table-wrap"></div></div></section>
    </div>`);

  async function refresh() {
    const [status, cameras] = await Promise.all([api.detectionStatus(), api.cameras()]);
    $("#mon-banner", root).innerHTML = String(modelBanner(status.model));
    const enabled = status.model.detection_enabled;

    $("#mon-cams", root).innerHTML = String(cameras.length ? html`${cameras.map((c) => html`<tr>
      <td><b>${c.name}</b><div class="muted" style="font-size:12px">${c.location_name || ""}</div></td>
      <td class="mono">${c.source_type} · ${c.source_display}</td>
      <td>${statusBadge(c.status)}${c.last_error ? html`<div class="muted" style="font-size:11.5px">${c.last_error}</div>` : ""}</td>
      <td>${c.last_seen_at ? relTime(c.last_seen_at) : "—"}</td>
      <td style="text-align:right">${canOperate ? (c.monitoring_job_id
        ? html`<button class="btn danger sm" data-stop="${c.monitoring_job_id}">Stop</button>`
        : html`<button class="btn sm" data-start="${c.id}" ${enabled ? "" : "disabled"}>Start</button>`) : ""}</td></tr>`)}`
      : html`<tr><td colspan="5" class="empty">No cameras configured. Add one on the Cameras page.</td></tr>`);

    const sel = $("#upcam", root);
    if (sel && sel.options.length !== cameras.length + 1) {
      sel.innerHTML = String(html`<option value="">— none —</option>${cameras.map((c) => html`<option value="${c.id}">${c.name}</option>`)}`);
    }
    const upBtn = $("#upload-form button", root);
    if (upBtn) upBtn.disabled = !enabled;

    $("#mon-jobs", root).innerHTML = String(status.jobs.length ? html`${status.jobs.map((j) => html`<tr class="clickable" data-job="${j.id}" ${j.id === selectedJob ? raw('style="background:var(--panel-2)"') : ""}>
      <td class="mono">${j.id}${j.is_demo ? html` ${demoBadge()}` : ""}</td>
      <td>${j.source}<div class="muted" style="font-size:12px">${j.kind}</div></td>
      <td>${statusBadge(j.status)}${j.error_code ? html`<div class="muted" style="font-size:11.5px">${j.error_code}: ${j.error_message}</div>` : ""}</td>
      <td style="min-width:110px">${j.progress !== null ? html`<div class="progress"><i style="width:${Math.round(j.progress * 100)}%"></i></div><span class="muted" style="font-size:11.5px">${fmtPct(j.progress)}</span>` : html`<span class="muted">live · ${j.video_time_s.toFixed(0)}s</span>`}</td>
      <td class="mono">${j.frames_processed}</td>
      <td>${j.incident_ids.length ? j.incident_ids.map((id) => html`<a href="#/incident/${id}">${incId(id)}</a> `) : html`<span class="muted">none</span>`}</td>
      <td style="text-align:right">${canOperate && (j.status === "RUNNING" || j.status === "QUEUED") ? html`<button class="btn danger sm" data-stop="${j.id}">Stop</button>` : ""}</td></tr>`)}`
      : html`<tr><td colspan="7" class="empty">No detection jobs yet.</td></tr>`);

    if (!selectedJob && status.jobs.length) selectedJob = status.jobs[0].id;
    const job = status.jobs.find((j) => j.id === selectedJob);
    if (job) await showJob(job);
  }

  async function showJob(job) {
    $("#snap-label", root).textContent = `${job.id} · ${job.source}`;
    $("#snap-dets", root).innerHTML = String(job.recent_detections.length ? html`<table><thead><tr><th>Hazard</th><th>Confidence</th><th>Frame</th><th>Video time</th><th>Detected</th></tr></thead><tbody>
      ${job.recent_detections.slice().reverse().map((d) => html`<tr><td>${label(d.hazard_type)} ${d.is_demo ? demoBadge() : ""}</td>
      <td class="mono">${d.confidence.toFixed(2)}</td><td class="mono">${d.frame}</td><td class="mono">${d.video_time_s.toFixed(1)}s</td><td>${relTime(d.detected_at)}</td></tr>`)}</tbody></table>`
      : html`<p class="muted">No detections above threshold yet.</p>`);
    if (!job.has_snapshot) return;
    try {
      const url = await api.snapshotUrl(job.id);
      if (snapshotUrl) URL.revokeObjectURL(snapshotUrl);
      snapshotUrl = url;
      $("#snap", root).innerHTML = String(html`<img alt="Latest analysed frame for job ${job.id}" src="${url}">`);
    } catch { /* snapshot may not exist yet */ }
  }

  root.addEventListener("click", async (e) => {
    const start = e.target.closest("[data-start]");
    const stop = e.target.closest("[data-stop]");
    const row = e.target.closest("tr[data-job]");
    try {
      if (start) {
        start.disabled = true;
        const job = await api.startDetection(Number(start.dataset.start));
        selectedJob = job.id;
        toast(`Monitoring started (job ${job.id})`, "success");
      } else if (stop) {
        stop.disabled = true;
        await api.stopDetection(stop.dataset.stop);
        toast("Stop requested", "info");
      } else if (row) {
        selectedJob = row.dataset.job;
      } else return;
      await refresh();
    } catch (err) { errorToast(err); await refresh().catch(() => {}); }
  });

  const form = $("#upload-form", root);
  if (form) form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const btn = form.querySelector("button");
    btn.disabled = true;
    btn.textContent = "Uploading…";
    try {
      const job = await api.analyze(fd.get("file"), fd.get("camera_id"));
      selectedJob = job.id;
      toast(`Analysis started (job ${job.id})`, "success");
      form.reset();
      await refresh();
    } catch (err) { errorToast(err); }
    finally { btn.disabled = false; btn.textContent = "Upload & analyse"; }
  });

  await refresh();
  const t = setInterval(() => refresh().catch(() => {}), 2000);
  return () => { clearInterval(t); if (snapshotUrl) URL.revokeObjectURL(snapshotUrl); };
}
