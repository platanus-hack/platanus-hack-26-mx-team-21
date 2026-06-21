# citycrawl-api

One Python FastAPI modular monolith, deployed as **one Fly.io Machine**. It consolidates the
compute-facing services behind `/v1`:

- **Planning** (`/v1/planning/optimize`, `/v1/planning/priorities:cluster`) — Python port of
  the former client-side mocks (`runAnalysis`, `mockClusteredPriorities`) behind a
  `PlanningEngine` protocol. A real optimizer replaces `MockPlanningEngine` with no frontend
  contract change.
- **LLM draft parsing** (`/v1/llm/drafts:parse`) — provider-neutral `DraftParser`; the only
  adapter today is Anthropic. Returns an editable `PlanDraft`.
- **Dataset refresh** (`/v1/datasets/refresh`) — operator-protected; streams NDJSON progress
  through extract → R2 → Postgres upsert → ROI recompute/supersede. The former
  `services/external-data` package now lives under `modules/datasets`; the Typer CLI
  (`citycrawl-datasets`) and the HTTP route are both adapters over `DatasetRefreshService`.
- **Video** (`/v1/video/capabilities`) — extension point only; reports `implemented: false`.

**Design:** `docs/superpowers/specs/2026-06-20-fly-modular-api-refactor-design.md`
**Plan:** `docs/superpowers/plans/2026-06-20-fly-modular-api-refactor.md`

## What stays outside Fly

Supabase Auth + Postgres remain the system of record; the frontend keeps calling
`public.app_*` RPCs directly for reads. The Cloudflare **R2 broker** (`services/broker`) still
serves object bytes. R2 remains the object store; this API writes to it server-side.

## Local development

```bash
cd services/api
uv venv --python 3.11 .venv && . .venv/bin/activate
uv pip install -e ".[dev]"
pytest                      # full suite incl. TS→Python planning parity
cp .env.example .env        # fill in secrets for live calls
uvicorn citycrawl_api.main:app --reload --port 8080
curl -s localhost:8080/health/live      # {"status":"ok"}
```

Regenerate the planning parity fixture from the live frontend mock (only needed while the
frontend mock still exists):

```bash
npx -y tsx tests/integration/capture_ts_planning.mts
```

Run the dataset pipeline locally via the CLI adapter:

```bash
citycrawl-datasets status
citycrawl-datasets refresh --source ssc_hechos_transito   # NDJSON progress
```

## Routes and auth

| Route | Method | Auth |
|-------|--------|------|
| `/health/live` | GET | public |
| `/v1/planning/optimize` | POST | Supabase bearer token |
| `/v1/planning/priorities:cluster` | POST | Supabase bearer token |
| `/v1/llm/drafts:parse` | POST | Supabase bearer token |
| `/v1/datasets/refresh` | POST | Supabase bearer token **+** `X-Operator-Key` |
| `/v1/video/capabilities` | GET | Supabase bearer token |

Tokens are validated against Supabase Auth's `/auth/v1/user`. Non-streaming errors use one
envelope `{"error":{"code","message","requestId","details"}}`; a dataset failure mid-stream is
a terminal NDJSON `error` record (the HTTP status cannot change once streaming begins).

---

## Fly.io runbook

Fly has **no permanent free tier** for a new account: Machines are billed per second while
running, with smaller stopped-root-filesystem charges. This deployment minimizes Machines and
uses no Volume. References: [pricing](https://fly.io/docs/about/pricing/),
[billing](https://fly.io/docs/about/billing/),
[autostop/autostart](https://fly.io/docs/launch/autostop-autostart/),
[regions](https://fly.io/docs/reference/regions/).

### First deploy

```bash
cd services/api
fly auth login
fly apps create citycrawl-api            # or: fly launch --no-deploy (reuses fly.toml)
fly config validate

# Set secrets (never committed). Repeat per environment.
fly secrets set \
  SUPABASE_URL=https://<ref>.supabase.co \
  SUPABASE_ANON_KEY=... \
  ANTHROPIC_API_KEY=... \
  ANTHROPIC_MODEL=claude-haiku-4-5-20251001 \
  OPERATOR_API_KEY=... \
  ALLOWED_ORIGINS=https://<frontend-host> \
  STORAGE_BACKEND=r2 \
  R2_S3_ENDPOINT=https://<account_id>.r2.cloudflarestorage.com \
  R2_ACCESS_KEY=... R2_SECRET=... EXTERNAL_DATA_BUCKET=external-data \
  DB_URL=postgresql://...

fly deploy
fly status
curl -s https://citycrawl-api.fly.dev/health/live
```

### Secret rotation

```bash
fly secrets set ANTHROPIC_API_KEY=<new>      # triggers a rolling restart
fly secrets unset <NAME>                      # remove a secret
```

### Logs

```bash
fly logs                  # live structured JSON logs (route, status, elapsed, requestId)
```
Logs never contain JWTs, operator/provider keys, DB URLs, R2 credentials, or prompt content.

### Rollback

```bash
fly releases                       # list releases
fly deploy --image <prior-image>   # or: fly releases rollback <version>
```

### Scaling / keeping warm for a demo

```bash
fly scale count 1                       # one Machine
fly scale show
# Keep it from auto-stopping during a live demo:
fly machine update <id> --metadata fly_min_machines_running=1   # or edit min_machines_running in fly.toml + deploy
```

### Temporary resize (large dataset / future video experiments)

```bash
fly scale memory 2048      # bump to 2 GB just for the experiment
# ... run the heavy refresh ...
fly scale memory 1024      # resize back to 1 GB immediately afterwards
```

### Autostop / cost control

`auto_stop_machines = "stop"`, `auto_start_machines = true`, `min_machines_running = 0` mean
the Machine stops when idle and starts on the next request (a brief cold start). Leave these as
default outside demos so an idle API costs only stopped-rootfs charges.

### Teardown after the event

```bash
fly scale count 0          # stop serving
fly apps destroy citycrawl-api    # remove app, Machines, and release history
```
Durable data is unaffected — it lives in Supabase and R2, not on Fly.
