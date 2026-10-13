import { api, session } from "../js/api.js";
import { $, errorToast, escapeHtml, html, modalForm, mount, raw, toast } from "../js/dashboard.js";

// Schematic position plot from stored latitude/longitude. No map tiles are loaded,
// so the page works offline; each location links out to OpenStreetMap.
function plot(locations) {
  const pts = locations.filter((l) => l.latitude !== null && l.longitude !== null);
  if (!pts.length) return html`<div class="empty">No locations with coordinates yet.</div>`;
  const W = 760, H = 380, P = 40;
  const lats = pts.map((p) => p.latitude), lons = pts.map((p) => p.longitude);
  let [minLat, maxLat, minLon, maxLon] = [Math.min(...lats), Math.max(...lats), Math.min(...lons), Math.max(...lons)];
  const padLat = Math.max((maxLat - minLat) * 0.15, 0.002), padLon = Math.max((maxLon - minLon) * 0.15, 0.002);
  minLat -= padLat; maxLat += padLat; minLon -= padLon; maxLon += padLon;
  const x = (lon) => P + ((lon - minLon) / (maxLon - minLon)) * (W - 2 * P);
  const y = (lat) => H - P - ((lat - minLat) / (maxLat - minLat)) * (H - 2 * P);
  const grid = [0.25, 0.5, 0.75].map((f) => `<line class="grid-line" x1="${P + f * (W - 2 * P)}" x2="${P + f * (W - 2 * P)}" y1="${P}" y2="${H - P}"/>
    <line class="grid-line" y1="${P + f * (H - 2 * P)}" y2="${P + f * (H - 2 * P)}" x1="${P}" x2="${W - P}"/>`).join("");
  const marks = pts.map((p) => {
    const active = p.active_incidents > 0;
    const r = active ? 9 + Math.min(p.active_incidents, 6) * 1.5 : 6;
    const right = x(p.longitude) > W * 0.6; // keep labels inside the plot
    return `<g><circle cx="${x(p.longitude)}" cy="${y(p.latitude)}" r="${r}" fill="${active ? "var(--critical)" : "var(--accent)"}" fill-opacity="${active ? 0.85 : 0.6}" stroke="var(--bg)" stroke-width="2">
      <title>${escapeHtml(p.name)}: ${p.active_incidents} active incident(s), ${p.camera_count} camera(s)</title></circle>
      <text x="${x(p.longitude) + (right ? -(r + 5) : r + 5)}" y="${y(p.latitude) + 4}" text-anchor="${right ? "end" : "start"}">${escapeHtml(p.name)}${active ? ` (${p.active_incidents})` : ""}</text></g>`;
  }).join("");
  return raw(`<svg class="map-plot" viewBox="0 0 ${W} ${H}" role="img" aria-label="Schematic plot of monitored locations">${grid}${marks}
    <text x="${P}" y="${H - 12}">${minLon.toFixed(4)}°E</text><text x="${W - P}" y="${H - 12}" text-anchor="end">${maxLon.toFixed(4)}°E</text>
    <text x="8" y="${P}">${maxLat.toFixed(4)}°N</text><text x="8" y="${H - P}">${minLat.toFixed(4)}°N</text></svg>`);
}

export async function render(root) {
  const isAdmin = session.hasRole("ADMIN");
  async function load() {
    const locations = await api.locations();
    mount(root, html`<section class="card"><div class="card-head"><h2>Location overview</h2><div class="spacer"></div>
        <span class="muted" style="font-size:12px">Schematic coordinate plot (not a street map). Red = active incidents.</span></div>
        <div class="card-body">${plot(locations)}</div></section>
      <section class="card"><div class="card-head"><h2>Locations (${locations.length})</h2><div class="spacer"></div>
        ${isAdmin ? html`<button class="btn primary" id="add-loc">Add location</button>` : ""}</div>
        <div class="card-body flush table-wrap"><table><thead><tr><th>Name</th><th>Address</th><th>Coordinates</th><th>Cameras</th><th>Active incidents</th><th></th></tr></thead><tbody>
        ${locations.length ? locations.map((l) => html`<tr><td><b>${l.name}</b></td><td>${l.address || "—"}</td>
          <td class="mono">${l.latitude !== null ? `${l.latitude.toFixed(5)}, ${l.longitude.toFixed(5)}` : "—"}</td>
          <td class="mono">${l.camera_count}</td>
          <td>${l.active_incidents ? html`<a href="#/incidents" class="badge bad">${l.active_incidents} active</a>` : html`<span class="muted">0</span>`}</td>
          <td>${l.latitude !== null ? html`<a target="_blank" rel="noopener noreferrer" href="https://www.openstreetmap.org/?mlat=${l.latitude}&mlon=${l.longitude}#map=17/${l.latitude}/${l.longitude}">Open map ↗</a>` : ""}</td></tr>`)
          : html`<tr><td colspan="6" class="empty">No locations yet.</td></tr>`}</tbody></table></div></section>`);
    const add = $("#add-loc", root);
    if (add) add.addEventListener("click", async () => {
      const d = await modalForm("Add location", html`
        <div class="field"><label>Name</label><input name="name" required maxlength="120"></div>
        <div class="field"><label>Address</label><input name="address" maxlength="255"></div>
        <div class="form-grid"><div class="field"><label>Latitude</label><input name="latitude" type="number" step="any" min="-90" max="90"></div>
        <div class="field"><label>Longitude</label><input name="longitude" type="number" step="any" min="-180" max="180"></div></div>`, "Create");
      if (!d) return;
      try {
        await api.createLocation({ name: d.name, address: d.address || null,
          latitude: d.latitude === "" ? null : Number(d.latitude), longitude: d.longitude === "" ? null : Number(d.longitude) });
        toast("Location created", "success");
        await load();
      } catch (err) { errorToast(err); }
    });
  }
  await load();
}
