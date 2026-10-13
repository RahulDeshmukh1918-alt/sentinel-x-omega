"""Orchestration of the per-frame pipeline (framework-free and DB-free).

    frames -> preprocess -> Detection Agent -> confidence filter -> temporal validation
           -> Risk Assessment Agent -> Response Recommendation Agent -> IncidentSink

``IncidentSink`` is the boundary to persistence. ``DatabaseIncidentSink``
(services/incident_workflow.py) writes incidents/alerts/audit logs to SQL;
``InMemoryIncidentSink`` is used by the CLI ``--no-db`` demo and tests.

The "agents" are ordinary, explicitly-interfaced Python components called
in sequence — not autonomous AI agents.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

import cv2
import numpy as np

from backend.app.ai.detector import BaseDetector, Detection
from backend.app.ai.postprocessor import EventKind, TemporalValidator, TrackEvent, filter_detections, scale_detections
from backend.app.ai.preprocessor import preprocess
from backend.app.ai.video_source import VideoSource
from backend.app.core.enums import HazardType, Severity
from backend.app.services.response_service import ResponseRecommendation, ResponseRecommendationAgent
from backend.app.services.risk_service import RiskAssessment, RiskAssessmentAgent

SEVERITY_BGR = {
    Severity.CRITICAL: (40, 40, 230),
    Severity.HIGH: (0, 140, 255),
    Severity.MEDIUM: (0, 215, 255),
    Severity.LOW: (200, 200, 200),
}


@dataclass(frozen=True)
class PipelineConfig:
    frame_stride: int = 5
    max_frame_width: int = 960
    max_frames: int | None = None
    default_threshold: float = 0.5
    thresholds: dict[HazardType, float] = field(default_factory=dict)
    window_size: int = 8
    min_hits: int = 5
    end_after_missed: int = 10
    max_samples: int = 20
    update_every_n_hits: int = 10

    @classmethod
    def from_settings(cls, s) -> "PipelineConfig":
        return cls(
            frame_stride=s.frame_stride,
            max_frame_width=s.max_frame_width,
            max_frames=s.max_frames_per_job,
            default_threshold=s.default_confidence_threshold,
            thresholds={h: s.threshold_for(h) for h in HazardType},
            window_size=s.temporal_window_frames,
            min_hits=s.temporal_min_hits,
            end_after_missed=s.temporal_end_after_missed,
            max_samples=s.max_detections_stored_per_event,
            update_every_n_hits=s.incident_update_every_n_hits,
        )


@dataclass
class SourceContext:
    camera_id: int | None
    source_label: str
    job_id: str | None = None
    is_demo_detector: bool = False


@dataclass
class PipelineStats:
    frames_read: int = 0
    frames_processed: int = 0
    raw_detections: int = 0
    kept_detections: int = 0
    events_confirmed: int = 0
    events_ended: int = 0
    incident_ids: list[int] = field(default_factory=list)
    last_video_time_s: float = 0.0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    stopped_early: bool = False

    def as_dict(self) -> dict:
        return {
            "frames_read": self.frames_read,
            "frames_processed": self.frames_processed,
            "raw_detections": self.raw_detections,
            "kept_detections": self.kept_detections,
            "events_confirmed": self.events_confirmed,
            "events_ended": self.events_ended,
            "incident_ids": list(self.incident_ids),
            "last_video_time_s": self.last_video_time_s,
            "stopped_early": self.stopped_early,
        }


class IncidentSink(Protocol):
    def on_confirmed(self, ctx: SourceContext, event: TrackEvent, risk: RiskAssessment,
                     recommendations: list[ResponseRecommendation]) -> int | None: ...

    def on_updated(self, ctx: SourceContext, event: TrackEvent, risk: RiskAssessment, incident_id: int) -> None: ...

    def on_ended(self, ctx: SourceContext, event: TrackEvent, risk: RiskAssessment, incident_id: int) -> None: ...


class InMemoryIncidentSink:
    """Keeps incidents in a list. Used by tests and ``run_demo.py --no-db``."""

    def __init__(self) -> None:
        self.incidents: dict[int, dict] = {}
        self._next = 1
        self._lock = threading.Lock()

    def on_confirmed(self, ctx, event, risk, recommendations):
        with self._lock:
            iid = self._next
            self._next += 1
            self.incidents[iid] = {
                "id": iid,
                "hazard_type": event.hazard_type.value,
                "severity": risk.severity.value,
                "risk_score": risk.score,
                "camera_id": ctx.camera_id,
                "source": ctx.source_label,
                "is_demo": event.is_demo,
                "first_frame": event.first_frame,
                "first_time_s": event.first_time_s,
                "frames_observed": event.total_hits,
                "peak_confidence": event.max_confidence,
                "recommendations": [(r.department, r.action, r.priority.value) for r in recommendations],
                "ended": False,
            }
            return iid

    def on_updated(self, ctx, event, risk, incident_id):
        inc = self.incidents[incident_id]
        inc["frames_observed"] = event.total_hits
        inc["peak_confidence"] = max(inc["peak_confidence"], event.max_confidence)
        if risk.score > inc["risk_score"]:
            escalated = Severity(inc["severity"]).rank < risk.severity.rank
            inc["risk_score"], inc["severity"] = risk.score, risk.severity.value
            if escalated:  # mirror the DB sink: new recommendations for the higher severity
                recs = ResponseRecommendationAgent().recommend(event.hazard_type, risk.severity)
                inc["recommendations"] = [(r.department, r.action, r.priority.value) for r in recs]

    def on_ended(self, ctx, event, risk, incident_id):
        self.on_updated(ctx, event, risk, incident_id)
        self.incidents[incident_id]["ended"] = True
        self.incidents[incident_id]["last_time_s"] = event.last_time_s


def annotate_frame(frame: np.ndarray, detections: list[Detection], is_demo: bool) -> np.ndarray:
    """Draw boxes, labels and (if applicable) a DEMO MODE banner on a copy of the frame."""
    out = frame.copy()
    for d in detections:
        x1, y1, x2, y2 = (int(v) for v in d.bbox)
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 80, 255), 2)
        cv2.putText(out, f"{d.hazard_type.value} {d.confidence:.2f}", (x1, max(14, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 80, 255), 1, cv2.LINE_AA)
    if is_demo:
        cv2.rectangle(out, (0, 0), (out.shape[1], 24), (20, 20, 20), -1)
        cv2.putText(out, "DEMO MODE - colour heuristic, not a validated detector", (8, 17),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 215, 255), 1, cv2.LINE_AA)
    return out


ProgressCallback = Callable[[PipelineStats, list[Detection], int, float], None]
SnapshotCallback = Callable[[np.ndarray], None]


class HazardPipeline:
    """Orchestrates the agents for one video source."""

    def __init__(self, detector: BaseDetector, risk_agent: RiskAssessmentAgent,
                 response_agent: ResponseRecommendationAgent, config: PipelineConfig):
        self.detector = detector
        self.risk_agent = risk_agent
        self.response_agent = response_agent
        self.config = config

    def run(self, source: VideoSource, sink: IncidentSink, ctx: SourceContext, *,
            stop_event: threading.Event | None = None,
            on_progress: ProgressCallback | None = None,
            on_snapshot: SnapshotCallback | None = None,
            snapshot_every: int = 3) -> PipelineStats:
        cfg = self.config
        validator = TemporalValidator(cfg.window_size, cfg.min_hits, cfg.end_after_missed, cfg.max_samples)
        stats = PipelineStats()
        track_incident: dict[int, int] = {}
        track_last_hits: dict[int, int] = {}
        supported = self.detector.supported_hazards
        ctx.is_demo_detector = self.detector.is_demo

        for frame_index, time_s, frame in source.frames(cfg.frame_stride, cfg.max_frames):
            if stop_event is not None and stop_event.is_set():
                stats.stopped_early = True
                break
            pre = preprocess(frame, cfg.max_frame_width)
            raw = scale_detections(self.detector.detect(pre.image), pre.scale)
            kept = filter_detections(raw, cfg.thresholds, cfg.default_threshold, supported)
            stats.frames_read = frame_index + 1
            stats.frames_processed += 1
            stats.raw_detections += len(raw)
            stats.kept_detections += len(kept)
            stats.last_video_time_s = time_s

            for event in validator.update(frame_index, time_s, kept):
                self._handle(event, sink, ctx, stats, track_incident, track_last_hits)

            if on_progress is not None:
                on_progress(stats, kept, frame_index, time_s)
            if on_snapshot is not None and (stats.frames_processed % snapshot_every == 0 or kept):
                on_snapshot(annotate_frame(frame, kept, self.detector.is_demo))

        for event in validator.flush():
            self._handle(event, sink, ctx, stats, track_incident, track_last_hits)
        stats.finished_at = datetime.now(timezone.utc)
        return stats

    def _handle(self, event: TrackEvent, sink: IncidentSink, ctx: SourceContext, stats: PipelineStats,
                track_incident: dict[int, int], track_last_hits: dict[int, int]) -> None:
        risk = self.risk_agent.assess(event.hazard_type, event.mean_confidence, event.total_hits)
        if event.kind == EventKind.CONFIRMED:
            recs = self.response_agent.recommend(event.hazard_type, risk.severity)
            incident_id = sink.on_confirmed(ctx, event, risk, recs)
            stats.events_confirmed += 1
            if incident_id is not None:
                track_incident[event.track_id] = incident_id
                track_last_hits[event.track_id] = event.total_hits
                if incident_id not in stats.incident_ids:
                    stats.incident_ids.append(incident_id)
            return

        incident_id = track_incident.get(event.track_id)
        if incident_id is None:
            return
        if event.kind == EventKind.UPDATED:
            if event.total_hits - track_last_hits[event.track_id] >= self.config.update_every_n_hits:
                sink.on_updated(ctx, event, risk, incident_id)
                track_last_hits[event.track_id] = event.total_hits
        elif event.kind == EventKind.ENDED:
            sink.on_ended(ctx, event, risk, incident_id)
            stats.events_ended += 1
            track_incident.pop(event.track_id, None)
            track_last_hits.pop(event.track_id, None)
