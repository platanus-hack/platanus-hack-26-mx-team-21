"""Llamativo anomaly render + JSON/GeoJSON.

- Floor mask drawn as a SEGMENTED GRID (cuadrícula) clipped to the road surface.
- THICK bounding boxes drawn ON TOP of the grid (potholes/anomalies from the cascade).
- Top banner: Qwen description focused on URBAN ANOMALIES (vendedores ambulantes,
  salubridad, falta de señalización, basura, obstrucciones) — stable + complemented.
- Exports anomalies.json and anomalies.geojson (one feature per event; geometry filled
  from --lat/--lon or a per-frame GPS track when available, else null).

Reuses detections.json + summary.json (detector boxes + 32B pothole verdicts).
Output: outputs/final/<name>/final_anomalias.mp4 + anomalies.json + anomalies.geojson
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import textwrap
import time
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageDraw, ImageFont
from transformers import (AutoProcessor, Qwen2_5_VLForConditionalGeneration,
                          SegformerForSemanticSegmentation, SegformerImageProcessor)

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"
DATASET = ROOT / "data" / "videos" / "app_dataset"
OUT = ROOT / "outputs" / "final"
ROAD_CLASS = 0

DESCRIBE = (
    "Eres un inspector urbano. Describe en UNA o DOS frases, en español, las ANOMALÍAS "
    "visibles en esta escena de calle, indicando EXPLÍCITAMENTE si hay: "
    "(1) BASURA o residuos en la vía; "
    "(2) problemas de ALUMBRADO público o luminarias/semáforos (dañados, faltantes o "
    "encendidos de día); "
    "(3) VENDEDORES AMBULANTES o comercio informal que obstruye la vía. "
    "Menciona también pavimento dañado, obstrucciones o falta de señalización si aplica. "
    "Solo menciona lo que realmente se ve. Responde solo con la descripción."
)
COMPLEMENT = (
    "Descripción previa de anomalías: «{prev}». La escena cambió. Da UNA o DOS frases en "
    "español que ACTUALICEN la lista de anomalías incorporando lo nuevo y conservando lo "
    "relevante, indicando explícitamente BASURA, ALUMBRADO/luminarias y VENDEDORES "
    "AMBULANTES cuando aparezcan, además de pavimento dañado u obstrucciones. "
    "Responde solo con la descripción."
)
STOP = set("de la el en y a los las un una con que se del por su al lo como mas más o sin sobre "
           "unos unas mientras donde bajo para es son está están hay este esta muestra aún".split())


def words(t):
    return {w for w in re.findall(r"[a-záéíóúñ]+", t.lower()) if len(w) > 3 and w not in STOP}


def jaccard(a, b):
    wa, wb = words(a), words(b)
    return len(wa & wb) / len(wa | wb) if (wa | wb) else 1.0


M = {}


def font(sz):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


def load(vlm_dir):
    sd = MODELS / "segformer-cityscapes"
    M["seg_proc"] = SegformerImageProcessor.from_pretrained(sd, local_files_only=True)
    M["seg"] = SegformerForSemanticSegmentation.from_pretrained(sd, local_files_only=True).to("cuda").eval()
    t = time.perf_counter()
    M["vp"] = AutoProcessor.from_pretrained(vlm_dir, local_files_only=True)
    M["vlm"] = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        vlm_dir, local_files_only=True, torch_dtype=torch.bfloat16,
        attn_implementation="sdpa", device_map="cuda").eval()
    M["font"] = font(28)
    M["bfont"] = font(22)
    print(f"models loaded ({Path(vlm_dir).name}, {time.perf_counter()-t:.0f}s)", flush=True)


@torch.inference_mode()
def floor(image):
    inp = M["seg_proc"](images=image, return_tensors="pt").to("cuda")
    up = F.interpolate(M["seg"](**inp).logits, size=image.size[::-1], mode="bilinear", align_corners=False)
    return up.argmax(1)[0].cpu().numpy() == ROAD_CLASS


@torch.inference_mode()
def ask(img_bgr, prompt):
    image = Image.fromarray(img_bgr[:, :, ::-1])
    if max(image.size) > 768:
        s = 768 / max(image.size); image = image.resize((int(image.width * s), int(image.height * s)))
    msgs = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": prompt}]}]
    txt = M["vp"].apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    inp = M["vp"](text=[txt], images=[image], return_tensors="pt").to("cuda")
    out = M["vlm"].generate(**inp, max_new_tokens=110, do_sample=False)
    return " ".join(M["vp"].decode(out[0][inp.input_ids.shape[1]:], skip_special_tokens=True).split()).strip("«».")[:220]


def draw_grid(canvas, mask, n_long=11, n_trans=9, color=(210, 210, 210), alpha=0.28):
    """Subtle PERSPECTIVE grid converging to the road vanishing point, clipped to floor.
    Keeps attention on the detections, not the road."""
    h, w = mask.shape
    ys, xs = np.where(mask)
    if ys.size < 80:
        return
    top = int(np.percentile(ys, 2)); bottom = int(np.percentile(ys, 99))
    if bottom - top < 20:
        return
    band = ys < top + max(4, int((bottom - top) * 0.06))
    vx = int(np.mean(xs[band])) if band.any() else w // 2
    vy = top
    bb = ys > bottom - max(4, int((bottom - top) * 0.08))
    if bb.any():
        bl = int(np.percentile(xs[bb], 3)); br = int(np.percentile(xs[bb], 97))
    else:
        bl, br = int(w * 0.15), int(w * 0.85)
    layer = np.zeros((h, w), np.uint8)
    for t in np.linspace(0, 1, n_long):
        cv2.line(layer, (vx, vy), (int(bl + t * (br - bl)), bottom), 255, 1, cv2.LINE_AA)
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
    ap.add_argument("--vlm", default=str(MODELS / "Qwen2.5-VL-32B-Instruct"))
    ap.add_argument("--fps", type=float, default=5.0)
    ap.add_argument("--proc-width", type=int, default=1280)
    ap.add_argument("--grid", type=int, default=64)
    ap.add_argument("--box-thick", type=int, default=6)
    ap.add_argument("--check-every", type=int, default=15)
    ap.add_argument("--sim-thresh", type=float, default=0.45)
    ap.add_argument("--lat", type=float, default=None)
    ap.add_argument("--lon", type=float, default=None)
    ap.add_argument("--gps-jsonl", type=str, default=None, help="optional per-frame {frame,lat,lon}")
    args = ap.parse_args()
    if not torch.cuda.is_available():
        raise SystemExit("CUDA unavailable")
    dest = OUT / args.name
    dets = {r["frame"]: r["boxes"] for r in json.loads((dest / "detections.json").read_text())}
    verds = {k: (v.get("verdict") or {}) for k, v in
             json.loads((dest / "summary.json").read_text())["events_detail"].items()}
    gps = {}
    if args.gps_jsonl and Path(args.gps_jsonl).exists():
        for ln in Path(args.gps_jsonl).read_text().splitlines():
            g = json.loads(ln); gps[g["frame"]] = (g["lat"], g["lon"])
    load(Path(args.vlm))

    fdir, rdir = dest / "_af", dest / "_ar"
    fdir.mkdir(parents=True, exist_ok=True); rdir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-nostdin", "-i", str(DATASET / f"{args.name}.mp4"),
                    "-vf", f"fps={args.fps}", "-q:v", "2", str(fdir / "f-%05d.jpg")],
                   check=True, capture_output=True)
    frames = sorted(fdir.glob("f-*.jpg"))

    # per-event frame range (for time + geojson)
    ev_frames = {}
    for fi, boxes in dets.items():
        for b in boxes:
            if b.get("on_floor") and b.get("event"):
                ev_frames.setdefault(b["event"], []).append(fi)

    current = ""
    captions = []
    for fi, fp in enumerate(frames):
        img = cv2.imread(str(fp))
        if img.shape[1] > args.proc_width:
            s = args.proc_width / img.shape[1]
            img = cv2.resize(img, (args.proc_width, int(img.shape[0] * s)))
        mask = floor(Image.fromarray(img[:, :, ::-1]))
        canvas = img.copy()
        draw_grid(canvas, mask)                                  # 1) perspective grid on floor
        for d in dets.get(fi, []):                               # 2) THICK boxes over grid
            x1, y1, x2, y2 = (int(v) for v in d["box"])
            if not d["on_floor"]:
                cv2.rectangle(canvas, (x1, y1), (x2, y2), (130, 130, 130), 2); continue
            v = verds.get(d["event"], {})
            color = (40, 220, 70) if v.get("is_pothole") else (0, 150, 255)
            cv2.rectangle(canvas, (x1, y1), (x2, y2), color, args.box_thick)
            lab = f"{v.get('label','?')}: {str(v.get('what',''))[:22]}"
            cv2.rectangle(canvas, (x1, y1 - 26), (x1 + 12 * len(lab), y1), color, -1)
            cv2.putText(canvas, lab, (x1 + 3, y1 - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2, cv2.LINE_AA)
        if fi % args.check_every == 0:                           # 3) anomaly caption (evolves every interval)
            t = time.perf_counter()
            if not current:
                current = ask(img, DESCRIBE)
                tag = "init"
            else:
                # always COMPLEMENT -> the banner evolves dynamically but stays coherent
                current = ask(img, COMPLEMENT.format(prev=current))
                tag = "evolve"
            print(f"  f{fi} [{tag}] {current} ({time.perf_counter()-t:.0f}s)", flush=True)
            captions.append({"frame": fi, "time_s": round(fi / args.fps, 2), "anomalies_desc": current})
        cv2.imwrite(str(rdir / fp.name), banner(canvas, current))

    final = dest / "final_anomalias.mp4"
    subprocess.run(["ffmpeg", "-y", "-nostdin", "-framerate", str(args.fps), "-i", str(rdir / "f-%05d.jpg"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(final)], check=True, capture_output=True)

    # ---- anomalies.json + anomalies.geojson (one feature per event) ----
    feats, rows = [], []
    for eid, fis in sorted(ev_frames.items()):
        v = verds.get(eid, {})
        first = min(fis); ts = round(first / args.fps, 2)
        lat, lon = gps.get(first, (args.lat, args.lon))
        rec = {"event_id": eid, "label": v.get("label"), "what": v.get("what"),
               "is_pothole": v.get("is_pothole"), "first_frame": first, "time_s": ts,
               "n_frames": len(fis), "lat": lat, "lon": lon}
        rows.append(rec)
        feats.append({"type": "Feature",
                      "geometry": ({"type": "Point", "coordinates": [lon, lat]} if lat is not None else None),
                      "properties": {k: rec[k] for k in rec if k not in ("lat", "lon")}})
    (dest / "anomalies.json").write_text(json.dumps(
        {"video": args.name, "fps": args.fps, "events": rows, "captions": captions}, indent=2, ensure_ascii=False))
    (dest / "anomalies.geojson").write_text(json.dumps(
        {"type": "FeatureCollection", "features": feats}, indent=2, ensure_ascii=False))

    for dd in (fdir, rdir):
        for f in dd.glob("*.jpg"):
            f.unlink()
        dd.rmdir()
    geo = sum(1 for r in rows if r["lat"] is not None)
    print(json.dumps({"final": str(final), "events": len(rows), "georeferenced": geo}), flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
