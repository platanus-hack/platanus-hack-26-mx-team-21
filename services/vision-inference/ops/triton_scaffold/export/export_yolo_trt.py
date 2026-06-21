"""Export pablo_v1 YOLO-seg to ONNX / TensorRT for the fast Triton path.

Run INSIDE the moe image on the GPU server (TensorRT engines are hardware-specific — build on
the same server you'll serve from). After export, point a Triton 'tensorrt'/'onnxruntime' model
at the artifact instead of the Python backend for ~5-10ms/frame.

  python export/export_yolo_trt.py --fmt engine   # TensorRT FP16 (fastest, server-specific)
  python export/export_yolo_trt.py --fmt onnx      # portable ONNX
"""
import argparse
from pathlib import Path

from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "models" / "pablo_v1" / "pablo_v1.pt"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fmt", choices=["onnx", "engine"], default="engine")
    ap.add_argument("--imgsz", type=int, default=960)
    ap.add_argument("--half", action="store_true", default=True)
    args = ap.parse_args()
    m = YOLO(str(MODEL))
    path = m.export(format=args.fmt, imgsz=args.imgsz, half=args.half, device=0)
    print("exported:", path)
    print("Next: place it under triton/model_repository/pothole_yolo/1/ and write a "
          "matching config.pbtxt (platform: tensorrt_plan or onnxruntime_onnx).")


if __name__ == "__main__":
    main()
