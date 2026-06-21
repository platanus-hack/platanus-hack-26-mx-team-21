"""Stream a video's frames to the orchestrator over gRPC and print cascade results.

Detector results print immediately; VLM verdicts arrive (tagged by event_id) a bit later.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import grpc

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))
import anomaly_pb2 as pb
import anomaly_pb2_grpc as pb_grpc


def frames(video: str, fps: float, max_frames: int):
    cap = cv2.VideoCapture(video)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(src_fps / fps)))
    i = 0
    sent = 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        if i % step == 0:
            ok2, buf = cv2.imencode(".jpg", img)
            if ok2:
                yield pb.Frame(image_jpeg=buf.tobytes(), frame_id=i, timestamp=time.time())
                sent += 1
                if max_frames and sent >= max_frames:
                    break
        i += 1
    cap.release()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--target", default="localhost:50051")
    ap.add_argument("--fps", type=float, default=4.0)
    ap.add_argument("--max-frames", type=int, default=0)
    args = ap.parse_args()
    ch = grpc.insecure_channel(args.target,
                               options=[("grpc.max_send_message_length", 32 * 1024 * 1024)])
    stub = pb_grpc.AnomalyServiceStub(ch)
    n_det = n_vlm = 0
    for res in stub.AnalyzeStream(frames(args.video, args.fps, args.max_frames)):
        if res.vlm_ran:
            n_vlm += 1
            print(f"  [VLM]  frame {res.frame_id} {res.event_id}: {res.final_label} "
                  f"— {res.vlm_comment}")
        else:
            on = sum(1 for d in res.detections if d.on_floor)
            if on:
                n_det += 1
                top = max((d.score for d in res.detections if d.on_floor), default=0)
                print(f"frame {res.frame_id}: {on} on-floor det (top {top:.2f}) "
                      f"{res.event_id}  [{res.detector_ms:.0f}ms]")
    print(f"\ndone. frames with detections: {n_det}, VLM verdicts: {n_vlm}")


if __name__ == "__main__":
    main()
