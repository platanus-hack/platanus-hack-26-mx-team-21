"""Triton gRPC client for the every-frame anomaly_detector model."""
from __future__ import annotations

import numpy as np
import tritonclient.grpc as grpcclient


class DetectorClient:
    def __init__(self, url: str = "localhost:8001", model: str = "anomaly_detector"):
        self.client = grpcclient.InferenceServerClient(url=url)
        self.model = model

    def infer(self, jpeg_bytes: bytes) -> dict:
        arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        inp = grpcclient.InferInput("IMAGE_JPEG", arr.shape, "UINT8")
        inp.set_data_from_numpy(arr)
        out = self.client.infer(self.model, [inp], outputs=[
            grpcclient.InferRequestedOutput("BOXES"),
            grpcclient.InferRequestedOutput("SCORES"),
            grpcclient.InferRequestedOutput("ON_FLOOR"),
            grpcclient.InferRequestedOutput("ROAD_OVERLAP"),
        ])
        boxes = out.as_numpy("BOXES")
        return {
            "boxes": boxes.reshape(-1, 4) if boxes is not None else np.zeros((0, 4), np.float32),
            "scores": out.as_numpy("SCORES"),
            "on_floor": out.as_numpy("ON_FLOOR"),
            "road_overlap": out.as_numpy("ROAD_OVERLAP"),
        }
