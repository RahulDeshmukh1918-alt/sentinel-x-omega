# Testing

## How to run

```bash
pip install -r requirements.txt
pytest                         # everything
pytest tests/unit              # pure logic: no database or web server needed
pytest tests/integration       # SQLAlchemy models, services and the REST API (TestClient)
pytest tests/system            # end-to-end pipeline + CLI demo
pytest -m "not slow"           # skip the longer end-to-end test
```

Tests generate their own **synthetic** video (`scripts/setup/generate_sample_video.py`):
a dark scene with moving grey blocks, a one-frame orange flash at 1 s (must be
rejected) and a flickering orange blob from 3 s to 8 s (must become exactly one
incident). Each test uses a temporary SQLite file and temporary upload folder;
no real footage is needed. `BCRYPT_ROUNDS=4` is set for speed in tests only.

## Coverage of the required scenarios

| Requirement | Test file(s) |
|---|---|
| Risk-score calculation | `unit/test_risk_service.py` |
| Severity assignment / band boundaries | `unit/test_risk_service.py` |
| Detection (confidence) filtering | `unit/test_postprocessor.py` |
| Temporal validation | `unit/test_postprocessor.py`, `unit/test_pipeline.py` |
| Incident creation | `integration/test_incident_alert_services.py`, `integration/test_api_detection.py`, `system/test_end_to_end.py` |
| Duplicate incident prevention | `unit/test_postprocessor.py` (track level), `integration/test_incident_alert_services.py`, `system/test_end_to_end.py` |
| Alert acknowledgement | `integration/test_incident_alert_services.py`, `integration/test_api.py` |
| Database operations | `integration/test_database.py` |
| API validation | `integration/test_api.py`, `integration/test_api_detection.py` |
| Error handling / error envelope | `integration/test_api.py`, `unit/test_video_source.py` |
| Missing model weights | `unit/test_detector.py`, `integration/test_api_detection.py` |
| Camera unavailable | `unit/test_video_source.py`, `integration/test_api_detection.py` |
| Response recommendations | `unit/test_response_service.py` |
| Auth / roles / passwords / JWT | `unit/test_security.py`, `integration/test_api.py` |
| Upload type/size limits, path traversal | `integration/test_api_detection.py`, `unit/test_preprocessor_and_validators.py` |

## Execution record

Recorded honestly; update this table whenever you run the suite.

| Date | Environment | Command | Result |
|---|---|---|---|
| 2026-10-14 | Python 3.13, OpenCV 5.0, NumPy 2.5, Pydantic 2.13, pytest 9.1 — *FastAPI, SQLAlchemy and bcrypt could not be installed in that environment (no package-index access)* | `pytest` | **126 passed, 8 skipped.** Passed: all of `tests/unit` except the bcrypt tests, plus `tests/system/test_cli_demo.py`. Skipped (not run): `tests/integration/*`, `tests/system/test_end_to_end.py`, 3 bcrypt tests in `tests/unit/test_security.py`. |
| | your machine | `pytest` | *run and record here* |

The skipped integration and end-to-end tests have **not yet been executed** and
must be run on a machine with `requirements.txt` installed before claiming the
API/database layer is tested.

## Not covered by automated tests

* The browser dashboard (manual test checklist below).
* Real webcams / RTSP cameras (only the unavailable-camera path is automated).
* Model accuracy — no trained model exists yet (see `ml/README.md`).

## Manual dashboard checklist

1. Sign in with the admin created by `create_admin.py`; wrong password shows an error.
2. Overview shows five summary cards with real counts and the **Demo detector** badge.
3. Live monitoring → **Start** on "Demo Feed - Synthetic" → job progresses, processed frame
   appears with a DEMO banner, an incident link appears.
4. Incidents → filters by hazard/severity/status/date change the table; pagination works.
5. Incident detail → recommendations say "Advisory only · not dispatched"; status buttons
   follow the allowed transitions; history shows audit entries.
6. Alerts → acknowledge removes it from the unacknowledged list; the sidebar count drops.
7. Cameras (admin) → add/edit/delete; an RTSP password never appears after saving.
8. Viewer account → no edit/start/acknowledge buttons; API returns 403 if forced.
9. Resize to phone width → sidebar becomes a horizontal menu, tables scroll horizontally.
