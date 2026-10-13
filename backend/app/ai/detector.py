"""Detection Agent: model interface and implementations.

Two implementations exist:

* ``YoloHazardDetector`` — wraps a *custom-trained* Ultralytics YOLO model whose
  class names are mapped to supported hazards via ``MODEL_CLASS_MAP``. The model
  classes are verified on load; a stock COCO model has no hazard classes and is
  therefore rejected with ``MODEL_NOT_AVAILABLE`` instead of producing fake
  hazard detections.
* ``DemoFireColorDetector`` — a clearly labelled **demonstration** heuristic that
  flags bright red/orange/yellow regions as "fire-like". It exists only so the
  full pipeline can be demonstrated without trained weights. It is not a fire
  detector: any orange object can trigger it, and real fire can be missed.

Weights are never downloaded automatically; only a local file is loaded.
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from pathlib import Path

import cv2
import numpy as np

from backend.app.core.enums import HazardType, ModelStatus


class ModelNotAvailableError(RuntimeError):
    code = "MODEL_NOT_AVAILABLE"


@dataclass(frozen=True)
class Detection:
    hazard_type: HazardType
    confidence: float
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 (pixels)
    raw_label: str
    is_demo: bool = False

    def scaled(self, factor: float) -> "Detection":
        x1, y1, x2, y2 = self.bbox
        return replace(self, bbox=(x1 * factor, y1 * factor, x2 * factor, y2 * factor))


@dataclass
class DetectorInfo:
    status: ModelStatus
    mode: str
    name: str
    is_demo: bool
    supported_hazards: list[str] = field(default_factory=list)
    message: str = ""
    model_classes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "model_status": self.status.value,
            "mode": self.mode,
            "detector": self.name,
            "is_demo": self.is_demo,
            "supported_hazards": self.supported_hazards,
            "unsupported_hazards": sorted({h.value for h in HazardType} - set(self.supported_hazards)),
            "message": self.message,
            "model_classes": self.model_classes,
        }


class BaseDetector(ABC):
    name: str = "base"
    is_demo: bool = False

    @property
    @abstractmethod
    def supported_hazards(self) -> set[HazardType]: ...

    @abstractmethod
    def detect(self, image: np.ndarray) -> list[Detection]:
        """Return hazard detections for one BGR image."""


# ----------------------------------------------------------------------
class YoloHazardDetector(BaseDetector):
    name = "ultralytics-yolo"
    is_demo = False

    def __init__(self, weights_path: Path, class_map: dict[str, str], device: str = "cpu", min_confidence: float = 0.1):
        weights_path = Path(weights_path)
        if not weights_path.is_file():
            raise ModelNotAvailableError(
                f"model weights not found at '{weights_path.name}'. Train a hazard model (see ml/training) "
                "and set MODEL_WEIGHTS_PATH, or use DETECTOR_MODE=demo."
            )
        try:
            from ultralytics import YOLO  # imported lazily: heavy dependency (torch)
        except ImportError as exc:
            raise ModelNotAvailableError(
                "ultralytics is not installed. Install requirements-ml.txt to enable YOLO inference."
            ) from exc

        self._model = YOLO(str(weights_path))
        self._device = device
        self._min_conf = min_confidence
        self._lock = threading.Lock()  # a single model instance is not guaranteed thread-safe
        names = self._model.names
        self.model_classes = [str(n) for n in (names.values() if isinstance(names, dict) else names)]
        self._label_to_hazard = {
            label: HazardType(class_map[label.strip().lower()])
            for label in self.model_classes
            if label.strip().lower() in class_map
        }
        if not self._label_to_hazard:
            preview = ", ".join(self.model_classes[:12])
            raise ModelNotAvailableError(
                f"none of the model's classes map to a supported hazard (classes: {preview}...). "
                "A generic COCO model cannot detect fire, smoke, accidents, sparks or falls; "
                "a custom-trained model is required."
            )

    @property
    def supported_hazards(self) -> set[HazardType]:
        return set(self._label_to_hazard.values())

    def detect(self, image: np.ndarray) -> list[Detection]:
        with self._lock:
            results = self._model.predict(image, conf=self._min_conf, device=self._device, verbose=False)
        out: list[Detection] = []
        for result in results:
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            for cls_id, conf, xyxy in zip(boxes.cls.tolist(), boxes.conf.tolist(), boxes.xyxy.tolist(), strict=False):
                label = str(result.names[int(cls_id)])
                hazard = self._label_to_hazard.get(label)
                if hazard is None:
                    continue  # class the model knows but we don't treat as a hazard
                out.append(Detection(hazard, float(conf), tuple(float(v) for v in xyxy), label))
        return out


# ----------------------------------------------------------------------
class DemoFireColorDetector(BaseDetector):
    """DEMO ONLY. HSV colour heuristic for bright flame-coloured regions."""

    name = "demo-fire-colour-heuristic"
    is_demo = True
    RAW_LABEL = "demo:fire_like_colour"

    def __init__(self, min_area_ratio: float = 0.004, hue_max: int = 35, sat_min: int = 120, val_min: int = 170):
        self.min_area_ratio = min_area_ratio
        self.lower = np.array([0, sat_min, val_min], dtype=np.uint8)
        self.upper = np.array([hue_max, 255, 255], dtype=np.uint8)
        self._kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    @property
    def supported_hazards(self) -> set[HazardType]:
        return {HazardType.FIRE}

    def detect(self, image: np.ndarray) -> list[Detection]:
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self.lower, self.upper)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self._kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        frame_area = float(image.shape[0] * image.shape[1])
        out: list[Detection] = []
        for contour in contours:
            area = cv2.contourArea(contour)
            ratio = area / frame_area
            if ratio < self.min_area_ratio:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            region = hsv[y : y + h, x : x + w]
            region_mask = mask[y : y + h, x : x + w] > 0
            brightness = float(region[..., 2][region_mask].mean()) / 255.0 if region_mask.any() else 0.0
            # Heuristic score, NOT a calibrated probability.
            score = 0.35 + 0.35 * brightness + 0.30 * min(1.0, ratio / 0.03)
            out.append(
                Detection(HazardType.FIRE, round(min(score, 0.99), 3), (float(x), float(y), float(x + w), float(y + h)),
                          self.RAW_LABEL, is_demo=True)
            )
        return out


# ----------------------------------------------------------------------
def build_detector(mode: str, weights_path: Path, class_map: dict[str, str], device: str = "cpu",
                   min_confidence: float = 0.1) -> tuple[BaseDetector | None, DetectorInfo]:
    """Create the configured detector.

    * ``yolo``: trained model or nothing (``MODEL_NOT_AVAILABLE``).
    * ``demo``: the labelled demo heuristic.
    * ``auto``: trained model if usable, otherwise the demo heuristic (status ``DEMO_MODE``).
    """
    if mode in ("yolo", "auto"):
        try:
            det = YoloHazardDetector(weights_path, class_map, device, min_confidence)
            return det, DetectorInfo(
                ModelStatus.READY, mode, det.name, False,
                sorted(h.value for h in det.supported_hazards),
                f"loaded {Path(weights_path).name}", det.model_classes,
            )
        except ModelNotAvailableError as exc:
            if mode == "yolo":
                return None, DetectorInfo(ModelStatus.MODEL_NOT_AVAILABLE, mode, "none", False, [], str(exc))
            reason = str(exc)
    else:
        reason = "DETECTOR_MODE=demo"

    demo = DemoFireColorDetector()
    return demo, DetectorInfo(
        ModelStatus.DEMO_MODE, mode, demo.name, True, sorted(h.value for h in demo.supported_hazards),
        "DEMONSTRATION MODE: colour heuristic for fire-like regions only; not a validated hazard detector. "
        f"Reason: {reason}",
    )
