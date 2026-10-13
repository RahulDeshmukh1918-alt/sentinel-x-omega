# ML workspace

| Folder | Purpose |
|---|---|
| `training/` | Dataset definition (`hazard_dataset.yaml`) and fine-tuning script |
| `evaluation/` | Evaluation script; measured results are written to `evaluation/results/` |
| `models/` | Put trained weights here (`hazard_yolo.pt`). Weights are git-ignored |
| `datasets/` | Local datasets (git-ignored; create it yourself) |

## Status

**No hazard model has been trained or evaluated yet.** The application therefore
runs in `DEMO_MODE` (colour heuristic, fire-like regions only) or reports
`MODEL_NOT_AVAILABLE`. No precision / recall / mAP / latency figures exist for
this project until `evaluate_model.py` has been run on a labelled test split.

| Metric | Value |
|---|---|
| Precision | not measured |
| Recall | not measured |
| mAP50 | not measured |
| mAP50-95 | not measured |
| Inference latency | not measured |

## Why a stock COCO model is not enough

COCO-pretrained YOLO models know 80 everyday classes (person, car, ...). None of
them is *fire*, *smoke*, *spark*, *accident* or *fall*. The detector verifies the
loaded model's class names against `MODEL_CLASS_MAP`; if nothing maps to a
supported hazard it refuses to run instead of producing meaningless detections.

## Steps to enable real detection

1. `pip install -r requirements-ml.txt`
2. Collect and label data in YOLO format (see `training/hazard_dataset.yaml`). Public
   fire/smoke datasets exist (e.g. D-Fire); check each dataset's licence before use.
3. `python ml/training/train_hazard_model.py --epochs 50 --device 0`
4. `python ml/evaluation/evaluate_model.py --weights <best.pt> --split test`
5. Copy the weights to `ml/models/hazard_yolo.pt`, set `DETECTOR_MODE=yolo` in `.env`, restart.
6. Re-tune `CONFIDENCE_THRESHOLDS` and the temporal parameters using the validation split.
