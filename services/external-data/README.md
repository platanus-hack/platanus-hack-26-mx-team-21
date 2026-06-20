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

## Run (Supabase)
Apply migrations `0101–0103` (Supabase MCP or CLI), then:
```bash
export STORAGE_BACKEND=supabase DB_URL=... \
       SUPABASE_S3_ENDPOINT=... SUPABASE_S3_ACCESS_KEY=... SUPABASE_S3_SECRET=...
external-data extract --all      # raw+staging → external-data bucket
external-data load-db            # staged signals → priority.external_signals
external-data roi-compute --all  # → priority.roi_runs + priority.rois
```

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
