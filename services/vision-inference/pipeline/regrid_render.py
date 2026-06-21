"""Fast re-render: perspective floor grid + thick boxes + existing anomaly captions.

Reuses anomalies.json (Qwen captions, already computed), detections.json (boxes) and
summary.json (verdicts). Loads ONLY Segformer (no VLM) -> fast.

Grid follows the road into depth (vanishing-point perspective) and is SUBTLE so the
attention stays on the detections, not the road.

Output: outputs/final/<name>/final_anomalias.mp4 (overwrite)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import textwrap
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageDraw, ImageFont
from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"
DATASET = ROOT / "data" / "videos" / "app_dataset"
OUT = ROOT / "outputs" / "final"
ROAD_CLASS = 0
M = {}


def fnt(sz):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


def load():
    sd = MODELS / "segformer-cityscapes"
    M["sp"] = SegformerImageProcessor.from_pretrained(sd, local_files_only=True)
    M["seg"] = SegformerForSemanticSegmentation.from_pretrained(sd, local_files_only=True).to("cuda").eval()
    M["font"] = fnt(28)


@torch.inference_mode()
def floor(image):
    inp = M["sp"](images=image, return_tensors="pt").to("cuda")
    up = F.interpolate(M["seg"](**inp).logits, size=image.size[::-1], mode="bilinear", align_corners=False)
    return up.argmax(1)[0].cpu().numpy() == ROAD_CLASS


def persp_grid(canvas, mask, n_long=11, n_trans=9, color=(210, 210, 210), alpha=0.28):
    """Subtle perspective grid converging to the road vanishing point, clipped to floor."""
    h, w = mask.shape
    ys, xs = np.where(mask)
    if ys.size < 80:
        return
    top = int(np.percentile(ys, 2)); bottom = int(np.percentile(ys, 99))
    if bottom - top < 20:
        return
    band = ys < top + max(4, int((bottom - top) * 0.06))
    vx = int(np.mean(xs[band])) if band.any() else w // 2          # vanishing x (road center far away)
    vy = top                                                       # horizon (top of road)
    bb = ys > bottom - max(4, int((bottom - top) * 0.08))
    if bb.any():
        bl = int(np.percentile(xs[bb], 3)); br = int(np.percentile(xs[bb], 97))
    else:
        bl, br = int(w * 0.15), int(w * 0.85)
    layer = np.zeros((h, w), np.uint8)
    # longitudinal rays (converge to vanishing point -> sense of depth along the road)
    for t in np.linspace(0, 1, n_long):
        xb = int(bl + t * (br - bl))
        cv2.line(layer, (vx, vy), (xb, bottom), 255, 1, cv2.LINE_AA)
    # transversal lines, denser near the horizon (perspective foreshortening)
    for k in range(1, n_trans + 1):
        y = int(vy + (bottom - vy) * (k / n_trans) ** 1.9)
        cv2.line(layer, (0, y), (w, y), 255, 1, cv2.LINE_AA)
    grid = (layer > 0) & mask
    canvas[grid] = (canvas[grid] * (1 - alpha) + np.array(color) * alpha).astype(np.uint8)


def banner(bgr, text, color=(60, 180, 255)):
    pil = Image.fromarray(bgr[:, :, ::-1])
    lines = textwrap.wrap(text, width=62)[:3] or [""]
    bh = 14 + 30 * len(lines)
    out = Image.new("RGB", (pil.width, pil.height + bh), (22, 22, 22))
    out.paste(pil, (0, bh))
    d = ImageDraw.Draw(out)
    d.rectangle((0, 0, 12, bh), fill=color)
    y = 8
    for ln in lines:
        d.text((22, y), ln, font=M["font"], fill=(255, 255, 255)); y += 30
    return np.asarray(out)[:, :, ::-1].copy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--fps", type=float, default=5.0)
    ap.add_argument("--proc-width", type=int, default=1280)
    ap.add_argument("--grid-long", type=int, default=11)
    ap.add_argument("--grid-trans", type=int, default=9)
    ap.add_argument("--box-thick", type=int, default=6)
    ap.add_argument("--out", default="final_anomalias.mp4")
    args = ap.parse_args()
    if not torch.cuda.is_available():
        raise SystemExit("CUDA unavailable")
    dest = OUT / args.name
    dets = {r["frame"]: r["boxes"] for r in json.loads((dest / "detections.json").read_text())}
    verds = {k: (v.get("verdict") or {}) for k, v in
             json.loads((dest / "summary.json").read_text())["events_detail"].items()}
    anom = json.loads((dest / "anomalies.json").read_text())
    caps = anom.get("captions", [])
    caps.sort(key=lambda c: c["frame"])
    # event_id -> (lat, lon) from the georeferenced events
    ev_gps = {e["event_id"]: (e.get("lat"), e.get("lon")) for e in anom.get("events", [])}
    load()

    fdir, rdir = dest / "_gf", dest / "_gr"
    fdir.mkdir(parents=True, exist_ok=True); rdir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-nostdin", "-i", str(DATASET / f"{args.name}.mp4"),
                    "-vf", f"fps={args.fps}", "-q:v", "2", str(fdir / "f-%05d.jpg")],
                   check=True, capture_output=True)
    frames = sorted(fdir.glob("f-*.jpg"))

    def caption_for(fi):
        cur = caps[0]["anomalies_desc"] if caps else ""
        for c in caps:
            if c["frame"] <= fi:
                cur = c["anomalies_desc"]
            else:
                break
        return cur

    for fi, fp in enumerate(frames):
        img = cv2.imread(str(fp))
        if img.shape[1] > args.proc_width:
            s = args.proc_width / img.shape[1]
            img = cv2.resize(img, (args.proc_width, int(img.shape[0] * s)))
        mask = floor(Image.fromarray(img[:, :, ::-1]))
        canvas = img.copy()
        persp_grid(canvas, mask, args.grid_long, args.grid_trans)         # subtle perspective grid
        for d in dets.get(fi, []):                                        # thick boxes on top
            x1, y1, x2, y2 = (int(v) for v in d["box"])
            if not d["on_floor"]:
                cv2.rectangle(canvas, (x1, y1), (x2, y2), (130, 130, 130), 2); continue
            v = verds.get(d["event"], {})
            is_p = v.get("is_pothole")
            color = (40, 220, 70) if is_p else (0, 150, 255)
            cv2.rectangle(canvas, (x1, y1), (x2, y2), color, args.box_thick)
            lat, lon = ev_gps.get(d["event"], (None, None))
            if is_p and lat is not None:
                lab = f"POTHOLE  GPS [{lat:.5f}, {lon:.5f}]"
            else:
                lab = f"{v.get('label','?')}: {str(v.get('what',''))[:22]}"
            cv2.rectangle(canvas, (x1, y1 - 26), (x1 + 11 * len(lab), y1), color, -1)
            cv2.putText(canvas, lab, (x1 + 3, y1 - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 0, 0), 2, cv2.LINE_AA)
        cv2.imwrite(str(rdir / fp.name), banner(canvas, caption_for(fi)))

    final = dest / args.out
    subprocess.run(["ffmpeg", "-y", "-nostdin", "-framerate", str(args.fps), "-i", str(rdir / "f-%05d.jpg"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(final)], check=True, capture_output=True)
    for dd in (fdir, rdir):
        for f in dd.glob("*.jpg"):
            f.unlink()
        dd.rmdir()
    print(f"DONE -> {final}", flush=True)


if __name__ == "__main__":
    main()
