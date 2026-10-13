import pytest
from pydantic import ValidationError

from backend.app.core.config import DEFAULT_JWT_SECRET, load_settings
from backend.app.core.enums import HazardType


def test_defaults_load(tmp_path):
    s = load_settings(env={}, dotenv_path=tmp_path / "none")
    assert s.detector_mode == "auto"
    assert s.severity_band_low_max == 30
    assert s.threshold_for(HazardType.FIRE) == s.default_confidence_threshold


def test_env_overrides_including_json_and_lists(tmp_path):
    s = load_settings(env={
        "DETECTOR_MODE": "demo",
        "FRAME_STRIDE": "3",
        "CONFIDENCE_THRESHOLDS": '{"SMOKE": 0.7}',
        "CORS_ORIGINS": "http://a.test, http://b.test",
        "ALLOWED_VIDEO_EXTENSIONS": "mp4,AVI",
    }, dotenv_path=tmp_path / "none")
    assert s.detector_mode == "demo" and s.frame_stride == 3
    assert s.threshold_for(HazardType.SMOKE) == 0.7
    assert s.cors_origins == ["http://a.test", "http://b.test"]
    assert s.allowed_video_extensions == [".mp4", ".avi"]


def test_dotenv_file_is_read_and_env_wins(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text('# comment\nFRAME_STRIDE=7\nAPP_NAME="Lab Build"\n')
    s = load_settings(env={"FRAME_STRIDE": "2"}, dotenv_path=env_file)
    assert s.frame_stride == 2 and s.app_name == "Lab Build"


@pytest.mark.parametrize("env", [
    {"SEVERITY_BAND_LOW_MAX": "60", "SEVERITY_BAND_MEDIUM_MAX": "50"},
    {"RISK_WEIGHT_CONFIDENCE": "0", "RISK_WEIGHT_PERSISTENCE": "0", "RISK_WEIGHT_SEVERITY": "0"},
    {"TEMPORAL_MIN_HITS": "9", "TEMPORAL_WINDOW_FRAMES": "4"},
    {"HAZARD_SEVERITY_FACTORS": '{"FIRE": 2}'},
    {"MODEL_CLASS_MAP": '{"fire": "EARTHQUAKE"}'},
    {"DETECTOR_MODE": "magic"},
])
def test_invalid_configuration_rejected(tmp_path, env):
    with pytest.raises(ValidationError):
        load_settings(env=env, dotenv_path=tmp_path / "none")


def test_production_requires_real_secret(tmp_path):
    with pytest.raises(ValidationError):
        load_settings(env={"ENVIRONMENT": "production"}, dotenv_path=tmp_path / "none")
    s = load_settings(env={"ENVIRONMENT": "production", "JWT_SECRET_KEY": "x" * 40}, dotenv_path=tmp_path / "none")
    assert s.jwt_secret_key != DEFAULT_JWT_SECRET


def test_public_view_has_no_secrets(settings):
    view = settings.public_view()
    flat = str(view)
    assert settings.jwt_secret_key not in flat
    assert "database_url" not in view
    assert view["external_dispatch"].startswith("NOT IMPLEMENTED")
