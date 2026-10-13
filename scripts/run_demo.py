"""Run the full detection pipeline on a video from the command line.

    python scripts/run_demo.py                              # synthetic sample, writes to the database
    python scripts/run_demo.py --video path/to/clip.mp4     # your own footage
    python scripts/run_demo.py --no-db                      # in-memory only (no SQLAlchemy needed)
    python scripts/run_demo.py --webcam 0 --max-frames 600  # local webcam

Exit codes: 0 ok, 2 video/camera problem, 3 model not available.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.ai.detector import build_detector  # noqa: E402
from backend.app.ai.video_source import VideoSource, VideoSourceError  # noqa: E402
from backend.app.core.config import get_settings  # noqa: E402
from backend.app.core.enums import ModelStatus, SourceType  # noqa: E402
from backend.app.services.pipeline import (  # noqa: E402
    HazardPipeline, InMemoryIncidentSink, PipelineConfig, SourceContext,
)
from backend.app.services.response_service import ResponseRecommendationAgent  # noqa: E402
from backend.app.services.risk_service import RiskAssessmentAgent, RiskConfig  # noqa: E402

DEFAULT_VIDEO = ROOT / "data" / "sample_videos" / "synthetic_fire_demo.mp4"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--video", type=Path, help="video file (default: synthetic sample)")
    src.add_argument("--webcam", type=int, help="webcam device index")
    ap.add_argument("--no-db", action="store_true", help="keep incidents in memory instead of the database")
    ap.add_argument("--max-frames", type=int, default=None, help="stop after this many frames")
    args = ap.parse_args(argv)

    settings = get_settings()
    detector, info = build_detector(settings.detector_mode, settings.weights_path, settings.model_class_map,
                                    settings.inference_device, settings.model_min_confidence)
    print(f"Detector: {info.status.value} - {info.message}")
    if info.status == ModelStatus.DEMO_MODE:
        print("*** DEMO MODE: colour heuristic only, results are NOT validated hazard detections ***")
    if detector is None:
        return 3

    if args.webcam is not None:
        source = VideoSource(SourceType.WEBCAM, str(args.webcam))
    else:
        video = args.video or DEFAULT_VIDEO
        if args.video is None and not video.exists():
            from scripts.setup.generate_sample_video import generate

            generate(video)
            print(f"generated synthetic sample at {video}")
        source = VideoSource(SourceType.FILE, str(video))

    if args.no_db:
        sink = InMemoryIncidentSink()
    else:
        from backend.app.database import connection
        from backend.app.services.incident_workflow import DatabaseIncidentSink

        connection.init_db()
        sink = DatabaseIncidentSink(connection.get_session_factory(), settings.incident_dedup_window_seconds)

    config = PipelineConfig.from_settings(settings)
    if args.max_frames:
        config = PipelineConfig(**{**config.__dict__, "max_frames": args.max_frames})
    pipeline = HazardPipeline(detector, RiskAssessmentAgent(RiskConfig.from_settings(settings)),
                              ResponseRecommendationAgent(), config)
    try:
        with source:
            print(f"Source: {source.display_name} ({source.width}x{source.height} @ {source.fps:.1f} fps)")
            stats = pipeline.run(source, sink, SourceContext(None, source.display_name))
    except VideoSourceError as exc:
        print(f"ERROR {exc.code}: {exc.message}")
        return 2
    except KeyboardInterrupt:
        print("interrupted")
        return 130

    print(f"Frames analysed: {stats.frames_processed} (of {stats.frames_read} read, stride {config.frame_stride})")
    print(f"Detections above threshold: {stats.kept_detections}; confirmed events: {stats.events_confirmed}")
    print(f"Incidents created: {len(stats.incident_ids)} -> ids {stats.incident_ids}")
    if isinstance(sink, InMemoryIncidentSink):
        for inc in sink.incidents.values():
            print(f"  #{inc['id']} {inc['hazard_type']} {inc['severity']} risk={inc['risk_score']} "
                  f"first seen {inc['first_time_s']:.1f}s, {inc['frames_observed']} frames"
                  f"{' [DEMO]' if inc['is_demo'] else ''}")
            for dept, action, prio in inc["recommendations"]:
                print(f"     {prio} {dept}: {action}  (recommendation only - not dispatched)")
    else:
        print("Open the dashboard to review them: uvicorn backend.app.main:app  ->  http://localhost:8000")
    return 0


if __name__ == "__main__":
    sys.exit(main())
