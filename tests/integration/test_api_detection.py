"""Detection endpoints: model status, uploads, start/stop, missing model, unavailable cameras."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from tests.conftest import build_client, login, make_settings, wait_for_job  # noqa: E402

pytestmark = pytest.mark.integration
API = "/api/v1"


def test_status_reports_demo_mode(client, auth_headers):
    res = client.get(f"{API}/detection/status", headers=auth_headers["VIEWER"])
    assert res.status_code == 200
    model = res.json()["model"]
    assert model["model_status"] == "DEMO_MODE" and model["is_demo"] is True
    assert model["detection_enabled"] is True


def test_missing_model_weights_disable_detection(tmp_path, sample_dir, create_user, db_engine):
    settings = make_settings(tmp_path, sample_dir, detector_mode="yolo")
    with build_client(settings) as client:
        user = create_user()
        headers = login(client, user.email)
        model = client.get(f"{API}/detection/status", headers=headers).json()["model"]
        assert model["model_status"] == "MODEL_NOT_AVAILABLE" and model["detection_enabled"] is False
        cam = client.post(f"{API}/cameras", headers=headers,
                          json={"name": "c", "source_type": "WEBCAM", "source_uri": "0"}).json()
        res = client.post(f"{API}/detection/start", headers=headers, json={"camera_id": cam["id"]})
        assert res.status_code == 503 and res.json()["error"]["code"] == "MODEL_NOT_AVAILABLE"
        up = client.post(f"{API}/detection/analyze", headers=headers,
                         files={"file": ("clip.mp4", b"\x00" * 100, "video/mp4")})
        assert up.status_code == 503
        assert list((tmp_path / "uploads").glob("*")) == []  # rejected upload not left on disk


def test_upload_rejects_wrong_type_empty_and_oversize(tmp_path, sample_dir, create_user, db_engine):
    settings = make_settings(tmp_path, sample_dir, max_upload_mb=1)
    with build_client(settings) as client:
        headers = login(client, create_user().email)
        bad = client.post(f"{API}/detection/analyze", headers=headers, files={"file": ("x.txt", b"hello", "text/plain")})
        assert bad.status_code == 415 and bad.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
        empty = client.post(f"{API}/detection/analyze", headers=headers, files={"file": ("x.mp4", b"", "video/mp4")})
        assert empty.status_code == 400 and empty.json()["error"]["code"] == "EMPTY_FILE"
        big = client.post(f"{API}/detection/analyze", headers=headers,
                          files={"file": ("x.mp4", b"\x00" * (1024 * 1024 + 10), "video/mp4")})
        assert big.status_code == 413 and big.json()["error"]["code"] == "FILE_TOO_LARGE"
        assert list((tmp_path / "uploads").glob("*")) == []


def test_upload_requires_operator(client, auth_headers):
    res = client.post(f"{API}/detection/analyze", headers=auth_headers["VIEWER"],
                      files={"file": ("x.mp4", b"\x00", "video/mp4")})
    assert res.status_code == 403


def test_invalid_video_job_fails_cleanly(client, auth_headers):
    op = auth_headers["OPERATOR"]
    res = client.post(f"{API}/detection/analyze", headers=op,
                      files={"file": ("corrupt.mp4", b"definitely not a video" * 50, "video/mp4")})
    assert res.status_code == 202, res.text
    job = wait_for_job(client, op, res.json()["id"])
    assert job["status"] == "FAILED" and job["error_code"] == "INVALID_VIDEO"


def test_uploaded_video_is_analysed_into_one_demo_incident(client, auth_headers, sample_video, settings):
    op = auth_headers["OPERATOR"]
    with sample_video.open("rb") as fh:
        res = client.post(f"{API}/detection/analyze", headers=op, files={"file": ("my clip.mp4", fh, "video/mp4")})
    assert res.status_code == 202, res.text
    job = wait_for_job(client, op, res.json()["id"])
    assert job["status"] == "COMPLETED", job
    assert job["source"] == "my_clip.mp4" and job["is_demo"] is True
    assert len(job["incident_ids"]) == 1 and job["frames_processed"] > 0
    snap = client.get(f"{API}/detection/jobs/{job['id']}/snapshot", headers=op)
    assert snap.status_code == 200 and snap.headers["content-type"] == "image/jpeg"

    inc = client.get(f"{API}/incidents/{job['incident_ids'][0]}", headers=op).json()
    assert inc["incident_type"] == "FIRE" and inc["source"] == "DEMO_HEURISTIC" and inc["is_demo"]
    assert 0 <= inc["risk_score"] <= 100 and inc["detections"]
    assert inc["response_actions"][0]["recommended_department"] == "Fire Brigade"
    assert list(settings.upload_path.glob("*")) == []  # footage deleted after analysis


def test_unavailable_camera_marks_job_failed_and_camera_offline(client, auth_headers):
    admin = auth_headers["ADMIN"]
    cam = client.post(f"{API}/cameras", headers=admin,
                      json={"name": "Ghost", "source_type": "WEBCAM", "source_uri": "15"}).json()
    res = client.post(f"{API}/detection/start", headers=admin, json={"camera_id": cam["id"]})
    assert res.status_code == 202
    job = wait_for_job(client, admin, res.json()["id"])
    assert job["status"] == "FAILED" and job["error_code"] == "CAMERA_UNAVAILABLE"
    cam = client.get(f"{API}/cameras/{cam['id']}", headers=admin).json()
    assert cam["status"] == "OFFLINE" and cam["last_error"]


def test_start_stop_and_conflicts(client, auth_headers, sample_video):
    admin = auth_headers["ADMIN"]
    cam = client.post(f"{API}/cameras", headers=admin,
                      json={"name": "Sample", "source_type": "FILE", "source_uri": sample_video.name}).json()
    assert client.post(f"{API}/detection/start", headers=admin, json={"camera_id": 999}).status_code == 404
    job = client.post(f"{API}/detection/start", headers=admin, json={"camera_id": cam["id"]}).json()
    again = client.post(f"{API}/detection/start", headers=admin, json={"camera_id": cam["id"]})
    if again.status_code != 202:  # first job may already have finished on a fast machine
        assert again.json()["error"]["code"] == "DETECTION_ALREADY_RUNNING"
    stop = client.post(f"{API}/detection/stop", headers=admin, json={"job_id": job["id"]})
    assert stop.status_code in (200, 409)
    final = wait_for_job(client, admin, job["id"])
    assert final["status"] in ("STOPPED", "COMPLETED")
    assert client.post(f"{API}/detection/stop", headers=admin, json={"job_id": job["id"]}).status_code == 409
    assert client.post(f"{API}/detection/stop", headers=admin, json={}).status_code == 422
    assert client.get(f"{API}/detection/jobs/nope1234", headers=admin).status_code == 404
