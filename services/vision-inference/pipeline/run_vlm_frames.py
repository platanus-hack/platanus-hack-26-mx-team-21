"""VLM-verify a specific list of frames (cascade: only the best/event frames).

Saves incrementally to outputs/video_analysis/<name>/vlm_best_report.json after every
frame, so nothing is lost if interrupted. Use --frames to pass the deduped best frames.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import torch
from PIL import Image
from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

ROOT = Path(__file__).resolve().parents[1]
VA = ROOT / "outputs" / "video_analysis"
DEFAULT_MODEL = ROOT / "models" / "Qwen2.5-VL-32B-Instruct"

PROMPT = (
    "You are inspecting a street-level dashcam frame for a road-maintenance survey. "
    "An automatic detector flagged a possible POTHOLE in this frame; verify it. "
    "Respond with STRICT JSON only, keys:\n"
    '  "pothole_present": true/false (a real pavement cavity/broken asphalt, NOT a manhole '
    'cover, drain grate, speed bump, shadow, or road marking),\n'
    '  "what_detector_likely_saw": short phrase (e.g. "manhole cover","real pothole","drain"),\n'
    '  "road_condition": "good"|"fair"|"poor"|"very_poor",\n'
    '  "anomalies": [{"type":..., "where":..., "severity":low/medium/high}],\n'
    '  "scene": one short sentence.\n'
    "Output ONLY the JSON object."
)


def parse_json(t: str) -> dict:
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if not m:
        return {"_parse_error": t[:400]}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"_parse_error": t[:400]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--frames", required=True, help="comma-separated frame numbers")
    ap.add_argument("--model", default=str(DEFAULT_MODEL), help="path to a Qwen2.5-VL model dir")
    ap.add_argument("--out", default="vlm_best_report.json", help="output filename under the video dir")
    ap.add_argument("--max-side", type=int, default=900)
    ap.add_argument("--max-new-tokens", type=int, default=200)
    args = ap.parse_args()
    if not torch.cuda.is_available():
        raise SystemExit("CUDA unavailable")
    dest = VA / args.name
    frames = [int(x) for x in args.frames.split(",") if x.strip()]
    scores = {}
    rj = dest / "results.json"
    if rj.exists():
        for f in json.loads(rj.read_text()).get("per_frame", []):
            scores[f["frame"]] = f.get("max_score")

    t_load = time.perf_counter()
    processor = AutoProcessor.from_pretrained(args.model, local_files_only=True)
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        args.model, local_files_only=True, torch_dtype=torch.bfloat16,
        attn_implementation="sdpa", device_map="cuda").eval()
    print(f"model loaded: {args.model} ({time.perf_counter()-t_load:.0f}s)", flush=True)

    out_path = dest / args.out
    rows = json.loads(out_path.read_text()) if out_path.exists() else []
    done = {r["frame"] for r in rows}
    for idx in frames:
        if idx in done:
            continue
        fp = dest / f"frames/frame-{idx:05d}.jpg"
        if not fp.exists():
            print(f"skip {idx} (no frame)", flush=True)
            continue
        image = Image.open(fp).convert("RGB")
        if max(image.size) > args.max_side:
            s = args.max_side / max(image.size)
            image = image.resize((int(image.width * s), int(image.height * s)))
        messages = [{"role": "user", "content": [
            {"type": "image", "image": image}, {"type": "text", "text": PROMPT}]}]
        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = processor(text=[text], images=[image], return_tensors="pt").to("cuda")
        t0 = time.perf_counter()
        with torch.inference_mode():
            gen = model.generate(**inputs, max_new_tokens=args.max_new_tokens, do_sample=False)
        ans = processor.decode(gen[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)
        dt = time.perf_counter() - t0
        p = parse_json(ans)
        rows.append({"frame": idx, "pablo_v1_score": scores.get(idx),
                     "vlm": p, "secs": round(dt, 1)})
        out_path.write_text(json.dumps(rows, indent=2))  # incremental save
        print(f"f{idx} (det {scores.get(idx)}): pothole={p.get('pothole_present')} "
              f"saw={p.get('what_detector_likely_saw')} ({dt:.1f}s)", flush=True)

    confirmed = sum(1 for r in rows if r["vlm"].get("pothole_present") is True)
    rejected = sum(1 for r in rows if r["vlm"].get("pothole_present") is False)
    secs = [r["secs"] for r in rows if "secs" in r]
    print(json.dumps({"model": args.model, "verified_frames": len(rows),
                      "confirmed_pothole": confirmed, "rejected_not_pothole": rejected,
                      "mean_secs_per_frame": round(sum(secs) / len(secs), 1) if secs else None,
                      "report": str(out_path)}, indent=2))


if __name__ == "__main__":
    main()
