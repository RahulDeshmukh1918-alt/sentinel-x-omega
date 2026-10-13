import numpy as np
import cv2
import pytest

from backend.app.ai.detector import DemoFireColorDetector, ModelNotAvailableError, YoloHazardDetector, build_detector
from backend.app.core.config import DEFAULT_CLASS_MAP
from backend.app.core.enums import HazardType, ModelStatus


def test_missing_weights_raise_model_not_available(tmp_path):
    with pytest.raises(ModelNotAvailableError) as exc:
        YoloHazardDetector(tmp_path / "nope.pt", DEFAULT_CLASS_MAP)
    assert "not found" in str(exc.value)


def test_yolo_mode_without_weights_reports_model_not_available(tmp_path):
    detector, info = build_detector("yolo", tmp_path / "nope.pt", DEFAULT_CLASS_MAP)
    assert detector is None
    assert info.status == ModelStatus.MODEL_NOT_AVAILABLE
    assert info.as_dict()["model_status"] == "MODEL_NOT_AVAILABLE"
    assert info.supported_hazards == []


def test_auto_mode_falls_back_to_labelled_demo(tmp_path):
    detector, info = build_detector("auto", tmp_path / "nope.pt", DEFAULT_CLASS_MAP)
    assert isinstance(detector, DemoFireColorDetector)
    assert info.status == ModelStatus.DEMO_MODE and info.is_demo
    assert "DEMONSTRATION" in info.message
    d = info.as_dict()
    assert d["supported_hazards"] == ["FIRE"]
    assert set(d["unsupported_hazards"]) == {"SMOKE", "ROAD_ACCIDENT", "ELECTRICAL_SPARK", "PERSON_FALL"}


def test_demo_mode_explicit(tmp_path):
    detector, info = build_detector("demo", tmp_path / "x.pt", DEFAULT_CLASS_MAP)
    assert detector.is_demo and info.status == ModelStatus.DEMO_MODE


def test_demo_detector_flags_flame_coloured_region():
    img = np.full((240, 320, 3), 30, np.uint8)
    cv2.circle(img, (200, 120), 30, (0, 120, 255), -1)  # BGR orange
    dets = DemoFireColorDetector().detect(img)
    assert len(dets) == 1
    d = dets[0]
    assert d.hazard_type == HazardType.FIRE and d.is_demo and 0 < d.confidence < 1
    x1, y1, x2, y2 = d.bbox
    assert x1 < 200 < x2 and y1 < 120 < y2


def test_demo_detector_ignores_dark_and_tiny_regions():
    img = np.full((240, 320, 3), 30, np.uint8)
    cv2.rectangle(img, (10, 10), (100, 100), (120, 120, 120), -1)  # grey block
    cv2.circle(img, (250, 200), 2, (0, 120, 255), -1)  # too small
    assert DemoFireColorDetector().detect(img) == []
