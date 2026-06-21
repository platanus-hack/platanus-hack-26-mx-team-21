"""Run the pothole detector on KartaView street-view sequences and geo-reference
every detection using the per-frame GPS track.

Input: data/videos/streetview/<name>/{frames/, gps_track.jsonl}
Output: outputs/demo/streetview/<name>/{annotated.mp4, detections.geojson, results.json}
and a combined outputs/demo/streetview/all_streetview.geojson over all sequences.

Frames map 1:1 to gps_track by frame number, so each detection inherits the exact
lat/lon/heading of its frame -> real map points.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_available_models as ram  # noqa: E402
from run_pothole import PotholeExpert  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SV = ROOT / "data" / "videos" / "streetview"
OUT = ROOT / "outputs" / "demo" / "streetview"


def process(expert: PotholeExpert, name: str, fps: float) -> list[dict]:
    src = SV / name
    frames = sorted((src / "frames").glob("frame-*.jpg"))
    track = {}
    for line in (src / "gps_track.jsonl").read_text().splitlines():
        t = json.loads(line)
        track[t["frame"]] = t
    dest = OUT / name
    ann = dest / "annotated"
    ann.mkdir(parents=True, exist_ok=True)
    rows = []
    for idx, fp in enumerate(frames, 1):
        image = Image.open(fp).convert("RGB")
        preds = expert.detect(image)
        ram.annotate(image, preds).save(ann / fp.name, quality=88)
        g = track.get(idx, {})
        for p in preds:
            rows.append({
                "source_type": "streetview", "sequence": name, "frame": idx,
                "image_id": g.get("image_id"), "model": p["model_name"],
                "anomaly": p["requested_class"], "score": round(float(p["score"]), 4),
                "bbox_xyxy": [round(x, 1) for x in p["bbox_xyxy"]],
                "heading": g.get("heading"), "shot_date": g.get("shot_date"),
                "lat": g.get("lat"), "lon": g.get("lon"),
            })
    subprocess.run(["ffmpeg", "-y", "-nostdin", "-framerate", str(fps), "-i",
                    str(ann / "frame-%05d.jpg"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(dest / "annotated.mp4")], check=True, capture_output=True)
    (dest / "results.json").write_text(json.dumps(rows, indent=2))
    (dest / "detections.geojson").write_text(json.dumps(geojson(rows), indent=2))
    print(f"{name}: {len(frames)} frames, {len(rows)} pothole detections")
    return rows


def geojson(rows: list[dict]) -> dict:
    feats = []
    for i, r in enumerate(rows):
        geom = ({"type": "Point", "coordinates": [r["lon"], r["lat"]]}
                if r.get("lat") is not None else None)
        feats.append({"type": "Feature", "id": i, "geometry": geom,
                      "properties": {k: v for k, v in r.items() if k not in ("lat", "lon")}})
    return {"type": "FeatureCollection", "features": feats}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--names", nargs="+", required=True)
    ap.add_argument("--conf", type=float, default=0.30)
    ap.add_argument("--fps", type=float, default=4.0)
    args = ap.parse_args()
    if not torch.cuda.is_available():
        raise SystemExit("CUDA unavailable")
    expert = PotholeExpert(args.conf)
    OUT.mkdir(parents=True, exist_ok=True)
    allrows = []
    for name in args.names:
        if (SV / name / "gps_track.jsonl").exists():
            allrows += process(expert, name, args.fps)
    (OUT / "all_streetview.geojson").write_text(json.dumps(geojson(allrows), indent=2))
    geo = sum(1 for r in allrows if r.get("lat") is not None)
    print(json.dumps({"sequences": len(args.names), "total_pothole_detections": len(allrows),
                      "georeferenced": geo,
                      "combined_geojson": str(OUT / "all_streetview.geojson")}, indent=2))


if __name__ == "__main__":
    main()
