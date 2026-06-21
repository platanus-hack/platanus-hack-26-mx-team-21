# Why two serving stacks: **vLLM for the LLM/VLM, Triton for vision segmentation (over gRPC)**

Presentation-ready justification. TL;DR: the two workloads have **opposite performance
profiles**, so we serve each on the runtime built for it, and connect them with **gRPC**.
Both run **locally on our private GPU server** — no external APIs.

## The two workloads are fundamentally different
| | Vision segmentation (YOLO-seg, Segformer) | LLM / VLM (Qwen2.5-VL) |
|---|---|---|
| Shape | **fixed-size** tensors (image in, masks out) | **variable-length**, autoregressive tokens |
| Compute | **1 forward pass**, compute-bound | **decode loop**, memory-bandwidth-bound |
| Cadence | **every frame** (real-time) | **only on events** (deduped detections) |
| Latency | **~5–60 ms/frame** | ~1–3 s (7B) / ~30 s (32B) |
| Best runtime | **Triton + TensorRT** | **vLLM (PagedAttention)** |

Serving both on one generic stack would under-serve both. Matching each to its runtime is
the whole argument.

## Why **vLLM** for the LLM/VLM
- **PagedAttention + continuous batching** — built for autoregressive, variable-length
  decode. Measured **~17× throughput** vs sequential on our server (6.6 img/s on 7B), with
  vLLM reporting up to **~34× max concurrency**. This is the single biggest LLM speed lever
  and Triton's generic batching does not give it.
- **Resident weights = continuous serving** — verified: up 8 h, **0 restarts**, model
  loaded, **0.62 s warm response**, **GPU idle ~0%** between requests. Pay the load once,
  serve forever.
- **OpenAI-compatible API** — trivial client; swap models/modes (fast 7B ↔ thinking 32B) by
  config; **future TRT-LLM upgrade is a base-URL change**, not a rewrite.
- **Structured output** (`response_format=json_object`) — valid JSON every time.
- **Torch isolation** — vLLM pins its own torch; running it standalone keeps the **NGC torch
  stack (2.12 nv26.05, tuned for our GPU) intact for the detector**. One stack can't satisfy
  both dependency sets.

## Why **Triton** for vision segmentation
- **TensorRT / ONNX backends** — FP16 engines bring the detector from ~30–60 ms (Python) to
  **~5–10 ms/frame**, so it can run on **every frame** in the real-time path.
- **Dynamic batching of fixed-shape tensors** + **multiple model instances** + **concurrent
  model execution** — exactly what CV models need (and what vLLM is *not* for).
- **Model ensemble / BLS** — chain *detector → floor-gate (Segformer) → optional VLM-verify*
  inside one server call, no round-trips.
- **CUDA shared-memory I/O & metrics** — production-grade serving for high-FPS streams.
- Mature, batteries-included for vision; we keep our **fine-tuned YOLO26 segmentation** model
  (trained on manually-captured, manually-annotated pothole images) here, plus the Segformer
  floor gate. See `docs/vision_model_and_ground_truth.md`.

## Why **gRPC** between them
- **Low-latency binary protocol** (protobuf + HTTP/2 multiplexing, streaming) — right for
  **high-frequency frame streaming**; avoids per-frame REST/JSON overhead.
- **Triton speaks gRPC natively**; a clean **`.proto` contract** keeps the boundary typed and
  language-agnostic.
- **Process/runtime decoupling** — two containers, **two torch environments, no dependency
  conflict**; each scales and restarts independently. The detector scales with **frame rate**,
  the VLM with **event rate** — the gRPC seam lets them sit on different GPUs/servers later
  (data-parallel replicas).

## How it maps to our cascade (one slide)
```
frames ──gRPC──► Triton (TensorRT detector + Segformer floor-gate)   ← every frame, ~ms
                      │ events (deduped by shape + GPS)
                      ▼
                  vLLM (Qwen2.5-VL)  ← only per event: validate + high-level, RAG-grounded
```
**Cheap model on every frame, expensive model only on what matters.** Two runtimes = the two
cost tiers, each served by the engine designed for it — all on our own hardware.

## One-line takeaways for the slide
- *"Right engine for each workload: vLLM (PagedAttention) for token decode, Triton (TensorRT)
  for fixed-shape vision — 17× and ~10 ms respectively, measured."*
- *"gRPC seam decouples two torch stacks, lets each scale on its own axis (frame-rate vs
  event-rate)."*
- *"All local, always-on: model resident, 0 restarts in 8 h, sub-second warm."*
