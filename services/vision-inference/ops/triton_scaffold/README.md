# inference_anomalies — real-time cascade serving

**YOLO detector on every frame (Triton, gRPC) → Qwen VLM only on detected frames
(vLLM, async).** See `ARCHITECTURE.md` for the design + latency budget.

## Layout
```
inference_anomalies/
├── ARCHITECTURE.md            # the plan, latency budget, "going faster"
├── proto/anomaly.proto        # gRPC contract (stream of frames -> results)
├── triton/model_repository/anomaly_detector/   # every-frame detector (python backend)
│   ├── config.pbtxt
│   └── 1/model.py             # YOLO26-seg (our fine-tune) + Segformer floor gate
├── orchestrator/              # the cascade brain (gRPC server)
│   ├── server.py              # detector inline + async VLM on new events
│   ├── cascade.py             # event dedup → VLM at most once per pothole
│   ├── detector_client.py     # Triton gRPC client
│   ├── vlm_client.py          # OpenAI-compatible (vLLM / TRT-LLM) client
│   ├── requirements.txt  Dockerfile
├── vllm/start_vllm.sh         # serve Qwen2.5-VL (OpenAI API)
├── client/stream_client.py    # stream a video, print results
├── export/export_yolo_trt.py  # YOLO -> TensorRT (fast path)
├── scripts/gen_proto.sh       # generate gRPC stubs
└── docker-compose.yaml        # triton + vllm + orchestrator
```

## Quickstart (on the private GPU server)

1) **Generate gRPC stubs** (needed by orchestrator + client):
```bash
cd inference_anomalies && bash scripts/gen_proto.sh
```

2) **Start the detector (Triton)** — serves `anomaly_detector` over gRPC :8001.
The python backend needs `ultralytics`+`transformers` in Triton's env; simplest is to run it
inside our `road-anomaly-zero-shot:moe` image, or build a custom Triton image. Models are
mounted from `../models` (YOLO26-seg weights + segformer-cityscapes).

3) **Start Qwen (vLLM)** — OpenAI API on :8000:
```bash
VLM_MODEL=Qwen/Qwen2.5-VL-7B-Instruct bash vllm/start_vllm.sh
```

4) **Start the orchestrator** (gRPC :50051):
```bash
cd orchestrator && TRITON_URL=localhost:8001 VLM_URL=http://localhost:8000/v1 python server.py
```

5) **Stream a video:**
```bash
python client/stream_client.py --video ../data/videos/drive/video2.mp4 --fps 4
```
You'll see detector hits print live (`[..ms]`), and `[VLM]` verdicts (`POTHOLE`/`ANOMALY`
+ caption) arrive shortly after, one per event.

Or bring everything up with `docker compose up` (adjust images to your NGC/arm64 builds).

## The cascade in one line
The detector decides **where to look**; the VLM decides **what it is** — and only once per
pothole. That's how you get real-time throughput on the cheap model and VLM-grade precision
without paying VLM cost on every frame.

## Going faster (see ARCHITECTURE.md)
TensorRT detector (~5-10ms) · Qwen-7B AWQ/FP8 on vLLM (~1-2s) · event dedup (done) ·
async VLM workers · keep models resident · TensorRT-LLM (FP8) for max VLM throughput.
