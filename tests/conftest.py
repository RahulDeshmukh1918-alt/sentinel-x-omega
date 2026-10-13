"""Shared fixtures.

Pure unit tests (tests/unit) need only numpy, OpenCV and Pydantic. Fixtures that
need SQLAlchemy/FastAPI import them lazily so unit tests run without them.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from backend.app.core.config import Settings, load_settings
from scripts.setup.generate_sample_video import generate

TEST_PASSWORD = "Str0ng-test-pass"
os.environ.setdefault("BCRYPT_ROUNDS", "4")  # fast hashing in tests only


@pytest.fixture(scope="session")
def sample_dir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("sample_videos")


@pytest.fixture(scope="session")
def sample_video(sample_dir) -> Path:
    """Synthetic clip: 1-frame flash at 1 s (noise) + fire-like blob from 3 s to 8 s."""
    return generate(sample_dir / "synthetic_fire_demo.mp4", seconds=10.0)


def make_settings(tmp_path: Path, sample_dir: Path, **overrides) -> Settings:
    env = {
        "ENVIRONMENT": "test",
        "JWT_SECRET_KEY": "test-secret-key-0123456789abcdef0123456789",
        "DETECTOR_MODE": "demo",
        "MODEL_WEIGHTS_PATH": str(tmp_path / "missing_weights.pt"),
        "DATABASE_URL": f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        "SAMPLE_VIDEO_DIR": str(sample_dir),
        "UPLOAD_DIR": str(tmp_path / "uploads"),
        "SERVE_FRONTEND": "false",
        "LOG_LEVEL": "WARNING",
    }
    env.update({k.upper(): str(v) for k, v in overrides.items()})
    return load_settings(env=env, dotenv_path=tmp_path / "no.env")


@pytest.fixture
def settings(tmp_path, sample_dir) -> Settings:
    return make_settings(tmp_path, sample_dir)


# ---------------------------------------------------------------- database / API (lazy imports)
@pytest.fixture
def db_engine(settings):
    pytest.importorskip("sqlalchemy")
    from backend.app.database import connection

    engine = connection.configure_database(settings.database_url)
    connection.init_db()
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    from backend.app.database import connection

    session = connection.get_session_factory()()
    yield session
    session.close()


@pytest.fixture
def create_user(db_session):
    pytest.importorskip("bcrypt")
    from backend.app.core.enums import UserRole
    from backend.app.core.security import hash_password
    from backend.app.models import User

    def _create(role: UserRole = UserRole.ADMIN, email: str | None = None, password: str = TEST_PASSWORD):
        user = User(name=f"Test {role.value.title()}", email=email or f"{role.value.lower()}@example.com",
                    password_hash=hash_password(password), role=role)
        db_session.add(user)
        db_session.commit()
        return user

    return _create


def build_client(settings):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from backend.app.main import create_app

    return TestClient(create_app(settings))


@pytest.fixture
def client(settings, db_engine):
    with build_client(settings) as c:
        yield c


def login(client, email: str, password: str = TEST_PASSWORD) -> dict:
    res = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def auth_headers(client, create_user):
    """Headers for one user of each role."""
    from backend.app.core.enums import UserRole

    headers = {}
    for role in UserRole:
        user = create_user(role)
        headers[role.value] = login(client, user.email)
    return headers


def wait_for_job(client, headers, job_id: str, timeout: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/v1/detection/jobs/{job_id}", headers=headers).json()
        if job["status"] not in ("QUEUED", "RUNNING"):
            return job
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")
