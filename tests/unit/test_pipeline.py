"""Pipeline orchestration on a synthetic video, without a database."""
import threading

import numpy as np

from backend.app.ai.detector import BaseDetector, DemoFireColorDetector, Detection
from backend.app.ai.video_source import VideoSource
from backend.app.core.enums import HazardType, SourceType
from backend.app.services.pipeline import (
    HazardPipeline, InMemoryIncidentSink, PipelineConfig, SourceContext, annotate_frame,
)
from backend.app.services.response_service import ResponseRecommendationAgent
from backend.app.services.risk_service import RiskAssessmentAgent, RiskConfig


def make_pipeline(settings, detector=None, **cfg):
    config = PipelineConfig.from_settings(settings)
    if cfg:
        config = PipelineConfig(**{**config.__dict__, **cfg})
    return HazardPipeline(detector or DemoFireColorDetector(), RiskAssessmentAgent(RiskConfig.from_settings(settings)),
                          ResponseRecommendationAgent(), config)


def test_synthetic_video_creates_exactly_one_incident(settings, sample_video):
    sink = InMemoryIncidentSink()
    with VideoSource(SourceType.FILE, str(sample_video)) as src:
        stats = make_pipeline(settings).run(src, sink, SourceContext(None, "synthetic"))
    assert stats.events_confirmed == 1 and stats.events_ended == 1
    assert len(sink.incidents) == 1
    inc = sink.incidents[1]
    assert inc["hazard_type"] == "FIRE" and inc["is_demo"] and inc["ended"]
    assert 2.5 <= inc["first_time_s"] <= 3.5  # blob appears at 3 s; flash at 1 s was rejected
    assert inc["recommendations"][0][0] == "Fire Brigade"
    assert stats.raw_detections > stats.events_confirmed  # many detections, one incident


def test_single_frame_flash_alone_is_not_an_incident(settings, tmp_path):
    from scripts.setup.generate_sample_video import generate

    clip = generate(tmp_path / "flash_only.mp4", seconds=3, fire_start=99, fire_end=99, flash_at=1.0)
    sink = InMemoryIncidentSink()
    with VideoSource(SourceType.FILE, str(clip)) as src:
        stats = make_pipeline(settings, frame_stride=1).run(src, sink, SourceContext(None, "flash"))
    assert stats.kept_detections >= 1
    assert sink.incidents == {}


def test_stop_event_stops_processing(settings, sample_video):
    stop = threading.Event()
    seen = []

    def progress(stats, kept, idx, t):
        seen.append(idx)
        if len(seen) == 3:
            stop.set()

    with VideoSource(SourceType.FILE, str(sample_video)) as src:
        stats = make_pipeline(settings).run(src, InMemoryIncidentSink(), SourceContext(None, "x"),
                                            stop_event=stop, on_progress=progress)
    assert stats.stopped_early and stats.frames_processed == 3


class FixedDetector(BaseDetector):
    """Returns a scripted detection per call - lets us test severity escalation deterministically."""
    name = "fixed"

    def __init__(self, confidences):
        self.confidences = list(confidences)

    @property
    def supported_hazards(self):
        return {HazardType.SMOKE}

    def detect(self, image):
        conf = self.confidences.pop(0) if self.confidences else 0.0
        return [Detection(HazardType.SMOKE, conf, (0, 0, 10, 10), "smoke")] if conf else []


def test_incident_is_updated_and_escalated_not_duplicated(settings, sample_video):
    detector = FixedDetector([0.6] * 5 + [0.95] * 30)
    sink = InMemoryIncidentSink()
    pipeline = make_pipeline(settings, detector, frame_stride=5, update_every_n_hits=5)
    with VideoSource(SourceType.FILE, str(sample_video)) as src:
        pipeline.run(src, sink, SourceContext(3, "cam"))
    assert len(sink.incidents) == 1
    inc = sink.incidents[1]
    assert inc["severity"] in ("HIGH", "CRITICAL")  # confirmed at a lower score, escalated later
    assert inc["frames_observed"] == 35


def test_snapshot_callback_receives_annotated_frames(settings, sample_video):
    frames = []
    with VideoSource(SourceType.FILE, str(sample_video)) as src:
        make_pipeline(settings).run(src, InMemoryIncidentSink(), SourceContext(None, "x"),
                                    on_snapshot=frames.append, snapshot_every=10)
    assert frames and frames[0].shape == (360, 640, 3)


def test_annotate_frame_draws_demo_banner():
    img = np.zeros((100, 400, 3), np.uint8)
    out = annotate_frame(img, [Detection(HazardType.FIRE, 0.9, (10, 30, 60, 90), "x")], is_demo=True)
    assert out.any() and not img.any()  # original untouched
