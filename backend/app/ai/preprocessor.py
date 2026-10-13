"""Frame preprocessing before inference."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


class InvalidFrameError(ValueError):
    pass


@dataclass(frozen=True)
class PreprocessedFrame:
    image: np.ndarray  # BGR uint8, possibly downscaled
    scale: float       # resized = original * scale (<= 1.0)
    original_size: tuple[int, int]  # (width, height)


def preprocess(frame: np.ndarray, max_width: int = 960) -> PreprocessedFrame:
    """Validate the frame, convert to 3-channel BGR uint8 and downscale wide frames.

    Downscaling keeps inference time bounded on CPU-only lab machines. Bounding
    boxes are mapped back to the original resolution with ``scale``.
    """
    if not isinstance(frame, np.ndarray) or frame.ndim not in (2, 3) or frame.size == 0:
        raise InvalidFrameError("frame must be a non-empty HxW or HxWxC numpy array")
    img = frame
    if img.dtype != np.uint8:
        img = np.clip(img, 0, 255).astype(np.uint8)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    elif img.shape[2] != 3:
        raise InvalidFrameError("frame must have 1, 3 or 4 channels")

    h, w = img.shape[:2]
    scale = 1.0
    if w > max_width:
        scale = max_width / float(w)
        img = cv2.resize(img, (max_width, max(1, int(round(h * scale)))), interpolation=cv2.INTER_AREA)
    return PreprocessedFrame(image=img, scale=scale, original_size=(w, h))
