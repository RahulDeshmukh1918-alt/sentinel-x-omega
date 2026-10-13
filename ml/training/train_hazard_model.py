"""Fine-tune a YOLO model on the hazard dataset (requires requirements-ml.txt).

    python ml/training/train_hazard_model.py --base yolov8n.pt --epochs 50
    # then: copy runs/.../weights/best.pt to ml/models/hazard_yolo.pt and set DETECTOR_MODE=yolo

Notes
* The base checkpoint is downloaded by Ultralytics on first use *here* (training),
  never by the web application.
* "accident" and "fall" are scene-level events; bounding-box detection of them
  needs carefully labelled data and will be less reliable than fire/smoke.
  A dedicated fall-detection approach (pose estimation + temporal rules) is a
  documented future enhancement.
"""
from __future__ import annotations

import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=HERE / "hazard_dataset.yaml")
    ap.add_argument("--base", default="yolov8n.pt", help="pretrained checkpoint to fine-tune")
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--device", default="cpu", help="'cpu', '0' for the first CUDA GPU, ...")
    ap.add_argument("--project", type=Path, default=HERE.parent / "runs")
    args = ap.parse_args()

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise SystemExit("ultralytics is not installed: pip install -r requirements-ml.txt") from exc

    model = YOLO(args.base)
    model.train(data=str(args.data), epochs=args.epochs, imgsz=args.imgsz, batch=args.batch, device=args.device,
                project=str(args.project), name="hazard", exist_ok=False)
    print("Training finished. Evaluate with ml/evaluation/evaluate_model.py before using the weights.")


if __name__ == "__main__":
    main()
