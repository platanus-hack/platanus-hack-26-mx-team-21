# inference_anomalies — real-time road-anomaly serving (private GPU server)

Two-stage **cascade** so the cheap model runs on every frame and the expensive VLM runs
only where it's needed.

```
                      gRPC (bidi stream of JPEG frames)
  client ──────────────────────────────────────────────►  ORCHESTRATOR (gRPC server)
   ▲                                                          │
   │  FrameResult (detector result instantly,                 │ 1) EVERY frame
   │  VLM verdict streamed back when ready)                   ▼
   │                                              ┌───────────────────────────┐
   │                                              │ TRITON (gRPC :8001)        │
   │                                              │  anomaly_detector model    │
   │                                              │  pablo_v1 YOLO-seg +        │
   │                                              │  Segformer floor mask +     │
   │                                              │  floor gate → boxes         │
   │                                              └───────────────────────────┘
   │                                                          │ detections (on_floor potholes)
   │                                                          ▼ 2) ONLY if a *new event* fires
   │                                              ┌───────────────────────────┐
   └───────────────────────────────────────────  │ vLLM (OpenAI API :8000)    │
              (async, non-blocking)               │  Qwen2.5-VL verify:        │
                                                  │  POTHOLE vs ANOMALY+caption│
                                                  └───────────────────────────┘
```

## Why this shape (the whole point)
- **Detector is ~1000× faster than the 32B VLM** (measured: detector ~few ms/frame on TRT;
  Qwen2.5-VL-32B ~34 s/frame bf16). So: detector inline on every frame; VLM only on frames
  the detector flags — and only **once per event** (deduped), **asynchronously** so the live
  stream never blocks on the VLM.
- The orchestrator returns the **detector result immediately**; the **VLM verdict arrives on
  a later stream message** tagged with the same `event_id`/`frame_id`.

## Components
| service | tech | port | role |
|---|---|---|---|
| `anomaly_detector` | **Triton** (Python backend → TensorRT upgrade) | gRPC 8001 | YOLO-seg + Segformer floor gate, every frame |
| `qwen-vl` | **vLLM** (OpenAI-compatible) | HTTP 8000 | verify detected frames, async |
| `orchestrator` | Python **grpc** service | gRPC 50051 | cascade logic, dedup, async VLM dispatch |
| `client` | Python | — | streams frames, prints results |

## Why vLLM for Qwen (not Triton/TRT-LLM by default)
- **vLLM** = fastest path to a working, batched, paged-KV, OpenAI-compatible VLM server with
  multimodal support. Best effort/throughput ratio on our server today.
- **TensorRT-LLM via Triton** is the absolute fastest on Blackwell (FP8/FP4) but a much
  heavier build. It's the **upgrade path** (see "Going faster"); the orchestrator talks to
  Qwen through an OpenAI-style client, so swapping vLLM→TRT-LLM is a base-URL change.

## Latency budget (target, real-time stream)
| stage | bf16 today | optimized target |
|---|---|---|
| detector (YOLO+Segformer), per frame | ~30–60 ms (python) | **~5–10 ms** (TensorRT FP16) |
| floor gate | ~1 ms | ~1 ms |
| VLM call (only on event) | ~34 s (32B bf16) | **~1–2 s** (7B AWQ/FP8 + vLLM, 128 tok) |
| VLM frequency | every event, async | every event, async |

→ Stream runs at detector speed (real-time); VLM verdicts trail by 1–2 s and attach to events.

## Going faster (ordered by impact)
1. **Export detector to TensorRT** (`export/export_yolo_trt.py`) → FP16 engine in Triton → ~5–10 ms/frame, frees Python overhead.
2. **Qwen2.5-VL-7B + AWQ/FP8 on vLLM**, `max_tokens≈128`, image side ≈768 → ~1–2 s/call.
3. **Dedup to events** (one VLM call per pothole, not per frame) — already in `cascade.py`.
4. **Async VLM workers + continuous batching** (vLLM handles batching; orchestrator dispatches concurrently).
5. **Keep models resident** (Triton + vLLM are long-running servers — pay load once).
6. **TensorRT-LLM (FP8) via Triton** for Qwen — max throughput on Blackwell; swap the OpenAI base URL.
7. **gRPC everywhere**, JPEG frames on the wire (small), CUDA shared-memory for Triton I/O (optional).

## Constraint respected
Everything builds on the NGC stack without replacing torch (detector container = our
`road-anomaly-zero-shot:moe`; vLLM/Triton run as their own NGC-based images).
