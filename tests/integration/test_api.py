"""REST API: auth, validation, error envelope, CRUD and role checks."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

pytestmark = pytest.mark.integration

API = "/api/v1"


def assert_error(res, status, code=None):
    assert res.status_code == status, res.text
    body = res.json()
    assert set(body) == {"error"} and "message" in body["error"]
    if code:
        assert body["error"]["code"] == code, body


# ---------------------------------------------------------------- health / errors / auth
def test_health_is_public(client):
    res = client.get(f"{API}/health")
    assert res.status_code == 200
    assert res.json()["database"] == "ok"
    assert res.json()["model_weights_present"] is False


def test_unknown_route_uses_error_envelope(client):
    assert_error(client.get(f"{API}/does-not-exist"), 404, "NOT_FOUND")


def test_protected_endpoint_requires_token(client):
    res = client.get(f"{API}/incidents")
    assert_error(res, 401, "NOT_AUTHENTICATED")
    assert res.headers.get("www-authenticate") == "Bearer"
    assert_error(client.get(f"{API}/incidents", headers={"Authorization": "Bearer garbage"}), 401, "INVALID_TOKEN")


def test_login_and_me(client, create_user):
    user = create_user()
    from tests.conftest import TEST_PASSWORD, login

    assert_error(client.post(f"{API}/auth/login", data={"username": user.email, "password": "wrong-password"}),
                 401, "INVALID_CREDENTIALS")
    headers = login(client, user.email.upper(), TEST_PASSWORD)  # e-mail match is case-insensitive
    me = client.get(f"{API}/auth/me", headers=headers).json()
    assert me["email"] == user.email and me["role"] == "ADMIN"
    assert "password_hash" not in me


# ---------------------------------------------------------------- cameras & locations
def test_camera_crud_and_credential_masking(client, auth_headers):
    admin = auth_headers["ADMIN"]
    loc = client.post(f"{API}/locations", json={"name": "Main gate", "latitude": 18.52, "longitude": 73.85}, headers=admin)
    assert loc.status_code == 201
    res = client.post(f"{API}/cameras", headers=admin, json={
        "name": "Gate cam", "source_type": "RTSP", "source_uri": "rtsp://admin:hunter2@10.0.0.5/live",
        "location_id": loc.json()["id"]})
    assert res.status_code == 201, res.text
    cam = res.json()
    assert cam["source_display"] == "rtsp://***@10.0.0.5/live" and "source_uri" not in cam
    assert cam["location_name"] == "Main gate" and cam["status"] == "UNKNOWN"
    assert "hunter2" not in client.get(f"{API}/cameras", headers=admin).text

    upd = client.put(f"{API}/cameras/{cam['id']}", headers=admin, json={"name": "Gate cam 2"})
    assert upd.status_code == 200 and upd.json()["name"] == "Gate cam 2"
    assert client.delete(f"{API}/cameras/{cam['id']}", headers=admin).status_code == 204
    assert_error(client.get(f"{API}/cameras/{cam['id']}", headers=admin), 404, "CAMERA_NOT_FOUND")


@pytest.mark.parametrize("payload,code", [
    ({"name": "x", "source_type": "WEBCAM", "source_uri": "abc"}, "INVALID_CAMERA_SOURCE"),
    ({"name": "x", "source_type": "FILE", "source_uri": "../../etc/passwd.mp4"}, "INVALID_CAMERA_SOURCE"),
    ({"name": "x", "source_type": "FILE", "source_uri": "clip.exe"}, "INVALID_CAMERA_SOURCE"),
    ({"name": "x", "source_type": "RTSP", "source_uri": "ftp://host/stream"}, "INVALID_CAMERA_SOURCE"),
    ({"name": "x", "source_type": "LASER", "source_uri": "0"}, "VALIDATION_ERROR"),
    ({"name": "", "source_type": "WEBCAM", "source_uri": "0"}, "VALIDATION_ERROR"),
    ({"source_type": "WEBCAM", "source_uri": "0"}, "VALIDATION_ERROR"),
])
def test_camera_validation(client, auth_headers, payload, code):
    assert_error(client.post(f"{API}/cameras", json=payload, headers=auth_headers["ADMIN"]), 422, code)


def test_camera_duplicate_name_and_missing_location(client, auth_headers):
    admin = auth_headers["ADMIN"]
    body = {"name": "Dup", "source_type": "WEBCAM", "source_uri": "0"}
    assert client.post(f"{API}/cameras", json=body, headers=admin).status_code == 201
    assert_error(client.post(f"{API}/cameras", json=body, headers=admin), 409, "CAMERA_NAME_EXISTS")
    assert_error(client.post(f"{API}/cameras", json={**body, "name": "Other", "location_id": 999}, headers=admin),
                 404, "LOCATION_NOT_FOUND")


def test_role_checks(client, auth_headers):
    body = {"name": "Cam", "source_type": "WEBCAM", "source_uri": "0"}
    assert_error(client.post(f"{API}/cameras", json=body, headers=auth_headers["VIEWER"]), 403, "FORBIDDEN")
    assert_error(client.post(f"{API}/cameras", json=body, headers=auth_headers["OPERATOR"]), 403, "FORBIDDEN")
    assert client.get(f"{API}/cameras", headers=auth_headers["VIEWER"]).status_code == 200
    report = {"incident_type": "FIRE", "severity": "LOW"}
    assert_error(client.post(f"{API}/incidents", json=report, headers=auth_headers["VIEWER"]), 403)
    assert_error(client.get(f"{API}/system/logs", headers=auth_headers["VIEWER"]), 403)


# ---------------------------------------------------------------- incidents & alerts
def test_manual_incident_flow(client, auth_headers):
    op = auth_headers["OPERATOR"]
    res = client.post(f"{API}/incidents", headers=op, json={"incident_type": "ROAD_ACCIDENT", "severity": "HIGH",
                                                            "description": "two-wheeler collision"})
    assert res.status_code == 201, res.text
    inc = res.json()
    assert inc["source"] == "MANUAL" and inc["risk_score"] is None and inc["is_demo"] is False
    assert {r["recommended_department"] for r in inc["response_actions"]} == {"Ambulance / EMS", "Traffic Police"}
    assert all(r["dispatch_status"] == "NOT_DISPATCHED" for r in inc["response_actions"])
    assert inc["alerts"][0]["status"] == "UNACKNOWLEDGED"
    assert inc["history"][0]["action"] == "INCIDENT_REPORTED"

    # status workflow
    res = client.patch(f"{API}/incidents/{inc['id']}", headers=op, json={"status": "RESOLVED"})
    assert res.status_code == 200 and res.json()["status"] == "RESOLVED"
    assert_error(client.patch(f"{API}/incidents/{inc['id']}", headers=op, json={"status": "IN_PROGRESS"}),
                 409, "INVALID_STATUS_TRANSITION")
    assert_error(client.patch(f"{API}/incidents/{inc['id']}", headers=op, json={}), 422, "VALIDATION_ERROR")
    assert_error(client.patch(f"{API}/incidents/{inc['id']}", headers=op, json={"status": "PANIC"}), 422)
    assert_error(client.get(f"{API}/incidents/99999", headers=op), 404, "INCIDENT_NOT_FOUND")


def test_incident_list_filters_and_pagination(client, auth_headers):
    op = auth_headers["OPERATOR"]
    for hazard, sev in [("FIRE", "CRITICAL"), ("FIRE", "LOW"), ("SMOKE", "MEDIUM"), ("PERSON_FALL", "HIGH")]:
        assert client.post(f"{API}/incidents", headers=op, json={"incident_type": hazard, "severity": sev}).status_code == 201
    page = client.get(f"{API}/incidents", headers=op, params={"page_size": 2}).json()
    assert page["total"] == 4 and page["pages"] == 2 and len(page["items"]) == 2
    fires = client.get(f"{API}/incidents", headers=op, params={"hazard_type": "FIRE"}).json()
    assert fires["total"] == 2
    crit = client.get(f"{API}/incidents", headers=op, params={"severity": "CRITICAL", "active_only": True}).json()
    assert crit["total"] == 1 and crit["items"][0]["recommended_department"] == "Fire Brigade"
    future = client.get(f"{API}/incidents", headers=op, params={"date_from": "2099-01-01T00:00:00Z"}).json()
    assert future["total"] == 0
    assert_error(client.get(f"{API}/incidents", headers=op, params={"date_from": "2026-02-01T00:00:00Z",
                                                                    "date_to": "2026-01-01T00:00:00Z"}),
                 400, "INVALID_DATE_RANGE")
    assert_error(client.get(f"{API}/incidents", headers=op, params={"page_size": 1000}), 422, "VALIDATION_ERROR")
    assert_error(client.get(f"{API}/incidents", headers=op, params={"severity": "APOCALYPTIC"}), 422)


def test_alert_acknowledgement_api(client, auth_headers):
    op = auth_headers["OPERATOR"]
    client.post(f"{API}/incidents", headers=op, json={"incident_type": "SMOKE", "severity": "MEDIUM"})
    alerts = client.get(f"{API}/alerts", headers=op, params={"status": "UNACKNOWLEDGED"}).json()
    assert alerts["total"] == 1
    alert_id = alerts["items"][0]["id"]
    assert_error(client.patch(f"{API}/alerts/{alert_id}/acknowledge", headers=auth_headers["VIEWER"]), 403)
    res = client.patch(f"{API}/alerts/{alert_id}/acknowledge", headers=op)
    assert res.status_code == 200 and res.json()["status"] == "ACKNOWLEDGED" and res.json()["acknowledged_at"]
    assert_error(client.patch(f"{API}/alerts/{alert_id}/acknowledge", headers=op), 409, "ALERT_ALREADY_ACKNOWLEDGED")
    assert_error(client.patch(f"{API}/alerts/424242/acknowledge", headers=op), 404, "ALERT_NOT_FOUND")
    assert client.get(f"{API}/alerts", headers=op, params={"status": "UNACKNOWLEDGED"}).json()["total"] == 0


def test_dashboard_summary_counts(client, auth_headers):
    op = auth_headers["OPERATOR"]
    ids = [client.post(f"{API}/incidents", headers=op, json={"incident_type": h, "severity": s}).json()["id"]
           for h, s in [("FIRE", "CRITICAL"), ("SMOKE", "LOW"), ("FIRE", "HIGH")]]
    client.patch(f"{API}/incidents/{ids[1]}", headers=op, json={"status": "RESOLVED"})
    s = client.get(f"{API}/dashboard/summary", headers=auth_headers["VIEWER"]).json()
    assert s["active_incidents"] == 2 and s["critical_incidents"] == 1 and s["resolved_incidents"] == 1
    assert s["unacknowledged_alerts"] == 3 and s["by_hazard"]["FIRE"] == 2
    assert sum(d["count"] for d in s["daily"]) == 3
    assert s["model"]["model_status"] == "DEMO_MODE"


def test_system_config_and_logs(client, auth_headers):
    cfg = client.get(f"{API}/system/config", headers=auth_headers["VIEWER"]).json()
    assert cfg["severity_bands"]["CRITICAL"][1] == 100
    assert "jwt" not in str(cfg).lower()
    logs = client.get(f"{API}/system/logs", headers=auth_headers["OPERATOR"]).json()
    assert any(item["action"] == "LOGIN" for item in logs["items"])
