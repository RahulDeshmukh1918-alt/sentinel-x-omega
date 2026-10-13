"""Confidence filtering and temporal-persistence validation.

The temporal validator keeps one *track* per hazard type per video source.
A track is **confirmed** only when the hazard appears in at least
``min_hits`` of the last ``window_size`` processed frames. This suppresses
single-frame false positives. Once confirmed, later frames update the same
track (so one continuous event never creates multiple incidents) until the
hazard is absent for ``end_after_missed`` processed frames.

Simplification (documented limitation): simultaneous separate hazards of the
same type in one camera view are merged into one track.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from itertools import count

from backend.app.ai.detector import Detection
from backend.app.core.enums import HazardType


def filter_detections(
    detections: Iterable[Detection],
    thresholds: Mapping[HazardType, float],
    default_threshold: float,
    supported: set[HazardType] | None = None,
) -> list[Detection]:
    """Keep detections at/above their hazard's confidence threshold."""
    kept = []
    for d in detections:
        if supported is not None and d.hazard_type not in supported:
            continue
        if d.confidence >= thresholds.get(d.hazard_type, default_threshold):
            kept.append(d)
    return kept


def scale_detections(detections: Iterable[Detection], scale: float) -> list[Detection]:
    """Map boxes from a resized frame back to original pixels (``scale`` = resized/original)."""
    if scale == 1.0:
        return list(detections)
    inv = 1.0 / scale
    return [d.scaled(inv) for d in detections]


class EventKind(str, Enum):
    CONFIRMED = "CONFIRMED"
    UPDATED = "UPDATED"
    ENDED = "ENDED"


@dataclass(frozen=True)
class DetectionSample:
    frame_index: int
    time_s: float
    confidence: float
    bbox: tuple[float, float, float, float]
    raw_label: str
    is_demo: bool


@dataclass
class HazardTrack:
    track_id: int
    hazard_type: HazardType
    window: deque
    first_frame: int
    first_time_s: float
    last_frame: int = 0
    last_time_s: float = 0.0
    total_hits: int = 0
    missed: int = 0
    conf_sum: float = 0.0
    max_confidence: float = 0.0
    confirmed: bool = False
    is_demo: bool = False
    samples: list[DetectionSample] = field(default_factory=list)
    best: DetectionSample | None = None

    @property
    def window_hits(self) -> int:
        return sum(self.window)

    @property
    def mean_confidence(self) -> float:
        return self.conf_sum / self.total_hits if self.total_hits else 0.0


@dataclass(frozen=True)
class TrackEvent:
    kind: EventKind
    track_id: int
    hazard_type: HazardType
    first_frame: int
    last_frame: int
    first_time_s: float
    last_time_s: float
    total_hits: int
    mean_confidence: float
    max_confidence: float
    is_demo: bool
    best: DetectionSample | None
    samples: tuple[DetectionSample, ...]


class TemporalValidator:
    _ids = count(1)

    def __init__(self, window_size: int = 8, min_hits: int = 5, end_after_missed: int = 10, max_samples: int = 20):
        if not 1 <= min_hits <= window_size:
            raise ValueError("require 1 <= min_hits <= window_size")
        if end_after_missed < 1:
            raise ValueError("end_after_missed must be >= 1")
        self.window_size = window_size
        self.min_hits = min_hits
        self.end_after_missed = end_after_missed
        self.max_samples = max_samples
        self.tracks: dict[HazardType, HazardTrack] = {}

    # ------------------------------------------------------------------
    def update(self, frame_index: int, time_s: float, detections: Iterable[Detection]) -> list[TrackEvent]:
        best_per_hazard: dict[HazardType, Detection] = {}
        for d in detections:
            cur = best_per_hazard.get(d.hazard_type)
            if cur is None or d.confidence > cur.confidence:
                best_per_hazard[d.hazard_type] = d

        events: list[TrackEvent] = []
        # hazards seen this frame
        for hazard, det in best_per_hazard.items():
            track = self.tracks.get(hazard)
            if track is None:
                track = HazardTrack(
                    track_id=next(self._ids), hazard_type=hazard, window=deque(maxlen=self.window_size),
                    first_frame=frame_index, first_time_s=time_s,
                )
                self.tracks[hazard] = track
            self._record_hit(track, frame_index, time_s, det)
            if not track.confirmed and track.window_hits >= self.min_hits:
                track.confirmed = True
                events.append(self._event(EventKind.CONFIRMED, track))
            elif track.confirmed:
                events.append(self._event(EventKind.UPDATED, track))

        # hazards not seen this frame
        for hazard in list(self.tracks):
            if hazard in best_per_hazard:
                continue
            track = self.tracks[hazard]
            track.window.append(0)
            track.missed += 1
            if track.confirmed and track.missed >= self.end_after_missed:
                events.append(self._event(EventKind.ENDED, track))
                del self.tracks[hazard]
            elif not track.confirmed and track.window_hits == 0:
                del self.tracks[hazard]  # transient detection that never persisted
        return events

    def flush(self) -> list[TrackEvent]:
        """Close all confirmed tracks (call at end of a video)."""
        events = [self._event(EventKind.ENDED, t) for t in self.tracks.values() if t.confirmed]
        self.tracks.clear()
        return events

    # ------------------------------------------------------------------
    def _record_hit(self, track: HazardTrack, frame_index: int, time_s: float, det: Detection) -> None:
        track.window.append(1)
        track.missed = 0
        track.total_hits += 1
        track.conf_sum += det.confidence
        track.last_frame = frame_index
        track.last_time_s = time_s
        track.is_demo = track.is_demo or det.is_demo
        sample = DetectionSample(frame_index, time_s, det.confidence, det.bbox, det.raw_label, det.is_demo)
        if det.confidence > track.max_confidence:
            track.max_confidence = det.confidence
            track.best = sample
        if len(track.samples) < self.max_samples:
            track.samples.append(sample)

    @staticmethod
    def _event(kind: EventKind, t: HazardTrack) -> TrackEvent:
        return TrackEvent(
            kind=kind, track_id=t.track_id, hazard_type=t.hazard_type, first_frame=t.first_frame,
            last_frame=t.last_frame, first_time_s=t.first_time_s, last_time_s=t.last_time_s,
            total_hits=t.total_hits, mean_confidence=round(t.mean_confidence, 4),
            max_confidence=round(t.max_confidence, 4), is_demo=t.is_demo, best=t.best, samples=tuple(t.samples),
        )
