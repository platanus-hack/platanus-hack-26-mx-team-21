"""Offline cascade -> baked final video.

For each video:
  pass 1 (detector, every sampled frame): YOLO26-seg (our fine-tune) + Segformer floor mask;
          keep on-floor pothole boxes; tint road pink; assign detections to events (dedup).
  pass 2 (VLM on EVENTS only): 32B Qwen2.5-VL verifies each event's best frame ->
          POTHOLE vs ANOMALY + caption.
  pass 3 (render): draw boxes colored by the event verdict, encode final.mp4.

Not real-time (32B is slow) but pre-rendered, so the output video plays instantly.
Models load once and process all --videos.

Output per video: outputs/final/<name>/{final.mp4, detections.json, vlm.json}
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from transformers import (AutoProcessor, Qwen2_5_VLForConditionalGeneration,
                          SegformerForSemanticSegmentation, SegformerImageProcessor)
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"
DATASET = ROOT / "data" / "videos" / "app_dataset"
OUT = ROOT / "outputs" / "final"
ROAD_CLASS = 0

VLM_PROMPT = (
    "A detector flagged a possible POTHOLE in this street photo. Reply STRICT JSON only: "
    '{"pothole_present": true/false (real pavement cavity, NOT manhole/drain/speed bump/'
    'shadow/marking), "what_it_is": short phrase}.'
)
M = {}  # loaded models


def load_all(vlm_dir: Path):
    M["yolo"] = YOLO(str(MODELS / "pablo_v1" / "pablo_v1.pt"))   # YOLO26-seg weights (legacy filename)
    M["pids"] = {i for i, n in M["yolo"].names.items() if n.lower() == "pothole"} or set(M["yolo"].names)
    sd = MODELS / "segformer-cityscapes"
    M["seg_proc"] = SegformerImageProcessor.from_pretrained(sd, local_files_only=True)
    M["seg"] = SegformerForSemanticSegmentation.from_pretrained(sd, local_files_only=True).to("cuda").eval()
    t = time.perf_counter()
    M["vlm_proc"] = AutoProcessor.from_pretrained(vlm_dir, local_files_only=True)
    M["vlm"] = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        vlm_dir, local_files_only=True, torch_dtype=torch.bfloat16,
        attn_implementation="sdpa", device_map="cuda").eval()
    print(f"models loaded (VLM {vlm_dir.name}, {time.perf_counter()-t:.0f}s)", flush=True)


@torch.inference_mode()
def road_mask(image):
    inp = M["seg_proc"](images=image, return_tensors="pt").to("cuda")
    up = F.interpolate(M["seg"](**inp).logits, size=image.size[::-1], mode="bilinear", align_corners=False)
    return up.argmax(1)[0].cpu().numpy() == ROAD_CLASS


@torch.inference_mode()
def vlm_verify(crop_bgr):
    import re
    image = Image.fromarray(crop_bgr[:, :, ::-1])
    if max(image.size) > 768:
        s = 768 / max(image.size); image = image.resize((int(image.width * s), int(image.height * s)))
    msgs = [{"role": "user", "content": [{"type": "image", "image": image},
                                         {"type": "text", "text": VLM_PROMPT}]}]
    txt = M["vlm_proc"].apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    inp = M["vlm_proc"](text=[txt], images=[image], return_tensors="pt").to("cuda")
    out = M["vlm"].generate(**inp, max_new_tokens=90, do_sample=False)
    ans = M["vlm_proc"].decode(out[0][inp.input_ids.shape[1]:], skip_special_tokens=True)
    m = re.search(r"\{.*\}", ans, re.DOTALL)
    try:
        v = json.loads(m.group(0)) if m else {}
    except Exception:  # noqa: BLE001
        v = {}
    isp = v.get("pothole_present") is True
    return {"label": "POTHOLE" if isp else "ANOMALY", "what": v.get("what_it_is", "?"), "is_pothole": isp}


def process(name, video, fps, proc_w, conf, road_frac):
    dest = OUT / name
    rdir = dest / "render"
    rdir.mkdir(parents=True, exist_ok=True)
    fdir = dest / "frames"
    fdir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-nostdin", "-i", str(video), "-vf", f"fps={fps}",
                    "-q:v", "2", str(fdir / "f-%05d.jpg")], check=True, capture_output=True)
    frames = sorted(fdir.glob("f-*.jpg"))

    # ---- pass 1: detector + floor + events ----
    events = {}
    counter = [0]

    def assign(cx, cy, diag, fi):
        for eid, e in events.items():
            if fi - e["last"] <= 40 and ((cx - e["cx"]) ** 2 + (cy - e["cy"]) ** 2) ** 0.5 <= 0.15 * diag:
                e.update(cx=cx, cy=cy, last=fi)
                if e["best_score"] < 0:  # placeholder
                    pass
                return eid
        counter[0] += 1
        eid = f"E{counter[0]}"
        events[eid] = {"cx": cx, "cy": cy, "last": fi, "best_score": -1, "best_frame": None,
                       "best_crop": None, "verdict": None}
        return eid

    per_frame = []
    for fi, fp in enumerate(frames):
        img = cv2.imread(str(fp))
        if img.shape[1] > proc_w:
            s = proc_w / img.shape[1]
            img = cv2.resize(img, (proc_w, int(img.shape[0] * s)))
        h, w = img.shape[:2]
        diag = (w * w + h * h) ** 0.5
        mask = road_mask(Image.fromarray(img[:, :, ::-1]))
        res = M["yolo"].predict(source=img[:, :, ::-1], conf=conf, device=0, verbose=False)[0]
        tinted = img.copy()
        tinted[mask] = (0.7 * tinted[mask] + 0.3 * np.array([180, 105, 255])).astype(np.uint8)
        boxes = []
        if res.boxes is not None:
            for b in res.boxes:
                if int(b.cls[0]) not in M["pids"]:
                    continue
                x1, y1, x2, y2 = (float(v) for v in b.xyxy[0].tolist())
                xi1, yi1, xi2, yi2 = max(0, int(x1)), max(0, int(y1)), min(w, int(x2)), min(h, int(y2))
                onf = float(mask[yi1:yi2, xi1:xi2].mean()) if (xi2 > xi1 and yi2 > yi1) else 0.0
                sc = float(b.conf[0])
                if onf < road_frac:
                    boxes.append({"box": [x1, y1, x2, y2], "score": sc, "event": None, "on_floor": False})
                    continue
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                eid = assign(cx, cy, diag, fi)
                e = events[eid]
                if sc > e["best_score"]:
                    e["best_score"] = sc
                    e["best_frame"] = fi
                    e["best_crop"] = img[max(0, int(y1) - 30):int(y2) + 30, max(0, int(x1) - 30):int(x2) + 30].copy()
                boxes.append({"box": [x1, y1, x2, y2], "score": sc, "event": eid, "on_floor": True})
        cv2.imwrite(str(rdir / fp.name), tinted)
        per_frame.append({"frame": fi, "boxes": boxes})
    print(f"  {name}: {len(frames)} frames, {counter[0]} events", flush=True)

    # ---- pass 2: 32B VLM on each event's best frame ----
    for eid, e in events.items():
        if e["best_crop"] is None or e["best_crop"].size == 0:
            e["verdict"] = {"label": "ANOMALY", "what": "?", "is_pothole": False}
            continue
        t = time.perf_counter()
        e["verdict"] = vlm_verify(e["best_crop"])
        print(f"    {eid} (score {e['best_score']:.2f}): {e['verdict']['label']} "
              f"- {e['verdict']['what']} ({time.perf_counter()-t:.0f}s)", flush=True)

    # ---- pass 3: render with verdicts baked in ----
    for rec in per_frame:
        fp = rdir / f"f-{rec['frame']+1:05d}.jpg"
        canvas = cv2.imread(str(fp))
        for d in rec["boxes"]:
            x1, y1, x2, y2 = (int(v) for v in d["box"])
            if not d["on_floor"]:
                cv2.rectangle(canvas, (x1, y1), (x2, y2), (130, 130, 130), 1)
                continue
            v = events[d["event"]]["verdict"] or {"label": "?", "what": "", "is_pothole": False}
            color = (40, 200, 70) if v["is_pothole"] else (0, 140, 255)
            cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 3)
            cv2.putText(canvas, f"{v['label']}: {v['what'][:26]}", (x1, max(18, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)
        cv2.imwrite(str(fp), canvas)

    final = dest / "final.mp4"
    subprocess.run(["ffmpeg", "-y", "-nostdin", "-framerate", str(fps), "-i", str(rdir / "f-%05d.jpg"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(final)], check=True, capture_output=True)
    conf_p = sum(1 for e in events.values() if e["verdict"] and e["verdict"]["is_pothole"])
    summary = {"video": name, "frames": len(frames), "events": counter[0],
               "confirmed_potholes": conf_p, "anomalies_not_pothole": counter[0] - conf_p,
               "events_detail": {k: {"best_score": round(v["best_score"], 3), "verdict": v["verdict"]}
                                 for k, v in events.items()}}
    (dest / "detections.json").write_text(json.dumps([{"frame": r["frame"],
                                                        "boxes": r["boxes"]} for r in per_frame], indent=2))
    (dest / "summary.json").write_text(json.dumps(summary, indent=2))
    # cleanup raw frames (keep render+final)
    for f in fdir.glob("*.jpg"):
        f.unlink()
    print(json.dumps({k: summary[k] for k in ("video", "frames", "events",
                                              "confirmed_potholes", "anomalies_not_pothole")}), flush=True)
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--videos", nargs="+", required=True, help="names in app_dataset (without .mp4)")
    ap.add_argument("--vlm", default=str(MODELS / "Qwen2.5-VL-32B-Instruct"))
    ap.add_argument("--fps", type=float, default=5.0)
    ap.add_argument("--proc-width", type=int, default=1280)
    ap.add_argument("--conf", type=float, default=0.40)
    ap.add_argument("--road-frac", type=float, default=0.5)
    args = ap.parse_args()
    if not torch.cuda.is_available():
        raise SystemExit("CUDA unavailable")
    load_all(Path(args.vlm))
    for name in args.videos:
        v = DATASET / f"{name}.mp4"
        if not v.exists():
            print(f"skip {name} (missing)", flush=True); continue
        process(name, v, args.fps, args.proc_width, args.conf, args.road_frac)
    print("ALL_DONE", flush=True)


if __name__ == "__main__":
    main()
