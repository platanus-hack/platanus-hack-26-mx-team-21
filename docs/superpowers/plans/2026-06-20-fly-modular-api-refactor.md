# Fly Modular API Refactor — Implementation Plan

**Design:** `docs/superpowers/specs/2026-06-20-fly-modular-api-refactor-design.md` (approved)
**Date:** 2026-06-20

One Python FastAPI modular monolith deployed as one Fly Machine. Ports the two
client-side planning mocks (`runAnalysis`, `mockClusteredPriorities`) behind `/v1/planning`,
adds an Anthropic-backed `/v1/llm/drafts:parse`, folds the existing `external-data` pipeline
into a `/v1/datasets/refresh` streaming endpoint, and stubs `/v1/video`. Frontend keeps direct
Supabase reads + the R2 broker; only planning + draft-parse move to the API.

## Build order

1. **Scaffold + shared infra** (`services/api/`)
   - `pyproject.toml` (package `citycrawl_api`, deps incl. datasets stack + fastapi/uvicorn/anthropic).
   - `config.py` — one `Settings` (Supabase, Anthropic, operator key, R2/storage, CORS, db).
   - `errors.py` — `ApiError` + envelope `{error:{code,message,requestId,details}}`; handlers for 401/403/422/502/503.
   - `logging.py` — structured JSON logs, request-id binding, secret redaction.
   - `auth.py` — `require_user` (validate bearer via Supabase `/auth/v1/user`), `require_operator` (constant-time `X-Operator-Key`).
   - `main.py` — app factory, request-id middleware, CORS from `ALLOWED_ORIGINS`, router registration.
   - `routers/health.py` — `GET /health/live` (no upstream calls).

2. **Planning module** (`modules/planning/`)
   - `geometry.py` — port `geo.ts`: haversine, `cluster_indices` (deterministic k-means), `convex_hull` (monotone chain), centroid.
   - `models.py` — camelCase-alias Pydantic for `AnalysisRequest`/`PlanResult`/`ClusteredPriority`/`AnalysisPoint` etc.
   - `protocol.py` — `PlanningEngine` (optimize + cluster_priorities).
   - `mock.py` — `MockPlanningEngine` porting `analysis.ts` exactly (ranking, flat `MOCK_UNIT_COST` budget select, clustering, hull, centroid, stats). Labelled mock.
   - `routers/planning.py` — `POST /v1/planning/optimize`, `POST /v1/planning/priorities:cluster` (user auth).
   - **Parity:** capture TS outputs via a tiny node harness for representative requests; assert byte-equivalent JSON in `tests/integration/test_planning_parity.py`.

3. **LLM module** (`modules/llm/`)
   - `models.py` — `DraftParseRequest`, `PlanDraft` (scalars nullable, lists always arrays).
   - `protocol.py` — `DraftParser`.
   - `anthropic.py` — `AnthropicDraftParser` (tool/structured output → validated `PlanDraft`; map provider errors to 502/503).
   - `routers/llm.py` — `POST /v1/llm/drafts:parse` (user auth).
   - Tests use a fake parser + mocked Anthropic client; no live calls.

4. **Datasets module** (`modules/datasets/`)
   - `git mv` `services/external-data/src/external_data` → `services/api/src/citycrawl_api/modules/datasets`; rewrite `external_data.` imports; `config.py` becomes a shim re-exporting central `Settings`/`get_settings`.
   - `service.py` — `DatasetRefreshService.run(source_ids) -> Iterator[progress records]` wrapping extract → write R2 → upsert Postgres → recompute/supersede ROIs (extracted from the Typer commands).
   - `cli.py` keeps existing commands (status/extract/roi-compute/load-db) + adds `refresh` over the service.
   - `routers/datasets.py` — `POST /v1/datasets/refresh` (user + operator) streaming NDJSON; terminal error record on mid-stream failure.
   - Move `services/external-data/tests` → `services/api/tests/...`; keep green.

5. **Video module** (`modules/video/`) + **main wiring**
   - `models.py` (versioned request/result), `service.py` (capabilities only).
   - `routers/video.py` — `GET /v1/video/capabilities` → `{implemented:false, operations:[]}`.
   - Register all routers in `main.py`.

6. **Frontend wiring** (`frontend/`)
   - `lib/citycrawlApi.ts` — fetch client; attaches Supabase access token; `optimize`, `clusterPriorities`, `parseDraft`. Base from `VITE_CITYCRAWL_API_URL`.
   - `MapPage.tsx` — replace `runAnalysis`/`mockClusteredPriorities` with API calls; debounce + sequence guard for live preview; no local fallback.
   - `AgentPanel.tsx` — enable prompt input; submit → `parseDraft` → populate dock for review (never auto-run).
   - `.env.example` + `.env` add `VITE_CITYCRAWL_API_URL`.

7. **Deploy artifacts + runbook**
   - `Dockerfile` (slim python, uvicorn one worker on `0.0.0.0:8080`, lazy dataset imports), `.dockerignore`.
   - `fly.toml` — app `citycrawl-api`, `shared-cpu-1x` 1GB, `dfw`, autostop/autostart, `min_machines_running=0`, http health check `/health/live`.
   - `.env.example`, `README.md` runbook: deploy, secrets, logs, rollback, scale, temporary 2GB resize, autostop, teardown. No free-tier claim.

8. **Verify + cleanup**
   - Full `pytest` (datasets tests + new api/unit/integration). Frontend `tsc` + `vite build`. Docker build + local `/health/live` smoke (best-effort). `fly config validate` documented (flyctl not installed locally).
   - Remove `services/external-data/cron/*` and `services/worker/` once represented in the API.

## Definition of done
Per design §10: one image + approved routes; planning parity proven; frontend uses Fly planning + draft APIs with direct Supabase reads + R2 broker retained; operator can stream a refresh; video reports not-implemented; all tests pass; runbook complete.
