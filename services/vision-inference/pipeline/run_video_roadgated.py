"""YOLO26-seg pothole segmentation + floor(road) detection gating on a generic video.

Extracts frames at --fps, computes a Segformer (Cityscapes) road/floor mask per frame,
runs our YOLO26-seg pothole model, and keeps a detection only if >= --road-frac of its
box overlaps floor pixels. Renders the floor tinted pink (kept = red box, dropped = grey),
builds an annotated mp4 + a best-parts montage of kept-detection frames.

Output: outputs/video_analysis/<name>/{annotated-floor.mp4, best-parts.mp4, results.json}
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor
from ultralytics import YOLO

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_available_models as ram  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "video_analysis"
YOLO_MODEL = ROOT / "models" / "pablo_v1" / "pablo_v1.pt"   # YOLO26-seg weights (legacy filename)
SEG_MODEL = ROOT / "models" / "segformer-cityscapes"
ROAD_CLASS = 0


class RoadSeg:
    def __init__(self):
        self.proc = SegformerImageProcessor.from_pretrained(SEG_MODEL, local_files_only=True)
        self.model = SegformerForSemanticSegmentation.from_pretrained(
            SEG_MODEL, local_files_only=True).to("cuda").eval()

    @torch.inference_mode()
    def mask(self, image: Image.Image) -> np.ndarray:
        inp = self.proc(images=image, return_tensors="pt").to("cuda")
        up = F.interpolate(self.model(**inp).logits, size=image.size[::-1],
                           mode="bilinear", align_corners=False)
        return up.argmax(1)[0].cpu().numpy() == ROAD_CLASS


def overlap(box, road, frac):
    x1, y1, x2, y2 = (int(max(0, v)) for v in box)
    x2 = min(x2, road.shape[1]); y2 = min(y2, road.shape[0])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    return float(road[y1:y2, x1:x2].mean())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--name", default=None)
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--max-frames", type=int, default=240)
    ap.add_argument("--conf", type=float, default=0.40)
    ap.add_argument("--road-frac", type=float, default=0.5)
    ap.add_argument("--best-thr", type=float, default=0.45)
    args = ap.parse_args()
    if not torch.cuda.is_available():
        raise SystemExit("CUDA unavailable")
    name = args.name or args.video.stem
    dest = OUT / name
    fdir = dest / "frames"
    adir = dest / "annotated"
    bdir = dest / "best_frames"
    for d in (fdir, adir, bdir):
        d.mkdir(parents=True, exist_ok=True)

    cmd = ["ffmpeg", "-y", "-nostdin", "-i", str(args.video), "-vf", f"fps={args.fps}"]
    if args.max_frames > 0:
        cmd += ["-frames:v", str(args.max_frames)]
    cmd += ["-q:v", "2", str(fdir / "frame-%05d.jpg")]
    subprocess.run(cmd, check=True, capture_output=True)
    frames = sorted(fdir.glob("frame-*.jpg"))

    yolo = YOLO(str(YOLO_MODEL))
    seg = RoadSeg()
    pothole_ids = {i for i, n in yolo.names.items() if n.lower() == "pothole"} or set(yolo.names)
    print(f"{name}: {len(frames)} frames, conf={args.conf}, road_frac={args.road_frac}", flush=True)

    per_frame, kept_total, dropped_total, best = [], 0, 0, []
    for idx, fp in enumerate(frames, 1):
        image = Image.open(fp).convert("RGB")
        road = seg.mask(image)
        res = yolo.predict(source=str(fp), conf=args.conf, device=0, verbose=False)[0]
        canvas = np.array(image)[:, :, ::-1].copy()
        canvas[road] = (0.7 * canvas[road] + 0.3 * np.array([180, 105, 255])).astype(np.uint8)
        kept_here, top = 0, 0.0
        if res.boxes is not None:
            for b in res.boxes:
                if int(b.cls[0]) not in pothole_ids:
                    continue
                box = ram.box_record(b.xyxy[0].tolist(), image.width, image.height)
                score = float(b.conf[0]); ov = overlap(box, road, args.road_frac)
                kept = ov >= args.road_frac
                x1, y1, x2, y2 = (int(v) for v in box)
                color = (0, 0, 255) if kept else (130, 130, 130)
                cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2 if kept else 1)
                cv2.putText(canvas, f"pothole {score:.2f}" if kept else f"off-floor {ov:.0%}",
                            (x1, max(0, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
                if kept:
                    kept_here += 1; kept_total += 1; top = max(top, score)
                else:
                    dropped_total += 1
        cv2.imwrite(str(adir / fp.name), canvas)
        if top >= args.best_thr:
            cv2.imwrite(str(bdir / fp.name), canvas); best.append(fp.name)
        per_frame.append({"frame": idx, "time_s": round(idx / args.fps, 2),
                          "potholes_on_floor": kept_here, "max_score": round(top, 3)})

    subprocess.run(["ffmpeg", "-y", "-nostdin", "-framerate", str(args.fps), "-i",
                    str(adir / "frame-%05d.jpg"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(dest / "annotated-floor.mp4")], check=True, capture_output=True)
    if best:
        lst = bdir / "list.txt"
        lst.write_text("".join(f"file '{n}'\nduration 0.6\n" for n in best))
        subprocess.run(["ffmpeg", "-y", "-nostdin", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-vsync", "vfr", "-pix_fmt", "yuv420p", "-c:v", "libx264",
                        str(dest / "best-parts.mp4")], check=True, capture_output=True)
    summary = {"video": str(args.video), "frames": len(frames), "fps": args.fps,
               "potholes_on_floor_kept": kept_total, "off_floor_dropped": dropped_total,
               "frames_with_floor_pothole": sum(1 for f in per_frame if f["potholes_on_floor"] > 0),
               "best_frames": len(best), "per_frame": per_frame}
    (dest / "results.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "per_frame"}, indent=2))


if __name__ == "__main__":
    main()
