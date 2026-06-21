# Fly Modular API Refactor - Design

**Date:** 2026-06-20
**Status:** Approved design
**Component:** Planning, application LLM, external datasets, and future video API

---

## 1. Goal and Scope

Consolidate compute-facing services into one Python modular API deployed as one Fly.io
Machine. The API is an ad-hoc HTTP server: incoming requests call service modules directly.
There is no scheduler, queue poller, Supabase-triggered execution, or second worker process.

The first deployment includes:

- A versioned planning API with a Python port of the current frontend mock.
- A provider-neutral natural-language draft parser with Anthropic as the initial adapter.
- A manually triggered endpoint that runs the complete external-dataset pipeline.
- A versioned extension point for future video processing, without fake processing behavior.
- Shared authentication, configuration, errors, request IDs, health checks, and logging.
- A single Docker/Fly deployment artifact and a deploy/teardown runbook.

The refactor also moves both existing client-side planning computations behind the API:
`runAnalysis` and `mockClusteredPriorities`. It preserves their current behavior and wire
shapes so a real optimizer can replace the mock without another frontend contract change.

## 2. Explicit Boundaries

### 2.1 Remains outside Fly

- **Supabase Auth and Postgres** remain managed dependencies and the system of record.
- The frontend continues to call existing Supabase `public.app_*` RPCs directly for reads.
- The deployed **Cloudflare R2 broker** remains in `services/broker`. It already has tested
  Postgres-mediated authorization and native R2 bindings; proxying R2 through Fly would add
  credentials, runtime use, and bandwidth without improving the product boundary.
- R2 remains the object store. The API's dataset module uses its S3-compatible server-side
  interface, as the existing external-data pipeline does.

### 2.2 Out of scope

- A production optimization algorithm or new cost model.
- Video decoding, inference, thumbnailing, or observation creation.
- Scheduled dataset refreshes.
- Durable queues, background consumers, process supervisors, or additional Fly Machines.
- Proxying existing frontend read APIs through Fly.
- Migrating the frontend host, Supabase, or R2.
- Migrating the R2 access broker into the modular API.

## 3. Architecture

The selected architecture is a native Python modular monolith:

```text
 React SPA                                      Operator curl
 Supabase session JWT                          JWT + operator key
       |                                               |
       +------------------- Fly Proxy -----------------+
                               |
                     FastAPI /v1 (one Uvicorn worker)
                               |
          +--------------------+--------------------+
          |                    |                    |
     Planning module       LLM module         Dataset module
     contract + mock       contract +         extract -> stage ->
     implementation        Anthropic adapter  load -> recompute ROIs
                               |
                        Future video module
                        contract only
          |                    |                    |
          +---------- Supabase / Anthropic / R2 ---+

 Browser media and tile reads ----------------> Cloudflare R2 broker
```

FastAPI routers translate HTTP requests into typed service calls. Routers contain no
algorithm or provider logic. Each module owns its models, protocol, and implementation,
so a later optimizer, LLM provider, or video processor can be replaced independently.

The API uses one Uvicorn worker to fit the initial 1 GB memory budget. Dataset libraries
are imported lazily so normal planning/LLM requests do not eagerly load pandas, PyArrow,
NumPy, scikit-learn, and the geospatial stack.

## 4. Repository Structure

```text
services/api/
|-- pyproject.toml
|-- Dockerfile
|-- .dockerignore
|-- fly.toml
|-- .env.example
|-- README.md
|-- src/citycrawl_api/
|   |-- __init__.py
|   |-- main.py
|   |-- config.py
|   |-- auth.py
|   |-- errors.py
|   |-- logging.py
|   |-- routers/
|   |   |-- health.py
|   |   |-- planning.py
|   |   |-- llm.py
|   |   |-- datasets.py
|   |   `-- video.py
|   `-- modules/
|       |-- planning/
|       |   |-- models.py
|       |   |-- protocol.py
|       |   |-- geometry.py
|       |   `-- mock.py
|       |-- llm/
|       |   |-- models.py
|       |   |-- protocol.py
|       |   `-- anthropic.py
|       |-- datasets/
|       |   |-- service.py
|       |   |-- cli.py
|       |   |-- schema.py
|       |   |-- adapters/
|       |   |-- core/
|       |   |-- geocode/
|       |   |-- registry/
|       |   `-- roi/
|       `-- video/
|           |-- models.py
|           `-- service.py
`-- tests/
    |-- unit/
    |-- api/
    `-- integration/
