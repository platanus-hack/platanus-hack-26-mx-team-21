# vision-inference

Vision service that **detects and describes urban infrastructure anomalies**
(potholes, trash, broken lighting, street vendors, missing signage, damaged pavement)
from street-level images. It consumes jobs from Supabase `community.inference_jobs`,
downloads the image from R2, runs the models, and writes the verdict back to the row.

**Everything runs on our own hardware — no external model APIs.** All models are
**self-hosted/local** on a **private GPU server** (LLMs served with **vLLM**,
OpenAI-compatible). Nothing is sent to a third-party inference provider.

> The service is hardware-agnostic: it only needs a private GPU server with enough VRAM
> to hold the models. Options range from a **unified-memory Grace-Blackwell box** (≈128 GB,
> high capacity / modest bandwidth — fits large models uncuantized) to a **high-bandwidth
> workstation GPU** like an **RTX PRO 6000 Blackwell** (lower latency per image), or a
> classic **A100 / H100 server**. See `docs/vllm_perf_analysis.md` for the
> capacity-vs-latency trade-off and how to size a second server.

## Architecture — three pillars

1. **Fine-tuned detector (segmentation) — our own model.** A **YOLO26 segmentation** model we
   fine-tuned for potholes on **images we captured and annotated manually** (street-level
   photos, hand-labeled pothole masks). Paired with a Segformer (Cityscapes) road/floor mask
   that gates detections to the drivable surface (kills off-road false positives). Fast
   (ms/frame), runs every frame in the offline `pipeline/`. A public **RDD2022 YOLOv12** model
   serves only as an external baseline we compared against — our YOLO26-seg is the one in the
   cascade. Training/test data and ground truth: see `docs/vision_model_and_ground_truth.md`.
2. **VLM as validator (cascade).** The detector proposes; a **locally-served Qwen2.5-VL**
   confirms each candidate (real pothole vs. shadow / manhole / patch). Segmentation +
   VLM together = high precision **without training the VLM**.
3. **VLM for high-level analysis + RAG.** The same local Qwen2.5-VL describes the whole
   scene and enumerates *all* urban anomalies in natural language, grounded by **RAG from
   our context** — a fixed anomaly taxonomy + municipal criteria injected into the prompt
   today, with **pgvector retrieval** (taxonomy/normativa, visual few-shot) as the next step
   (see `docs/PLAN.md` §RAG).

So: **fine-tuned segmentation detects → local VLM validates → local VLM does the high-level,
RAG-grounded write-up.** The VLMs are served locally (vLLM) and used zero-shot with
structured-output prompting; the *detectors* are the fine-tuned, task-specific models.

Detection is by **shape/appearance over sequences** (events deduped over time), aligned
with the system's capture→detect→prioritize flow.

## Layout
```
src/vision_inference/   # the service package (no GPU, no weights — orchestrates vLLM + R2 + Supabase)
  app.py        FastAPI gateway: POST /v1/analyze (Stage 1, online)
  schemas.py    request/response + JSON schema
  vlm.py        Qwen2.5-VL call (fast=7B / thinking=32B) -> natural-language verdict
  r2.py         download s3://observation-thumbnails/observations/<id>/report.jpg
  supa.py       claim pending jobs, write {"confirmed":true,"body":...} / error
  worker.py     Stage 2 poller: pending -> R2 -> VLM -> update
  listener.py   Stage 2 realtime: subscribe INSERT status=pending (READ-ONLY by default)
  query_jobs.py read-only queries
  db.py         optional local SQLite mirror (MVP)
tests/       # smoke tests (schema validation, r2 url parsing) — no network/GPU
pipeline/    # offline GPU pipeline (detector + render): potholes seg, perspective grid,
             # dynamic anomaly captions, GPS-georeferenced GeoJSON (needs model weights)
ops/         # vLLM launch + Triton(vLLM-backend) scaffold for the unified-server option
docs/        # PLAN.md (architecture, stages, RAG), architecture_justification.md (vLLM+Triton+gRPC,
             # presentation), vision_model_and_ground_truth.md (YOLO26-seg dataset + ground truth),
             # vllm_perf_analysis.md (perf/experiments), prompts.md
```

## Modes (latency vs detail)
- **fast** = Qwen2.5-VL-7B — ~1.3 s/img (compact) / ~2–3 s (natural sentence). Online.
- **thinking** = Qwen2.5-VL-32B — ~30 s/img, richer. Offline.
- **reason** = pending (native-reasoning model, e.g. Qwen3-VL).

## Run (dev)
```bash
# 1) vLLM (separate container; needs the model weights + GPU). 7B on :8001, 32B on :8002.
bash ops/start_both.sh

# 2) gateway (Stage 1)
cp .env.example .env   # fill secrets (gitignored)
pip install -e .       # installs the vision_inference package + deps
uvicorn vision_inference.app:app --host 0.0.0.0 --port 8080

# 3) request
curl -s localhost:8080/v1/analyze -H 'content-type: application/json' \
  -d '{"image_url":"https://<r2>/img.jpg","mode":"fast","id":"row-123","task":"vlm"}' | jq

# Stage 2 (Supabase jobs): python -m vision_inference.worker --once   |   python -m vision_inference.listener
# (console scripts also installed: `vision-worker --once`, `vision-jobs`)

# tests
pip install -e '.[dev]' && pytest -q
```

## Job contract (`community.inference_jobs`)
`r2_url` (s3://…), `thinking_mode` ∈ {flash,thinking}, `status` ∈ {pending,processing,done,error}.
On success → `status='done'`, `response={"confirmed":true,"body":"<descripción>"}`; on failure → `status='error'`.

## Requisitos externos
- vLLM corriendo (no se instala junto al detector NGC — usa su propia imagen; ver `docs/vllm_perf_analysis.md`).
- Supabase: esquema `community` **expuesto** (REST) para queries/escritura; **Realtime** habilitado en la tabla para el listener.
- Secretos en `.env` (gitignored): `SUPABASE_URL/SERVICE_KEY`, `R2_S3_ENDPOINT/ACCESS_KEY/SECRET`.

## Performance / escalado
Ver `docs/vllm_perf_analysis.md`: throughput batch medido (~6.6 img/s 7B, ~17× vs secuencial),
límite de concurrencia, y plan de experimentos (justificar un 2º servidor GPU, multi-servidor
vs un GPU de mayor ancho de banda como el RTX PRO 6000).
