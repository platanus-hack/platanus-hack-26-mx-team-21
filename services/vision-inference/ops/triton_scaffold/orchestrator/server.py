"""Orchestrator gRPC server — the cascade.

EVERY frame -> Triton detector (fast, blocking, returned immediately).
NEW event with an on-floor pothole -> Qwen VLM (async, non-blocking); the verdict is
streamed back on a later message tagged with the same frame_id/event_id.

This keeps the live stream at detector speed while the VLM trails by ~1-2s per event.
"""
from __future__ import annotations

import os
import queue
import threading
import time
from concurrent import futures

import grpc

import anomaly_pb2 as pb
import anomaly_pb2_grpc as pb_grpc
from cascade import CascadePolicy
from detector_client import DetectorClient
from vlm_client import VLMClient

TRITON_URL = os.environ.get("TRITON_URL", "localhost:8001")
VLM_URL = os.environ.get("VLM_URL", "http://localhost:8000/v1")
VLM_MODEL = os.environ.get("VLM_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct")
VLM_WORKERS = int(os.environ.get("VLM_WORKERS", "2"))


class AnomalyServicer(pb_grpc.AnomalyServiceServicer):
    def __init__(self):
        self.detector = DetectorClient(TRITON_URL)
        self.vlm = VLMClient(VLM_URL, VLM_MODEL)
        self.vlm_pool = futures.ThreadPoolExecutor(max_workers=VLM_WORKERS)

    # ---- core per-frame detector step ----
    def _detect(self, frame: pb.Frame):
        t0 = time.perf_counter()
        d = self.detector.infer(frame.image_jpeg)
        dt = (time.perf_counter() - t0) * 1000
        dets = []
        best = None
        for i in range(d["boxes"].shape[0]):
            x1, y1, x2, y2 = (float(v) for v in d["boxes"][i])
            sc = float(d["scores"][i]); onf = bool(d["on_floor"][i])
            ov = float(d["road_overlap"][i])
            dets.append(pb.Detection(label="pothole", score=sc, x1=x1, y1=y1, x2=x2, y2=y2,
                                     on_floor=onf, road_overlap=ov))
            if onf and (best is None or sc > best[0]):
                best = (sc, [x1, y1, x2, y2])
        return dets, best, dt

    # ---- unary ----
    def Analyze(self, frame, context):
        dets, best, dt = self._detect(frame)
        res = pb.FrameResult(frame_id=frame.frame_id, detections=dets, detector_ms=dt,
                             lat=frame.lat, lon=frame.lon)
        if frame.want_vlm and best is not None:
            t0 = time.perf_counter()
            v = self.vlm.verify(frame.image_jpeg)
            res.vlm_ran = True
            res.vlm_ms = (time.perf_counter() - t0) * 1000
            res.final_label = v.get("final_label", "")
            res.pothole_present = bool(v.get("pothole_present") is True)
            res.vlm_comment = f"{v.get('what_it_is','')} | road {v.get('road_condition','?')}"
        return res

    # ---- bidirectional stream ----
    def AnalyzeStream(self, request_iterator, context):
        policy = CascadePolicy()
        out_q: queue.Queue = queue.Queue()
        pending = {"n": 0}
        lock = threading.Lock()

        def on_vlm_done(fut, frame_id, event_id, jpeg_len):
            try:
                v = fut.result()
                r = pb.FrameResult(frame_id=frame_id, event_id=event_id, vlm_ran=True,
                                   final_label=v.get("final_label", ""),
                                   pothole_present=bool(v.get("pothole_present") is True),
                                   vlm_comment=f"{v.get('what_it_is','')} | road {v.get('road_condition','?')}")
            except Exception as e:  # noqa: BLE001
                r = pb.FrameResult(frame_id=frame_id, event_id=event_id, vlm_ran=True,
                                   vlm_comment=f"vlm_error: {type(e).__name__}")
            out_q.put(r)
            with lock:
                pending["n"] -= 1

        def consume():
            for frame in request_iterator:
                dets, best, dt = self._detect(frame)
                res = pb.FrameResult(frame_id=frame.frame_id, detections=dets, detector_ms=dt,
                                     lat=frame.lat, lon=frame.lon)
                if best is not None:
                    eid, run_vlm = policy.assign_event(frame.frame_id, best[1],
                                                       img_w=1920, img_h=1080)
                    res.event_id = eid
                    if run_vlm:
                        jpeg = frame.image_jpeg
                        with lock:
                            pending["n"] += 1
                        fut = self.vlm_pool.submit(self.vlm.verify, jpeg)
                        fut.add_done_callback(
                            lambda f, fid=frame.frame_id, e=eid, n=len(jpeg): on_vlm_done(f, fid, e, n))
                out_q.put(res)             # detector result immediately
                policy.gc()
            out_q.put(None)                # end of input

        threading.Thread(target=consume, daemon=True).start()
        # drain: yield detector results live + VLM verdicts as they complete
        ended = False
        while True:
            item = out_q.get()
            if item is None:
                ended = True
            elif item is not None:
                yield item
            with lock:
                if ended and pending["n"] == 0 and out_q.empty():
                    break


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8),
                         options=[("grpc.max_receive_message_length", 32 * 1024 * 1024)])
    pb_grpc.add_AnomalyServiceServicer_to_server(AnomalyServicer(), server)
    port = os.environ.get("PORT", "50051")
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    print(f"orchestrator gRPC on :{port}  (triton={TRITON_URL}, vlm={VLM_URL})", flush=True)
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