```

`services/api` is the only Fly artifact. The code currently under
`services/external-data/src/external_data` moves into the dataset module, and its tests
move under the API test tree. Typer remains only as a local adapter over the same callable
dataset service. The obsolete external-data Docker/Cloudflare cron configuration and the
empty `services/worker` placeholder are removed after their contracts are represented in
the API.

`services/broker` remains independently deployable on Cloudflare. The
`ActionableOptimization` playground remains research input and is not promoted into the
production package by this refactor.

## 5. HTTP and Module Contracts

All application JSON uses the existing frontend's camelCase field convention. Pydantic
models expose aliases while Python internals use snake_case. All routes are under `/v1`.

### 5.1 Health

```http
GET /health/live
```

This public endpoint reports that the process can serve requests. It does not call
Supabase, Anthropic, or R2, so an upstream outage cannot cause Fly to restart a healthy
process.

### 5.2 Planning

```http
POST /v1/planning/optimize
Authorization: Bearer <supabase-access-token>
```

The request is the existing `AnalysisRequest`: issue type, budget, region filter, optional
squad count, cost configuration, and eligible points. The response is the existing
`PlanResult`: selected critical observations, squads, hulls, centroids, costs, and stats.

```http
POST /v1/planning/priorities:cluster
Authorization: Bearer <supabase-access-token>
```

This route moves `mockClusteredPriorities` out of the browser and returns the current
`ClusteredPriority[]` contract. It remains separate because priority clusters depend on
the visible points, while an action plan additionally depends on budget and selection.

Both routes depend on a `PlanningEngine` protocol. `MockPlanningEngine` ports the current
ranking, flat nominal budget selection, deterministic clustering, convex hull, centroid,
and placeholder weighting behavior exactly. It is explicitly labeled as a mock in API
metadata and source comments.

The frontend calls `optimize` when the user generates a plan. While a plan preview is
open, changes are debounced and prior requests are aborted or ignored using a request
sequence guard. There is no client-side computation fallback.

### 5.3 Natural-language draft parsing

```http
POST /v1/llm/drafts:parse
Authorization: Bearer <supabase-access-token>
```

The request carries the prompt plus the issue-type and region choices already visible to
the frontend. The parser returns an editable `PlanDraft` containing recognized issue type,
budget, region codes, squad count, unresolved terms, and warnings.

```json
{
  "issueType": "pothole",
  "budget": 2000000,
  "regionFilter": ["005"],
  "squadCount": 3,
  "unresolvedTerms": [],
  "warnings": []
}
```

Recognized scalar fields may be `null`; list fields are always arrays. Cost overrides are
not inferred in the first version and remain unchanged in the dock.

The endpoint enables the currently disabled prompt input in `AgentPanel`. A successful
draft populates the existing dock for user review. It never starts optimization or submits
an analysis automatically.

The router depends on a provider-neutral `DraftParser` protocol. The only initial adapter
is `AnthropicDraftParser`, configured by `ANTHROPIC_API_KEY` and model name. Provider output
must validate as `PlanDraft`; provider-specific responses never cross the module boundary.
No unused provider factory or second adapter is added.

### 5.4 External dataset refresh

```http
POST /v1/datasets/refresh
Authorization: Bearer <supabase-access-token>
X-Operator-Key: <operator-key>
Content-Type: application/json

{"sourceIds": []}
```

An empty or omitted `sourceIds` means all enabled sources. The request directly executes:

```text
extract selected sources
  -> write raw/staged objects to R2
  -> upsert staged signals into Supabase Postgres
  -> recompute and supersede affected ROI dimensions
```

The implementation extracts orchestration from the existing Typer commands into one
`DatasetRefreshService`. The CLI and HTTP router are adapters over that service rather
than separate execution paths.

Because refreshes can take minutes, the endpoint keeps the same HTTP request open and
streams newline-delimited JSON progress records. Records identify the stage, source,
counts, and final ROI run summary. Authentication and configuration failures return a
normal HTTP error before streaming begins. A failure after streaming starts emits a
terminal error record naming the failed stage and completed work.

```json
{"type":"progress","stage":"extract","sourceId":"ssc_hechos_transito","count":1000}
{"type":"complete","signalCount":1000,"roiRunId":"...","roiCount":12}
{"type":"error","stage":"load","error":{"code":"dataset_load_failed","message":"...","requestId":"..."}}
```

The existing signal upserts are idempotent. ROI supersession occurs only through the
existing run/store contract, allowing an operator to retry a partial refresh without
inventing a second recovery mechanism.

### 5.5 Video extension point

The `/v1/video` router and versioned request/result model package are created, but no
processing endpoint reports success. `GET /v1/video/capabilities` reports
`{"implemented": false, "operations": []}`.
Actual video execution, storage writes, limits, and failure semantics require a separate
design when the processor exists.

### 5.6 Additional modules

A new service follows the same local pattern: focused router, typed models, protocol, and
implementation under `modules/<name>`, then explicit router registration in `main.py`.
There is no dynamic plugin loader; explicit registration is simpler and makes the public
surface reviewable.

## 6. Authentication and Secrets

The frontend keeps Supabase Auth. Browser calls send the existing Supabase access token to
Fly. The API validates it with Supabase Auth's `/auth/v1/user` endpoint using the caller's
bearer token, `SUPABASE_URL`, and the publishable anon key; Supabase is not a trigger and
does not call Fly.

Planning, LLM, and future video routes require a valid user token. Dataset refresh requires
both a valid user token and `X-Operator-Key`, compared to `OPERATOR_API_KEY` in constant
time. This prevents a browser user from spending external API/storage resources merely by
having a session.

Server-only configuration includes:

- `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and `DB_URL`.
- `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL`.
- `OPERATOR_API_KEY`.
- `R2_S3_ENDPOINT`, `R2_ACCESS_KEY`, `R2_SECRET`, and bucket names.
- `ALLOWED_ORIGINS`.

