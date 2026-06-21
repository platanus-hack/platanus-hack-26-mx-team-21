# external-data — CDMX external-signal ROI pipeline

Extracts CDMX point/geocodable risk signals → clusters them into **granular, risk-semantic
ROI polygons** → persists with a current/superseded lifecycle for the Priority Engine and
Latent Issue Detection.

- **Design:** `docs/superpowers/specs/2026-06-20-external-data-pipeline-design.md`
- **Plan:** `docs/superpowers/plans/2026-06-20-external-data-roi-pipeline.md`
- **DB tables (priority schema):** `external_signals`, `roi_runs`, `rois`, view `current_rois`
  (migrations `supabase/migrations/0101–0103`).

## Setup
```bash
cd services/external-data
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest                       # 28 tests
```

## Run (local, no DB)
```bash
external-data status                                   # list sources + dimensions
external-data extract --source ssc_hechos_transito     # → .data/raw + .data/staging
external-data roi-compute --dimension crash            # → .data/staging/rois/current.geojson
```

## Run (Cloudflare R2 — production / Container)
Object storage is on Cloudflare R2 (`STORAGE_BACKEND=r2`). In production the pipeline
runs as the container image (`Dockerfile`) invoked by the Cron worker (`cron/`); see
`docs/runbooks/r2-cutover.md` and `supabase/STORAGE.md`. Apply migrations `0101–0103`
(Supabase MCP or CLI) for the DB side, then:
```bash
export STORAGE_BACKEND=r2 DB_URL=... \
       R2_S3_ENDPOINT=https://<account_id>.r2.cloudflarestorage.com \
       R2_ACCESS_KEY=... R2_SECRET=...
external-data extract --all      # raw+staging → R2 external-data bucket
external-data load-db            # staged signals → priority.external_signals
external-data roi-compute --all  # → priority.roi_runs + priority.rois
```
> `STORAGE_BACKEND=supabase` (with `SUPABASE_S3_*`) is retained only as the migration
> rollback path until Supabase Storage is decommissioned (`0211`).

## Sources (registry/sources.yaml)
9 sources across 5 toggleable risk dimensions: `crash` (SSC, C5, news), `crime` (FGJ
carpetas+víctimas), `flooding` (SACMEX, 0311-agua), `road_surface` (0311-baches),
`violation` (infracciones). New source = a YAML entry.

## Status / not-yet-done
- Built + locally validated on live SSC 2024 (30,652 signals → 870 ROIs, median ~3,200 m²).
- Remote `joixzhdpnxqhnuscxsoy`: migrations applied; **representative sample loaded** (12
  signals, 5 crash ROIs). Full 30k multi-source bulk load needs a direct Postgres connection
  (the MCP carries SQL inline).
- Column names verified live for **SSC only**; FGJ/C5/0311/SACMEX/infracciones headers must
  be confirmed against each live CSV before their first real extract.
- `external-data` bucket created but empty (no raw/staging uploaded yet).

## Container deployment (R2 + Cron)

Deploy the containerized pipeline to Cloudflare Containers with a daily Cron trigger:

```bash
# From services/external-data/cron/
npx wrangler deploy

# Set R2 + DB credentials (one-time):
npx wrangler secret put R2_S3_ENDPOINT
npx wrangler secret put R2_ACCESS_KEY
npx wrangler secret put R2_SECRET
npx wrangler secret put DB_URL
npx wrangler secret put EXTERNAL_DATA_BUCKET  # e.g. "external-data"
```

The Dockerfile defines the image: `external-data:r2` with `STORAGE_BACKEND=r2`, entrypoint `external-data` CLI.
The `wrangler.toml` in `cron/` configures the Cron Worker (`0 6 * * *` = daily 06:00 UTC) and Durable Object container.

On each cron trigger, the container runs: `external-data extract && external-data roi-compute --export && external-data load`.
All raw/staging/ROI output writes to R2 via the s3fs backend.
