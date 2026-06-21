from __future__ import annotations

import argparse
import gc
import importlib.machinery
import json
import re
import shutil
import subprocess
import sys
import time
import types
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
import yaml
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"
OUTPUTS = ROOT / "outputs"
PROMPTS = {
    "pothole": "pothole in the road",
    "open_manhole": "open manhole",
    "missing_or_broken_drain_grate": "missing storm drain grate",
}
COLORS = {
    "pothole": (255, 80, 40),
    "open_manhole": (255, 200, 30),
    "missing_or_broken_drain_grate": (60, 210, 255),
}


def release(*objects: Any) -> None:
    del objects
    gc.collect()
    torch.cuda.empty_cache()


def revision(model_dir: Path) -> str:
    return json.loads((model_dir / "roadlab-manifest.json").read_text())["revision"]


def box_record(box: Any, width: int, height: int) -> list[float]:
    values = [max(0.0, float(value)) for value in box]
    values[0], values[2] = sorted((min(values[0], width), min(values[2], width)))
    values[1], values[3] = sorted((min(values[1], height), min(values[3], height)))
    return values


def annotate(image: Image.Image, predictions: list[dict[str, Any]], masks: list[np.ndarray] | None = None) -> Image.Image:
    canvas = image.convert("RGBA")
    if masks:
        overlay = np.zeros((image.height, image.width, 4), dtype=np.uint8)
        for mask, prediction in zip(masks, predictions, strict=False):
            color = COLORS.get(prediction.get("requested_class", ""), (80, 255, 100))
            active = np.asarray(mask, dtype=bool)
            overlay[active] = (*color, 95)
        canvas = Image.alpha_composite(canvas, Image.fromarray(overlay, "RGBA"))
    draw = ImageDraw.Draw(canvas)
    for prediction in predictions:
        box = prediction.get("bbox_xyxy")
        if not box:
            continue
        color = COLORS.get(prediction.get("requested_class", ""), (80, 255, 100))
        label = prediction.get("requested_class") or prediction.get("raw_label") or "detection"
        score = prediction.get("score")
        if score is not None:
            label = f"{label} {score:.3f}"
        draw.rectangle(box, outline=color, width=max(2, image.width // 350))
        text_box = draw.textbbox((box[0], box[1]), label)
        draw.rectangle(text_box, fill=(*color, 230))
        draw.text((box[0], box[1]), label, fill=(0, 0, 0, 255))
    return canvas.convert("RGB")


def panel(image: Image.Image, title: str, width: int, height: int) -> Image.Image:
    fitted = image.copy()
    fitted.thumbnail((width, height - 38))
    result = Image.new("RGB", (width, height), "white")
    result.paste(fitted, ((width - fitted.width) // 2, 38 + (height - 38 - fitted.height) // 2))
    draw = ImageDraw.Draw(result)
    draw.rectangle((0, 0, width, 38), fill=(30, 30, 30))
    draw.text((10, 10), title, fill="white")
    return result


def comparison_canvas(panels: list[tuple[str, Image.Image]], destination: Path) -> None:
    width, height = 640, 500
    cols = 2
    rows = (len(panels) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * width, rows * height), (225, 225, 225))
    for index, (title, image) in enumerate(panels):
        canvas.paste(panel(image, title, width, height), ((index % cols) * width, (index // cols) * height))
    canvas.save(destination, quality=92)


def run_grounding(image: Image.Image) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

    model_dir = MODELS / "IDEA-Research--grounding-dino-base"
    processor = AutoProcessor.from_pretrained(model_dir, local_files_only=True)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(model_dir, local_files_only=True).to("cuda").eval()
    predictions: list[dict[str, Any]] = []
    timings: dict[str, float] = {}
    torch.cuda.reset_peak_memory_stats()
    for requested_class, prompt in PROMPTS.items():
        started = time.perf_counter()
        inputs = processor(images=image, text=prompt, return_tensors="pt").to("cuda")
        with torch.inference_mode():
            outputs = model(**inputs)
        result = processor.post_process_grounded_object_detection(
            outputs, inputs.input_ids, threshold=0.22, text_threshold=0.20,
            target_sizes=[image.size[::-1]],
        )[0]
        timings[prompt] = (time.perf_counter() - started) * 1000
        for box, score, label in zip(result["boxes"], result["scores"], result["labels"], strict=True):
            predictions.append({
                "model_name": "grounding-dino", "model_revision": revision(model_dir),
                "requested_class": requested_class, "raw_label": str(label), "prompt": prompt,
                "bbox_xyxy": box_record(box.tolist(), image.width, image.height),
                "score": float(score), "score_is_calibrated": False,
            })
    metadata = {"timings_ms": timings, "peak_memory_mb": torch.cuda.max_memory_allocated() / 1048576}
    release(model, processor)
    return predictions, metadata


def run_sam2(image: Image.Image, predictions: list[dict[str, Any]]) -> tuple[list[np.ndarray], dict[str, Any]]:
    from transformers import Sam2Model, Sam2Processor

    if not predictions:
        return [], {"status": "skipped_no_boxes"}
    model_dir = MODELS / "facebook--sam2.1-hiera-small"
    processor = Sam2Processor.from_pretrained(model_dir, local_files_only=True)
    model = Sam2Model.from_pretrained(model_dir, local_files_only=True).to("cuda").eval()
    boxes = [prediction["bbox_xyxy"] for prediction in predictions]
    started = time.perf_counter()
    inputs = processor(images=image, input_boxes=[boxes], return_tensors="pt").to("cuda")
    with torch.inference_mode():
        outputs = model(**inputs)
    mask_sets = processor.post_process_masks(outputs.pred_masks.cpu(), inputs["original_sizes"])[0]
    masks = [mask_set[0].numpy() for mask_set in mask_sets]
    metadata = {
        "model_revision": revision(model_dir),
        "runtime_ms": (time.perf_counter() - started) * 1000,
        "mask_count": len(masks),
    }
    release(model, processor, inputs, outputs)
    return masks, metadata


def locate_boxes(answer: str, width: int, height: int) -> list[list[float]]:
    boxes = []
    for match in re.finditer(r"<box><(\d+)><(\d+)><(\d+)><(\d+)></box>", answer):
        normalized = [int(value) / 1000 for value in match.groups()]
        boxes.append(box_record((normalized[0] * width, normalized[1] * height, normalized[2] * width, normalized[3] * height), width, height))
    return boxes


def run_locateanything(image: Image.Image) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    # Image-only compatibility shim: the pinned processor imports decord even when no video is used.
    decord_stub = types.ModuleType("decord")
    decord_stub.__spec__ = importlib.machinery.ModuleSpec("decord", loader=None)
    sys.modules.setdefault("decord", decord_stub)
    from transformers import AutoModel, AutoProcessor, AutoTokenizer

    model_dir = MODELS / "nvidia--LocateAnything-3B"
    tokenizer = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True, local_files_only=True)
    processor = AutoProcessor.from_pretrained(model_dir, trust_remote_code=True, local_files_only=True)
    model = AutoModel.from_pretrained(
        model_dir, trust_remote_code=True, local_files_only=True, torch_dtype=torch.bfloat16,
    ).to("cuda").eval()
    predictions: list[dict[str, Any]] = []
    answers: dict[str, str] = {}
    timings: dict[str, float] = {}
    torch.cuda.reset_peak_memory_stats()
    for requested_class, phrase in PROMPTS.items():
        question = f"Locate all the instances that match the following description: {phrase}."
        messages = [{"role": "user", "content": [
            {"type": "image", "image": image}, {"type": "text", "text": question},
        ]}]
        text = processor.py_apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        images, videos = processor.process_vision_info(messages)
        inputs = processor(text=[text], images=images, videos=videos, return_tensors="pt").to("cuda")
        started = time.perf_counter()
        with torch.inference_mode():
            response = model.generate(
                pixel_values=inputs["pixel_values"].to(torch.bfloat16),
                input_ids=inputs["input_ids"], attention_mask=inputs["attention_mask"],
                image_grid_hws=inputs.get("image_grid_hws"), tokenizer=tokenizer,
                max_new_tokens=512, use_cache=True, generation_mode="hybrid",
                temperature=0.0, do_sample=False, verbose=False,
            )
        timings[phrase] = (time.perf_counter() - started) * 1000
        answer = str(response[0] if isinstance(response, tuple) else response)
        answers[phrase] = answer
        for box in locate_boxes(answer, image.width, image.height):
            predictions.append({
                "model_name": "locateanything", "model_revision": revision(model_dir),
                "requested_class": requested_class, "raw_label": None, "prompt": phrase,
                "bbox_xyxy": box, "score": None, "score_is_calibrated": False,
            })
    metadata = {"answers": answers, "timings_ms": timings, "peak_memory_mb": torch.cuda.max_memory_allocated() / 1048576}
    release(model, processor, tokenizer)
    return predictions, metadata


def process_image(image_path: Path, destination: Path, models: set[str]) -> dict[str, Any]:
    destination.mkdir(parents=True, exist_ok=True)
    image = Image.open(image_path).convert("RGB")
    image.save(destination / "original.jpg", quality=95)
    report: dict[str, Any] = {"source": str(image_path), "width": image.width, "height": image.height, "models": {}}
    panels: list[tuple[str, Image.Image]] = [("Original", image)]

    grounding_predictions: list[dict[str, Any]] = []
    if "grounding-dino" in models:
        grounding_predictions, metadata = run_grounding(image)
        rendered = annotate(image, grounding_predictions)
        rendered.save(destination / "grounding_dino.jpg", quality=92)
        panels.append(("Grounding DINO", rendered))
        report["models"]["grounding-dino"] = {"predictions": grounding_predictions, **metadata}

    if "sam2" in models and grounding_predictions:
        masks, metadata = run_sam2(image, grounding_predictions)
        rendered = annotate(image, grounding_predictions, masks)
        rendered.save(destination / "grounding_dino_sam2.jpg", quality=92)
        panels.append(("Grounding DINO + SAM2", rendered))
        mask_dir = destination / "masks"
        mask_dir.mkdir(exist_ok=True)
        for index, mask in enumerate(masks):
            Image.fromarray((mask.astype(np.uint8) * 255)).save(mask_dir / f"mask-{index:04d}.png")
        report["models"]["sam2"] = metadata

    if "locateanything" in models:
        try:
            predictions, metadata = run_locateanything(image)
            rendered = annotate(image, predictions)
            rendered.save(destination / "locateanything.jpg", quality=92)
            panels.append(("LocateAnything", rendered))
            report["models"]["locateanything"] = {"predictions": predictions, **metadata}
        except Exception as exc:
            report["models"]["locateanything"] = {"error": f"{type(exc).__name__}: {exc}"}

    comparison_canvas(panels, destination / "comparison.jpg")
    (destination / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def extract_keyframes(video: Path, output: Path, fps: float, max_frames: int) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-nostdin", "-i", str(video), "-vf", f"fps={fps}",
        "-frames:v", str(max_frames), "-q:v", "2", str(output / "frame-%05d.jpg"),
    ], check=True, capture_output=True)
    return sorted(output.glob("frame-*.jpg"))


def build_video(frames: list[Path], destination: Path, fps: float) -> None:
    if not frames:
        return
    subprocess.run([
        "ffmpeg", "-y", "-nostdin", "-framerate", str(fps), "-i",
        str(frames[0].parent / "frame-%05d.jpg"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(destination),
    ], check=True, capture_output=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--image", type=Path)
    group.add_argument("--video", type=Path)
    parser.add_argument("--models", default="grounding-dino,sam2,locateanything")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fps", type=float, default=1.0)
    parser.add_argument("--max-frames", type=int, default=8)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise SystemExit("CUDA unavailable; CPU fallback is disabled")
    models = set(args.models.split(","))
    if args.image:
        output = args.output or OUTPUTS / "comparisons" / args.image.stem
        report = process_image(args.image, output, models)
        print(json.dumps({"output": str(output), "models": list(report["models"])}, indent=2))
        return
    output = args.output or OUTPUTS / "videos" / args.video.stem
    raw_frames = extract_keyframes(args.video, output / "keyframes", args.fps, args.max_frames)
    annotated_frames = output / "annotated"
    annotated_frames.mkdir(parents=True, exist_ok=True)
    summaries = []
    for index, frame in enumerate(raw_frames, start=1):
        frame_output = output / "frames" / frame.stem
        report = process_image(frame, frame_output, models)
        shutil.copy2(frame_output / "comparison.jpg", annotated_frames / f"frame-{index:05d}.jpg")
        summaries.append(report)
    build_video(sorted(annotated_frames.glob("frame-*.jpg")), output / "comparison-preview.mp4", args.fps)
    (output / "results.json").write_text(json.dumps({"source": str(args.video), "fps": args.fps, "frames": summaries}, indent=2) + "\n")
    print(json.dumps({"output": str(output), "frame_count": len(raw_frames)}, indent=2))


if __name__ == "__main__":
    main()