Secrets are set with `fly secrets set` and never committed or exposed through health,
errors, logs, or frontend environment variables. `VITE_CITYCRAWL_API_URL` is the only new
frontend API setting.

## 7. Errors and Observability

Non-streaming errors use one envelope:

```json
{
  "error": {
    "code": "stable_machine_code",
    "message": "safe human-readable message",
    "requestId": "...",
    "details": {}
  }
}
```

- Request validation returns `422`.
- Missing or invalid Supabase credentials return `401`.
- A missing or invalid operator key returns `403`.
- Explicit upstream timeouts prevent hanging provider calls.
- Anthropic rate limits, timeouts, and unavailable responses map to stable `502` or `503`
  errors without raw provider bodies.
- Invalid LLM structured output is rejected and never applied to the frontend form.
- Dataset stream failures use the same error fields in a terminal NDJSON record because an
  HTTP status cannot change after streaming begins.

Middleware accepts a valid incoming request ID or creates one, returns it as
`X-Request-ID`, and binds it to structured JSON logs. Logs contain route, status, elapsed
time, and safe service/stage fields. They exclude JWTs, operator keys, provider keys,
database URLs, R2 credentials, and prompt content by default.

## 8. Fly.io Deployment

The deployment uses:

- One Fly App named with the `citycrawl-api` convention.
- One `shared-cpu-1x` Machine with 1 GB RAM.
- One Uvicorn worker listening on `0.0.0.0:8080`.
- `dfw` as the initial region because Fly currently has no Mexico region and Dallas is the
  closest listed deployment choice to the target users.
- No Fly Volume; durable data stays in Supabase and R2.
- HTTP health checks against `/health/live`.
- Autostop enabled, autostart enabled, and `min_machines_running = 0` by default.

The Machine can be kept running during a demo by changing the minimum to one. A documented
temporary resize to 2 GB is allowed for large dataset or future video experiments, followed
by an immediate resize back to 1 GB. The runbook includes deploy, secret rotation, logs,
rollback, scaling, autostop, and destruction after the event.

Fly has no permanent free tier for a new account. Machines are billed per second while
running, with smaller stopped-root-filesystem charges. This design therefore minimizes
Machines and volumes rather than claiming a free deployment. Current references:

- [Fly.io pricing](https://fly.io/docs/about/pricing/)
- [Fly.io billing](https://fly.io/docs/about/billing/)
- [Autostop/autostart](https://fly.io/docs/launch/autostop-autostart/)
- [Current Fly regions](https://fly.io/docs/reference/regions/)

## 9. Verification Strategy

### 9.1 Planning parity

Before deleting client computations, capture representative `AnalysisRequest` fixtures and
their current TypeScript results. Python parity tests compare full JSON responses for:

- Empty and single-point inputs.
- Budget below one item and budget covering several items.
- Default, excessive, and negative/invalid squad counts at the HTTP boundary.
- Region-filtered points.
- Deterministic cluster membership, hull ordering, weights, and statistics.
- Standalone clustered-priority output.

### 9.2 API and module tests

- Unit tests cover planning geometry and service behavior.
- LLM tests use a fake `DraftParser` plus mocked Anthropic responses; no live provider call
  is required in the normal suite.
- Dataset orchestration tests use fake extract/store/load/ROI collaborators and assert exact
  stage order, source filters, summaries, and terminal failures.
- Existing external-data registry, adapters, geocoding, storage, schema, ROI, and Postgres
  opt-in tests move with the module and remain green.
- FastAPI tests cover models, auth, operator protection, CORS, request IDs, errors, health,
  and NDJSON stream behavior.
- Frontend tests cover authenticated API calls, loading and error states, stale planning
  response suppression, draft population, and the absence of local planning execution.

### 9.3 Build and deployment checks

The completion gate runs:

- The complete Python test suite.
- Frontend typecheck and production build.
- Docker image build and local container health smoke test.
- Planning and dataset API smoke requests against the local container with fakes/local
  storage where appropriate.
- `fly config validate`.
- An opt-in deployed smoke test for health, Supabase authentication, one planning request,
  and one deliberately narrow dataset refresh.

## 10. Definition of Done

The refactor is complete when:

1. `services/api` builds one image and exposes the approved routes under `citycrawl_api`.
2. Python planning parity tests prove both client-side planning mocks were migrated.
3. The frontend uses the Fly planning and draft-parser APIs while retaining direct Supabase
   reads and the existing Cloudflare broker for object bytes.
4. An authenticated operator can stream a filtered or full dataset refresh through all
   stages and receive a final summary.
5. Video capabilities accurately report that processing is not implemented.
6. Existing external-data tests and all new API/frontend tests pass.
7. A 1 GB single-Machine Fly deployment passes health and authenticated smoke tests.
8. The runbook explains normal deploy, temporary resize, rollback, autostop, cost controls,
   and teardown without relying on a nonexistent free tier.
