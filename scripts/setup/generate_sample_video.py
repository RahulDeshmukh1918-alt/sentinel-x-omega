"""Generate a SYNTHETIC test video for the demo detector.

The clip is computer-generated (no real fire): a dark scene with moving grey
"traffic" blocks, a single-frame orange flash at ~1 s (should be rejected by
temporal validation), and a flickering orange "fire-like" blob from ~3 s to ~8 s
(should become ONE incident).

    python scripts/setup/generate_sample_video.py            # -> data/sample_videos/synthetic_fire_demo.mp4
    python scripts/setup/generate_sample_video.py --out x.mp4 --seconds 6
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def generate(out_path: Path, seconds: float = 12.0, fps: int = 25, size=(640, 360),
             fire_start: float = 3.0, fire_end: float = 8.0, flash_at: float | None = 1.0, seed: int = 7) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    w, h = size
    fourcc = cv2.VideoWriter_fourcc(*("mp4v" if out_path.suffix.lower() == ".mp4" else "MJPG"))
    writer = cv2.VideoWriter(str(out_path), fourcc, fps, (w, h))
    if not writer.isOpened():
        raise RuntimeError(f"OpenCV could not open a video writer for {out_path}")
    rng = np.random.default_rng(seed)
    total = int(seconds * fps)
    flash_frame = int(flash_at * fps) if flash_at is not None else -1
    try:
        for i in range(total):
            t = i / fps
            frame = np.full((h, w, 3), 38, dtype=np.uint8)
            cv2.rectangle(frame, (0, int(h * 0.65)), (w, h), (55, 55, 55), -1)  # "road"
            for lane, speed in ((0.72, 90), (0.85, -120)):
                x = int((t * speed) % (w + 120)) - 60
                if speed < 0:
                    x = w - x
                cv2.rectangle(frame, (x, int(h * lane)), (x + 60, int(h * lane) + 22), (120, 120, 120), -1)
            if i == flash_frame:
                cv2.circle(frame, (100, 80), 30, (0, 140, 255), -1)
            if fire_start <= t < fire_end:
                flicker = 1.0 + 0.15 * math.sin(t * 17) + 0.05 * rng.standard_normal()
                cx, cy, r = int(w * 0.62), int(h * 0.45), int(34 * flicker)
                cv2.ellipse(frame, (cx, cy), (r, int(r * 1.5)), 0, 0, 360, (0, 90, 255), -1)
                cv2.ellipse(frame, (cx, cy + 8), (int(r * 0.55), int(r * 0.9)), 0, 0, 360, (0, 200, 255), -1)
            noise = rng.integers(0, 6, size=frame.shape, dtype=np.uint8)
            writer.write(cv2.add(frame, noise))
    finally:
        writer.release()
    return out_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "sample_videos" / "synthetic_fire_demo.mp4")
    ap.add_argument("--seconds", type=float, default=12.0)
    args = ap.parse_args(argv)
    path = generate(args.out, seconds=args.seconds, fire_end=min(8.0, args.seconds - 1))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
