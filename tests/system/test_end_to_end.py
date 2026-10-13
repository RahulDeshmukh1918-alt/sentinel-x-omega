"""End-to-end: camera source -> detection -> validation -> risk -> incident -> response -> alert -> audit -> dashboard."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from tests.conftest import wait_for_job  # noqa: E402

pytestmark = [pytest.mark.system, pytest.mark.slow]
API = "/api/v1"


def test_full_workflow_and_duplicate_prevention(client, auth_headers, sample_video):
    admin, op = auth_headers["ADMIN"], auth_headers["OPERATOR"]
    loc = client.post(f"{API}/locations", headers=admin,
                      json={"name": "Shivajinagar depot", "latitude": 18.5308, "longitude": 73.8475}).json()
    cam = client.post(f"{API}/cameras", headers=admin, json={
        "name": "Depot CCTV 1", "source_type": "FILE", "source_uri": sample_video.name, "location_id": loc["id"]}).json()

    # --- run 1: one continuous fire-like event -> exactly one incident
    job = client.post(f"{API}/detection/start", headers=op, json={"camera_id": cam["id"]}).json()
    job = wait_for_job(client, op, job["id"])
    assert job["status"] == "COMPLETED", job
    assert len(job["incident_ids"]) == 1
    incident_id = job["incident_ids"][0]

    inc = client.get(f"{API}/incidents/{incident_id}", headers=op).json()
    assert inc["incident_type"] == "FIRE" and inc["camera_id"] == cam["id"] and inc["location_id"] == loc["id"]
    assert inc["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL") and 0 <= inc["risk_score"] <= 100
    assert inc["is_demo"] and inc["detections"] and all(d["is_demo"] for d in inc["detections"])
    assert inc["response_actions"][0]["recommended_department"] == "Fire Brigade"
    assert any(a["alert_type"] == "INCIDENT_CREATED" for a in inc["alerts"])
    actions = [h["action"] for h in inc["history"]]
    assert "INCIDENT_CREATED" in actions and "ALERT_CREATED" in actions and "EVENT_ENDED" in actions

    cam_after = client.get(f"{API}/cameras/{cam['id']}", headers=op).json()
    assert cam_after["status"] == "ONLINE" and cam_after["last_seen_at"]

    # --- run 2 on the same camera within the de-dup window -> merged, still one incident
    job2 = client.post(f"{API}/detection/start", headers=op, json={"camera_id": cam["id"]}).json()
    job2 = wait_for_job(client, op, job2["id"])
    assert job2["incident_ids"] == [incident_id]
    listing = client.get(f"{API}/incidents", headers=op, params={"camera_id": cam["id"]}).json()
    assert listing["total"] == 1
    merged = client.get(f"{API}/incidents/{incident_id}", headers=op).json()
    assert merged["frames_observed"] > inc["frames_observed"]
    assert "INCIDENT_MERGED" in [h["action"] for h in merged["history"]]

    # --- operator closes the loop
    alert_id = merged["alerts"][0]["id"]
    assert client.patch(f"{API}/alerts/{alert_id}/acknowledge", headers=op).status_code == 200
    assert client.patch(f"{API}/incidents/{incident_id}", headers=op, json={"status": "RESOLVED"}).status_code == 200

    summary = client.get(f"{API}/dashboard/summary", headers=op).json()
    assert summary["resolved_incidents"] == 1 and summary["active_incidents"] == 0
    assert summary["online_cameras"] == 1 and summary["demo_incidents"] == 1

    logs = client.get(f"{API}/system/logs", headers=op, params={"module": "detection_service", "page_size": 100}).json()
    assert {"DETECTION_STARTED", "DETECTION_FINISHED"} <= {l["action"] for l in logs["items"]}
