import { api } from "../js/api.js";
import { $, HAZARDS, SEVERITIES, SEV_COLOR, STATUSES, columnChart, hbars, html, mount } from "../js/dashboard.js";

const STATUS_COLOR = { OPEN: "var(--critical)", ACKNOWLEDGED: "var(--medium)", IN_PROGRESS: "var(--high)", RESOLVED: "var(--ok)", FALSE_ALARM: "var(--low)" };

export async function render(root) {
  let days = 14;
  mount(root, html`<div class="toolbar"><div class="field"><label for="days">Period</label>
    <select id="days"><option value="7">Last 7 days</option><option value="14" selected>Last 14 days</option><option value="30">Last 30 days</option><option value="90">Last 90 days</option></select></div>
    <p class="muted" style="font-size:12px;margin:0 0 6px">All charts are computed live from stored incidents. No model accuracy figures are shown because none have been measured.</p></div>
    <div id="charts"></div>`);

  async function load() {
    const s = await api.summary(days);
    const daily = s.daily.map((d) => ({ label: d.date.slice(5), value: d.count }));
    $("#charts", root).innerHTML = String(html`
      ${s.demo_incidents ? html`<div class="banner warn"><div>${s.demo_incidents} of ${s.total_incidents} incidents were produced by the demo detector and are included below.</div></div>` : ""}
      <section class="card"><div class="card-head"><h2>Incidents per day</h2><div class="spacer"></div><span class="muted mono">${daily.reduce((a, b) => a + b.value, 0)} in period</span></div>
        <div class="card-body">${columnChart(daily)}</div></section>
      <div class="grid cols-2">
        <section class="card"><div class="card-head"><h2>All incidents by hazard</h2></div><div class="card-body">${hbars(HAZARDS.map((h) => [h, s.by_hazard[h]]), () => "var(--accent)")}</div></section>
        <section class="card"><div class="card-head"><h2>Average risk score by hazard</h2></div><div class="card-body">
          ${hbars(HAZARDS.map((h) => [h, s.average_risk_by_hazard[h]]), () => "var(--high)", (v) => v.toFixed(1))}
          <p class="muted" style="font-size:12px;margin:8px 0 0">Model-derived incidents only; manual reports have no risk score.</p></div></section>
        <section class="card"><div class="card-head"><h2>Active incidents by severity</h2></div><div class="card-body">${hbars(SEVERITIES.slice().reverse().map((k) => [k, s.by_severity[k]]), (k) => SEV_COLOR[k])}</div></section>
        <section class="card"><div class="card-head"><h2>Incidents by status</h2></div><div class="card-body">${hbars(STATUSES.map((k) => [k, s.by_status[k]]), (k) => STATUS_COLOR[k])}</div></section>
      </div>`);
  }
  $("#days", root).addEventListener("change", (e) => { days = Number(e.target.value); load(); });
  await load();
}
