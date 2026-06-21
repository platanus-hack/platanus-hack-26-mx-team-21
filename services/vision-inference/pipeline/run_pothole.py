"""Pothole-only detector using the single best model from the MoE test:
rezzzq YOLOv12 trained on RDD2022 (multi-class; we keep only the D40=pothole class).

Chosen because in the MoE test it gave 0 pothole false positives on crack-only
negatives and the highest-confidence true detections.

Modes:
  --image  PATH   one image -> outputs/pothole/images/<stem>/
  --video  PATH   sample frames, detect, rebuild annotated video, and cut a
                  "best parts" montage of frames containing potholes.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
from PIL import Image
from ultralytics import YOLO

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_available_models as ram  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"
OUTPUTS = ROOT / "outputs"
BEST_MODEL = MODELS / "rezzzq--yolo12s-road-damage-rdd2022" / "yolo12s_RDD2022_best.pt"
POTHOLE_CLASS = "D40"


class PotholeExpert:
    def __init__(self, conf: float, model_path: Path | None = None, model_name: str = "yolo12_rdd2022_pothole"):
        self.model = YOLO(str(model_path or BEST_MODEL))
        self.names = self.model.names
        self.conf = conf
        self.model_name = model_name
        # classes that count as "pothole": explicit pothole/D40, else a single-class model -> class 0
        self.pothole_ids = {i for i, n in self.names.items() if n.lower() == "pothole" or n.upper() == "D40"}
        if not self.pothole_ids and len(self.names) == 1:
            self.pothole_ids = set(self.names)

    def detect(self, image: Image.Image) -> list[dict[str, Any]]:
        res = self.model.predict(source=np.asarray(image), conf=self.conf, device=0, verbose=False)[0]
        preds = []
        for b in res.boxes:
            cid = int(b.cls[0])
            if cid not in self.pothole_ids:
                continue
            preds.append({
                "model_name": self.model_name, "requested_class": "pothole",
                "raw_label": self.names[cid], "score": float(b.conf[0]), "score_is_calibrated": True,
                "bbox_xyxy": ram.box_record(b.xyxy[0].tolist(), image.width, image.height),
            })
        preds.sort(key=lambda p: p["score"], reverse=True)
        return preds


def process_image(expert: PotholeExpert, image_path: Path, dest: Path, sam2: bool) -> dict[str, Any]:
    dest.mkdir(parents=True, exist_ok=True)
    image = Image.open(image_path).convert("RGB")
    image.save(dest / "original.jpg", quality=95)
    preds = expert.detect(image)
    ram.annotate(image, preds).save(dest / "potholes.jpg", quality=92)
    report = {"source": str(image_path), "width": image.width, "height": image.height,
              "pothole_count": len(preds), "predictions": preds}
    if sam2 and preds:
        masks, meta = ram.run_sam2(image, preds)
        ram.annotate(image, preds, masks).save(dest / "potholes_masks.jpg", quality=92)
        report["sam2"] = meta
    ram.comparison_canvas([("Original", image), ("Potholes (YOLOv12-RDD2022)", ram.annotate(image, preds))],
                          dest / "comparison.jpg")
    (dest / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def collect_best(image_reports: list[tuple[str, dict]], best_dir: Path, top_k: int, pad: float = 0.25) -> None:
    best_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for stem, rep in image_reports:
        for i, p in enumerate(rep["predictions"]):
            rows.append((p["score"], stem, i, p["bbox_xyxy"], rep["source"]))
    rows.sort(reverse=True)
    index = []
    for rank, (score, stem, i, box, src) in enumerate(rows[:top_k]):
        im = Image.open(src).convert("RGB")
        x1, y1, x2, y2 = box
        px, py = (x2 - x1) * pad, (y2 - y1) * pad
        crop = im.crop((max(0, x1 - px), max(0, y1 - py), min(im.width, x2 + px), min(im.height, y2 + py)))
        name = f"{rank:02d}_{stem}_{score:.2f}.jpg"
        crop.save(best_dir / name, quality=95)
        index.append({"rank": rank, "stem": stem, "score": round(score, 4), "bbox_xyxy": box,
                      "crop": name, "source": src})
    (best_dir / "index.jsonl").write_text("".join(json.dumps(r) + "\n" for r in index))
    print(f"best: wrote {len(index)} pothole crops -> {best_dir}")


def process_video(expert: PotholeExpert, video: Path, dest: Path, fps: float, max_frames: int,
                  best_thr: float) -> dict[str, Any]:
    frames_dir = dest / "frames"
    annotated_dir = dest / "annotated"
    best_frames_dir = dest / "best_frames"
    for d in (frames_dir, annotated_dir, best_frames_dir):
        d.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-nostdin", "-i", str(video), "-vf", f"fps={fps}"]
    if max_frames > 0:
        cmd += ["-frames:v", str(max_frames)]
    cmd += ["-q:v", "2", str(frames_dir / "frame-%05d.jpg")]
    subprocess.run(cmd, check=True, capture_output=True)
    frames = sorted(frames_dir.glob("frame-*.jpg"))

    per_frame = []
    best_frames = []
    t0 = time.perf_counter()
    for idx, fp in enumerate(frames, 1):
        image = Image.open(fp).convert("RGB")
        preds = expert.detect(image)
        ram.annotate(image, preds).save(annotated_dir / fp.name, quality=90)
        top = preds[0]["score"] if preds else 0.0
        per_frame.append({"frame": idx, "time_s": round(idx / fps, 2), "potholes": len(preds),
                          "max_score": round(top, 4)})
        if top >= best_thr:
            ram.annotate(image, preds).save(best_frames_dir / fp.name, quality=92)
            best_frames.append(fp.name)
    elapsed = time.perf_counter() - t0

    # full annotated video
    full_mp4 = dest / "annotated-full.mp4"
    subprocess.run(["ffmpeg", "-y", "-nostdin", "-framerate", str(fps), "-i",
                    str(annotated_dir / "frame-%05d.jpg"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(full_mp4)], check=True, capture_output=True)
    # best-parts montage (only frames with a confident pothole), if any
    best_mp4 = None
    if best_frames:
        listfile = best_frames_dir / "list.txt"
        listfile.write_text("".join(f"file '{n}'\nduration 0.5\n" for n in best_frames))
        best_mp4 = dest / "best-parts.mp4"
        subprocess.run(["ffmpeg", "-y", "-nostdin", "-f", "concat", "-safe", "0", "-i", str(listfile),
                        "-vsync", "vfr", "-pix_fmt", "yuv420p", "-c:v", "libx264", str(best_mp4)],
                       check=True, capture_output=True)

    summary = {
        "source": str(video), "sampled_fps": fps, "frames_processed": len(frames),
        "frames_with_pothole": sum(1 for f in per_frame if f["potholes"] > 0),
        "best_frames(score>=%.2f)" % best_thr: len(best_frames),
        "runtime_s": round(elapsed, 1),
        "annotated_full_video": str(full_mp4),
        "best_parts_video": str(best_mp4) if best_mp4 else None,
        "per_frame": per_frame,
    }
    (dest / "results.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--image", type=Path)
    g.add_argument("--video", type=Path)
    g.add_argument("--collect-best", type=Path, metavar="IMAGES_DIR",
                   help="scan <dir>/*/results.json and build a best/ folder of top pothole crops")
    ap.add_argument("--top-k", type=int, default=20)
    ap.add_argument("--model", type=Path, help="YOLO .pt path (default: rezzzq RDD2022)")
    ap.add_argument("--model-name", default="yolo12_rdd2022_pothole")
    ap.add_argument("--output", type=Path)
    ap.add_argument("--conf", type=float, default=0.30)
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--max-frames", type=int, default=0)
    ap.add_argument("--best-thr", type=float, default=0.45)
    ap.add_argument("--no-sam2", action="store_true")
    args = ap.parse_args()
    if args.collect_best:
        reports = []
        for rj in sorted(args.collect_best.glob("*/results.json")):
            rep = json.loads(rj.read_text())
            reports.append((rj.parent.name, rep))
        collect_best(reports, OUTPUTS / "pothole" / "best", args.top_k)
        return
    if not torch.cuda.is_available():
        raise SystemExit("CUDA unavailable")
    expert = PotholeExpert(args.conf, model_path=args.model, model_name=args.model_name)
    if args.image:
        out = args.output or OUTPUTS / "pothole" / "images" / args.image.stem
        rep = process_image(expert, args.image, out, sam2=not args.no_sam2)
        print(json.dumps({"output": str(out), "pothole_count": rep["pothole_count"]}, indent=2))
    else:
        out = args.output or OUTPUTS / "pothole" / "video" / args.video.stem
        summary = process_video(expert, args.video, out, args.fps, args.max_frames, args.best_thr)
        print(json.dumps({k: v for k, v in summary.items() if k != "per_frame"}, indent=2))


if __name__ == "__main__":
    main()
