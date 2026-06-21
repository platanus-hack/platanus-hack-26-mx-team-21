"""Triton Python-backend detector: YOLO26-seg (our fine-tune) + Segformer floor gate.

Runs on EVERY frame. Returns only on-floor pothole boxes (the floor gate drops
off-road false positives). Fast path; for lowest latency export the YOLO to a
TensorRT engine and replace this with an ensemble (see export/export_yolo_trt.py).

Models are expected mounted at /models inside the Triton container
(the YOLO26-seg weights file is named pablo_v1.pt on disk for historical reasons):
  /models/pablo_v1/pablo_v1.pt   # YOLO26-seg weights
  /models/segformer-cityscapes/
Set env ANOMALY_MODELS_DIR to override.
"""
import io
import os

import numpy as np
import torch
import torch.nn.functional as F
import triton_python_backend_utils as pb_utils
from PIL import Image
from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor
from ultralytics import YOLO

MODELS = os.environ.get("ANOMALY_MODELS_DIR", "/models")
ROAD_CLASS = 0  # Cityscapes road


class TritonPythonModel:
    def initialize(self, args):
        import json
        cfg = json.loads(args["model_config"])
        params = cfg.get("parameters", {})
        self.conf = float(params.get("conf", {}).get("string_value", "0.40"))
        self.road_frac = float(params.get("road_frac", {}).get("string_value", "0.5"))
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        self.yolo = YOLO(os.path.join(MODELS, "pablo_v1", "pablo_v1.pt"))
        self.pothole_ids = {i for i, n in self.yolo.names.items() if n.lower() == "pothole"} \
            or set(self.yolo.names)
        seg_dir = os.path.join(MODELS, "segformer-cityscapes")
        self.seg_proc = SegformerImageProcessor.from_pretrained(seg_dir, local_files_only=True)
        self.seg = SegformerForSemanticSegmentation.from_pretrained(
            seg_dir, local_files_only=True).to(self.device).eval()

    @torch.inference_mode()
    def _road_mask(self, image: Image.Image) -> np.ndarray:
        inp = self.seg_proc(images=image, return_tensors="pt").to(self.device)
        up = F.interpolate(self.seg(**inp).logits, size=image.size[::-1],
                           mode="bilinear", align_corners=False)
        return (up.argmax(1)[0].cpu().numpy() == ROAD_CLASS)

    def _overlap(self, box, road):
        x1, y1, x2, y2 = (int(max(0, v)) for v in box)
        x2 = min(x2, road.shape[1]); y2 = min(y2, road.shape[0])
        if x2 <= x1 or y2 <= y1:
            return 0.0
        return float(road[y1:y2, x1:x2].mean())

    def execute(self, requests):
        responses = []
        for request in requests:
            jpeg = pb_utils.get_input_tensor_by_name(request, "IMAGE_JPEG").as_numpy()
            image = Image.open(io.BytesIO(jpeg.tobytes())).convert("RGB")
            road = self._road_mask(image)
            res = self.yolo.predict(source=np.asarray(image), conf=self.conf,
                                    device=0, verbose=False)[0]
            boxes, scores, on_floor, overlaps = [], [], [], []
            if res.boxes is not None:
                for b in res.boxes:
                    if int(b.cls[0]) not in self.pothole_ids:
                        continue
                    xyxy = [float(v) for v in b.xyxy[0].tolist()]
                    ov = self._overlap(xyxy, road)
                    boxes.append(xyxy)
                    scores.append(float(b.conf[0]))
                    overlaps.append(ov)
                    on_floor.append(ov >= self.road_frac)
            boxes = np.asarray(boxes, dtype=np.float32).reshape(-1, 4)
            scores = np.asarray(scores, dtype=np.float32)
            on_floor = np.asarray(on_floor, dtype=bool)
            overlaps = np.asarray(overlaps, dtype=np.float32)
            responses.append(pb_utils.InferenceResponse(output_tensors=[
                pb_utils.Tensor("BOXES", boxes),
                pb_utils.Tensor("SCORES", scores),
                pb_utils.Tensor("ON_FLOOR", on_floor),
                pb_utils.Tensor("ROAD_OVERLAP", overlaps),
            ]))
        return responses
