// REST client for the SENTINEL-X backend (/api/v1). All dashboard data comes from here.

const TOKEN_KEY = "sx_token";
const USER_KEY = "sx_user";
const BASE_KEY = "sx_api_base";

function storageGet(store, key) {
  try { return store.getItem(key); } catch { return null; }
}
function storageSet(store, key, value) {
  try { value === null ? store.removeItem(key) : store.setItem(key, value); } catch { /* storage unavailable */ }
}

export class ApiError extends Error {
  constructor(status, code, message, details) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function apiBase() {
  const override = storageGet(localStorage, BASE_KEY);
  if (override) return override.replace(/\/$/, "");
  return location.protocol.startsWith("http") ? location.origin : "http://localhost:8000";
}
export function setApiBase(value) { storageSet(localStorage, BASE_KEY, value ? value.trim() : null); }

export const session = {
  get token() { return storageGet(sessionStorage, TOKEN_KEY); },
  get user() {
    const raw = storageGet(sessionStorage, USER_KEY);
    try { return raw ? JSON.parse(raw) : null; } catch { return null; }
  },
  save(token, user) {
    storageSet(sessionStorage, TOKEN_KEY, token);
    storageSet(sessionStorage, USER_KEY, JSON.stringify(user));
  },
  clear() {
    storageSet(sessionStorage, TOKEN_KEY, null);
    storageSet(sessionStorage, USER_KEY, null);
  },
  hasRole(min) {
    const order = { VIEWER: 1, OPERATOR: 2, ADMIN: 3 };
    const u = this.user;
    return !!u && order[u.role] >= order[min];
  },
};

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }

async function request(method, path, { body, form, query, raw } = {}) {
  const url = new URL(apiBase() + "/api/v1" + path);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
    }
  }
  const headers = {};
  const token = session.token;
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload;
  if (form) payload = form;  // FormData / URLSearchParams: browser sets Content-Type
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }

  let res;
  try {
    res = await fetch(url, { method, headers, body: payload });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", `Cannot reach the API at ${apiBase()}. Is the backend running?`);
  }
  if (res.status === 401 && path !== "/auth/login") onUnauthorized();
  if (!res.ok) {
    let err = { code: `HTTP_${res.status}`, message: res.statusText || "Request failed" };
    try { const data = await res.json(); if (data && data.error) err = data.error; } catch { /* non-JSON */ }
    throw new ApiError(res.status, err.code, err.message, err.details);
  }
  if (raw) return res;
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  login: (email, password) => request("POST", "/auth/login", { form: new URLSearchParams({ username: email, password }) }),
  me: () => request("GET", "/auth/me"),
  health: () => request("GET", "/health"),
  summary: (days = 14) => request("GET", "/dashboard/summary", { query: { days } }),
  config: () => request("GET", "/system/config"),
  logs: (query) => request("GET", "/system/logs", { query }),

  cameras: () => request("GET", "/cameras"),
  createCamera: (data) => request("POST", "/cameras", { body: data }),
  updateCamera: (id, data) => request("PUT", `/cameras/${id}`, { body: data }),
  deleteCamera: (id) => request("DELETE", `/cameras/${id}`),
  locations: () => request("GET", "/locations"),
  createLocation: (data) => request("POST", "/locations", { body: data }),

  incidents: (query) => request("GET", "/incidents", { query }),
  incident: (id) => request("GET", `/incidents/${id}`),
  reportIncident: (data) => request("POST", "/incidents", { body: data }),
  updateIncident: (id, data) => request("PATCH", `/incidents/${id}`, { body: data }),

  alerts: (query) => request("GET", "/alerts", { query }),
  acknowledge: (id) => request("PATCH", `/alerts/${id}/acknowledge`),

  detectionStatus: () => request("GET", "/detection/status"),
  startDetection: (cameraId) => request("POST", "/detection/start", { body: { camera_id: cameraId } }),
  stopDetection: (jobId) => request("POST", "/detection/stop", { body: { job_id: jobId } }),
  job: (id) => request("GET", `/detection/jobs/${id}`),
  analyze: (file, cameraId) => {
    const fd = new FormData();
    fd.append("file", file);
    if (cameraId) fd.append("camera_id", cameraId);
    return request("POST", "/detection/analyze", { form: fd });
  },
  snapshotUrl: async (jobId) => {
    const res = await request("GET", `/detection/jobs/${jobId}/snapshot`, { raw: true });
    return URL.createObjectURL(await res.blob());
  },
};
