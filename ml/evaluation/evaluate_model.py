"""Evaluate trained weights on the held-out split and record the *measured* metrics.

    python ml/evaluation/evaluate_model.py --weights ml/models/hazard_yolo.pt --split test

Writes ml/evaluation/results/<timestamp>.json with precision, recall, mAP50 and
mAP50-95 per class as reported by Ultralytics. Quote only numbers produced by this
script (with the dataset and split they were measured on) in reports.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", type=Path, required=True)
    ap.add_argument("--data", type=Path, default=HERE.parent / "training" / "hazard_dataset.yaml")
    ap.add_argument("--split", default="test", choices=["val", "test"])
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()
    if not args.weights.is_file():
        raise SystemExit(f"weights not found: {args.weights}")
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise SystemExit("ultralytics is not installed: pip install -r requirements-ml.txt") from exc

    model = YOLO(str(args.weights))
    metrics = model.val(data=str(args.data), split=args.split, device=args.device)
    names = model.names
    box = metrics.box
    result = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "weights": args.weights.name,
        "dataset": str(args.data),
        "split": args.split,
        "overall": {"precision": float(box.mp), "recall": float(box.mr), "mAP50": float(box.map50),
                    "mAP50_95": float(box.map)},
        "per_class_mAP50_95": {names[int(i)]: float(v) for i, v in zip(box.ap_class_index, box.maps[box.ap_class_index], strict=False)},
        "speed_ms_per_image": {k: float(v) for k, v in metrics.speed.items()},
    }
    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result["overall"], indent=2))
    print(f"saved {out}")


if __name__ == "__main__":
    main()
