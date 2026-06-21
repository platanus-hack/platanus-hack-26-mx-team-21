"""Fetch street-level driving sequences from KartaView (open, CC BY-SA) and build a
video + per-frame GPS track for geo-referenced anomaly detection.

KartaView (ex-OpenStreetCam) is an open street-imagery database. Each sequence is a
real drive of consecutive geotagged frames. We pick the longest sequence near a given
location, order by sequence_index, download frames via the CDN, stitch a video, and
emit gps_track.jsonl (frame -> lat/lon/heading) so detections can be placed on a map.

Image URL: the nearby-photos `name` host 404s; the real URL comes from the 2.0
photo-detail endpoint field `imageProcUrl` (cdn.kartaview.org).

Usage:
  python scripts/fetch_kartaview.py --lat 19.40 --lng -99.18 --name insurgentes --max 100
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://api.openstreetcam.org"


def nearby(client: httpx.Client, lat: float, lng: float, radius: int) -> list[dict]:
    r = client.post(f"{BASE}/1.0/list/nearby-photos/",
                    data={"lat": lat, "lng": lng, "radius": radius}, timeout=60)
    r.raise_for_status()
    return r.json().get("currentPageItems", [])


def proc_url(client: httpx.Client, photo_id: str) -> str | None:
    try:
        d = client.get(f"{BASE}/2.0/photo/{photo_id}", timeout=30).json()["result"]["data"]
    except Exception:  # noqa: BLE001
        return None
    u = d.get("imageProcUrl") or d.get("imageLthUrl")
    return u.replace("{{sizeprefix}}", "proc") if u else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lng", type=float, required=True)
    ap.add_argument("--radius", type=int, default=1200)
    ap.add_argument("--name", required=True)
    ap.add_argument("--max", type=int, default=100)
    ap.add_argument("--fps", type=float, default=4.0)
    args = ap.parse_args()

    dest = ROOT / "data" / "videos" / "streetview" / args.name
    frames_dir = dest / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    with httpx.Client(headers={"User-Agent": "anomaly-demo/0.1 (research)"},
                      follow_redirects=True) as client:
        items = nearby(client, args.lat, args.lng, args.radius)
        if not items:
            raise SystemExit(f"no nearby photos for {args.name}")
        seq_id = Counter(i["sequence_id"] for i in items).most_common(1)[0][0]
        photos = [i for i in items if i["sequence_id"] == seq_id]
        photos.sort(key=lambda p: int(p.get("sequence_index", 0)))
        photos = photos[: args.max]
        print(f"{args.name}: sequence {seq_id}, {len(photos)} candidate frames")

        track = []
        kept = 0
        for p in photos:
            url = proc_url(client, p["id"])
            if not url:
                continue
            try:
                resp = client.get(url, timeout=90)
                if resp.status_code != 200 or resp.content[:3] != b"\xff\xd8\xff":
                    continue
            except Exception:  # noqa: BLE001
                continue
            (frames_dir / f"frame-{kept:05d}.jpg").write_bytes(resp.content)
            track.append({
                "frame": kept + 1, "image_id": p.get("id"), "sequence_id": seq_id,
                "lat": float(p["lat"]), "lon": float(p["lng"]),
                "heading": float(p.get("heading") or 0), "shot_date": p.get("shot_date"),
                "source": "KartaView", "license": "CC BY-SA 4.0",
            })
            kept += 1
            time.sleep(0.15)

    if kept == 0:
        raise SystemExit(f"{args.name}: downloaded 0 frames")
    (dest / "gps_track.jsonl").write_text("".join(json.dumps(t) + "\n" for t in track))
    video = dest / f"{args.name}.mp4"
    subprocess.run(["ffmpeg", "-y", "-nostdin", "-framerate", str(args.fps), "-i",
                    str(frames_dir / "frame-%05d.jpg"), "-vf", "scale=1280:-2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
                   check=True, capture_output=True)
    print(json.dumps({"name": args.name, "sequence": seq_id, "frames": kept,
                      "video": str(video), "gps_track": str(dest / "gps_track.jsonl")}, indent=2))


if __name__ == "__main__":
    main()
