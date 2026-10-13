"""Video input: uploaded/sample files, local webcams and RTSP/HTTP streams (OpenCV).

Usage::

    with VideoSource(SourceType.FILE, "/abs/path/clip.mp4") as src:
        for frame_index, t_seconds, frame in src.frames(stride=5):
            ...

Resources are always released on exit, including on exceptions.
"""
from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import cv2
import numpy as np

from backend.app.core.enums import SourceType
from backend.app.core.validators import mask_credentials

DEFAULT_FPS = 25.0


class VideoSourceError(Exception):
    """Raised when a source cannot be opened or read. ``code`` is API-friendly."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class VideoSource:
    def __init__(
        self,
        source_type: SourceType,
        uri: str,
        *,
        open_timeout_ms: int = 5000,
        max_consecutive_read_failures: int = 25,
    ):
        self.source_type = SourceType(source_type)
        self.uri = uri
        self.open_timeout_ms = open_timeout_ms
        self.max_consecutive_read_failures = max_consecutive_read_failures
        self._cap: cv2.VideoCapture | None = None
        self.fps: float = DEFAULT_FPS
        self.frame_count: int | None = None
        self.width: int | None = None
        self.height: int | None = None

    # ------------------------------------------------------------------
    @property
    def is_live(self) -> bool:
        return self.source_type in (SourceType.WEBCAM, SourceType.RTSP)

    @property
    def display_name(self) -> str:
        if self.source_type == SourceType.FILE:
            return Path(self.uri).name
        if self.source_type == SourceType.WEBCAM:
            return f"webcam:{self.uri}"
        return mask_credentials(self.uri)

    def open(self) -> "VideoSource":
        if self._cap is not None:
            return self
        if self.source_type == SourceType.FILE:
            path = Path(self.uri)
            if not path.is_file():
                raise VideoSourceError("SOURCE_NOT_FOUND", f"video file not found: {path.name}")
            cap = cv2.VideoCapture(str(path))
        elif self.source_type == SourceType.WEBCAM:
            cap = cv2.VideoCapture(int(self.uri))
        else:
            cap = self._open_stream(self.uri)

        if cap is None or not cap.isOpened():
            if cap is not None:
                cap.release()
            if self.source_type == SourceType.FILE:
                raise VideoSourceError("INVALID_VIDEO", f"could not decode video file {self.display_name}")
            raise VideoSourceError("CAMERA_UNAVAILABLE", f"camera source {self.display_name} is unavailable")

        # Confirm at least one frame can actually be decoded.
        ok, frame = cap.read()
        if not ok or frame is None:
            cap.release()
            code = "INVALID_VIDEO" if self.source_type == SourceType.FILE else "CAMERA_UNAVAILABLE"
            raise VideoSourceError(code, f"no frames could be read from {self.display_name}")
        self.height, self.width = frame.shape[:2]
        if self.source_type == SourceType.FILE:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            self.frame_count = count if count > 0 else None
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        self.fps = fps if 1.0 <= fps <= 240.0 else DEFAULT_FPS
        self._first_frame = frame
        self._cap = cap
        return self

    def _open_stream(self, uri: str) -> cv2.VideoCapture:
        timeout_prop = getattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC", None)
        if timeout_prop is not None:
            try:
                return cv2.VideoCapture(uri, cv2.CAP_FFMPEG, [timeout_prop, self.open_timeout_ms])
            except (cv2.error, TypeError):
                pass
        return cv2.VideoCapture(uri)

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self) -> "VideoSource":
        return self.open()

    def __exit__(self, *exc) -> None:
        self.release()

    # ------------------------------------------------------------------
    def frames(self, stride: int = 1, max_frames: int | None = None) -> Iterator[tuple[int, float, np.ndarray]]:
        """Yield ``(frame_index, seconds_since_start, frame_bgr)`` for every ``stride``-th frame.

        For files, skipped frames are only grabbed (not decoded), which is much cheaper.
        For live sources, the timestamp is wall-clock time since the stream was opened.
        """
        if self._cap is None:
            raise RuntimeError("VideoSource.open() must be called first")
        stride = max(1, int(stride))
        cap = self._cap
        started = time.monotonic()
        index = -1
        yielded = 0
        failures = 0
        while True:
            index += 1
            if max_frames is not None and index >= max_frames:
                return
            sample = index % stride == 0
            if self.is_live or sample:
                ok, frame = cap.read()
            else:
                ok, frame = cap.grab(), None
            if not ok:
                if not self.is_live:
                    return  # end of file
                failures += 1
                if failures >= self.max_consecutive_read_failures:
                    raise VideoSourceError("STREAM_LOST", f"stream {self.display_name} stopped delivering frames")
                time.sleep(0.05)
                index -= 1
                continue
            failures = 0
            if not sample or frame is None:
                continue
            t = (time.monotonic() - started) if self.is_live else index / self.fps
            yielded += 1
            yield index, round(t, 3), frame
