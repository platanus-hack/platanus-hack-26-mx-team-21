# External-Signal ROI Pipeline (CDMX) — Design

**Date:** 2026-06-20
**Status:** Approved (design) — pending implementation
**Component:** Priority Engine / Latent Issue Detection input (README §4–5)
**Scope:** **Mexico City (CDMX) only.** Monterrey / Nuevo León are out of scope.

Builds on the research in
[`docs/research/external-risk-datasets.md`](../../research/external-risk-datasets.md) and
[`docs/research/external-data-followup.md`](../../research/external-data-followup.md).

---

## 1. Goal & scope

The **product of this pipeline is a set of granular ROI polygons with risk semantics**, not
raw datasets. External point signals are an *intermediate*: they are extracted, normalized,
then aggregated into **Regions of Interest (ROIs)** — small zones that imply a mobility (or,
optionally, safety) conflict and therefore **motivate a visual inspection** whose job is to
find the *root cause* (missing lighting/signage, bad geometry, pothole, blocked drainage…).

**Strict requirements (from the user):**
1. Construct **granular ROI polygons** carrying **risk semantics**.
2. Persist ROIs in a **database**, each ROI linking **(a) object references** back to the
   contributing source data and **(b) a generated issue description** — the context handed to
   the VLM/analysis step (README §5).
3. ROIs are **time-sensitive**: there is a **current** set, and a recompute **supersedes** the
   prior current ROIs (logical supersession + history, mirroring the observation contract).
4. **If a source doesn't help draw these ROIs, scrap it.**

In scope: extraction of contributing CDMX point/geocodable signals → per-dimension ROI
computation → ROI persistence with supersession.

Out of scope: Waze/GDELT/GBFS/social feeds; the VLM inspection itself (consumes ROIs);
the observation contract (ROIs are inputs to latent detection, a separate entity).

ROIs are tagged by **risk dimension** so the application can include/exclude any dimension
(notably crime) at query time — the app decides what to use.

## 2. Source catalog → risk dimensions (live-verified 2026-06-20)

Each kept source feeds exactly one **risk dimension**. Sources that don't contribute to
granular conflict ROIs are dropped.

| `source_id` | CKAN slug / origin | Risk dimension | Geo | Freshest data |
|---|---|---|---|---|
| `ssc_hechos_transito` | `hechos-de-transito-registrados-por-la-ssc-2024-…` | `crash` | point `latitud/longitud` | 2024 |
| `c5_incidentes_viales` | `incidentes-viales-c5` | `crash` | point | 2024-02 (stalled, density prior) |
| `accidentes_ciclistas` | `puntos-de-accidentes-de-ciclistas` (SHP) | `crash` | point | 2023 (vulnerable-user prior) |
| `accidentes_peatones` | `puntos-de-accidentes-a-peatones` (SHP) | `crash` | point | 2023 (vulnerable-user prior) |
| `news_nota_roja` | RSS/sitemaps, CDMX outlets | `crash` | geocoded (LLM) | **live** |
| `infracciones_ee` | `…-equipos-electronicos` | `violation` | geocoded (address) | **Q3 2025** |
| `infracciones_parq` | `infracciones-al-reglamento-de-transito-…` (moving-violation subset) | `violation` | geocoded | **Q3 2025** |
| `sacmex_encharcamientos` | `reportes-de-agua` (`encharcamientos` subset) | `flooding` | point | 2024 |
| `locatel_0311_agua` | `0311` (water subset) | `flooding` | point | 2024 |
| `locatel_0311_baches` | `0311` (`baches`/road-surface subset) | `road_surface` | point | 2024 |
| `fgj_carpetas` | `carpetas-de-investigacion-fgj-…` | `crime` | point | **2025-01** |
| `fgj_victimas` | `victimas-en-carpetas-de-investigacion-fgj` | `crime` | point | 2024 |

**Dropped (don't serve granular ROIs):** `c5_911` (lat/long is **block-centroid** → fails the
granularity requirement; discontinued 2022); `ruse_emergencias` (2020, flooding already
covered by SACMEX); `socavones` (alcaldía-aggregated); `atlas-de-riesgo-*` (AGEB/grid surfaces).

**Recency note:** the only signals fresher than 2024 are `infracciones` (Q3 2025), `news`
(live), and FGJ crime (Jan 2025). The pipeline handles staleness two ways: a **recency-decay**
weight in the risk score (§4) and **ROI supersession** on recompute (§6).

**FGJ freshness lever:** FGJ publishes monthly snapshots at
`https://archivo.datos.cdmx.gob.mx/FGJ/carpetas/carpetasFGJ_acumulado_YYYY_MM.csv`; the
adapter probes newest-first and falls back to the CKAN-linked URL, auto-picking fresher data.

## 3. Architecture — three stages

```
STAGE 1  EXTRACT      adapters → raw + staging signals in Supabase Storage  ("objects")
                      → load normalized rows into external_signals (PostGIS)
STAGE 2  COMPUTE ROIs per risk dimension: cluster weighted points (ST_ClusterDBSCAN)
                      → polygon (concave hull + buffer) → risk semantics + description
STAGE 3  PERSIST      insert rois (current), supersede prior current ROIs for those
                      dimensions; keep history → current_rois view, time-travel
```

**Stack:** Python 3.11 · `httpx` · `pyarrow`/`pandas` · `fsspec`+`s3fs` (Supabase Storage;
local FS in dev) · `pydantic` · `typer` (CLI) · `psycopg` (PostGIS) · Claude (news extraction,
ROI description, geocode fallback) · `pytest`.

**Storage decision (mine to make):**
- **Supabase Storage** — raw zone (exact bytes + manifest) + staging Parquet. These are the
  *objects* ROIs reference.
- **Supabase Postgres + PostGIS** — `external_signals` (clustering input, rebuildable),
  `roi_runs`, `rois` (the product), `current_rois` view. This is the strict-requirement DB.

## 4. Risk dimensions & weighting

Dimensions (configurable in the registry): `crash`, `violation`, `flooding`, `road_surface`,
`crime`. Each signal carries a weight used by clustering and scoring:

```
weight = severity(event_type) × recency_decay(occurred_at) × geom_quality_factor
recency_decay = exp(-ln2 × age_days / half_life_days)      # half_life default 365d
geom_quality_factor:  point 1.0 · geocoded 0.7 · block_centroid 0.5
```

`severity` is a per-event-type table (e.g. fatal crash > injury crash > property crash; flood
> isolated water report). All weights live in config so they're tunable as real data lands.

## 5. ROI computation

**Method (recommended): native PostGIS `ST_ClusterDBSCAN`.** Deterministic, granular,
explainable; no extra extension needed. Per dimension, over the current signal set:

1. Project signal points to metric CRS **EPSG:32614** (UTM 14N, CDMX) so `eps` is in meters.
2. `ST_ClusterDBSCAN(geom, eps := ~100m, minpoints := ~5)` (params per dimension, in config).
3. Per cluster build the polygon: `ST_ConcaveHull(ST_Collect(points), 0.8)` then a small
   `ST_Buffer` (~15m) to give the inspection a footprint; store back as `geography(Polygon,4326)`.
4. Aggregate **risk semantics**: `risk_score = Σ weight`, `signal_count`, `risk_breakdown`
   (counts per event_type + co-located other-dimension counts), `dominant_type`,
   `occurred_from/to`, `recency_score`.
5. Generate **`description`** — a concise inspection brief for the VLM: what's clustered, how
   much, how recent, nearest street/colonia, and **candidate root causes by dimension**
   (crash → signage/geometry/lighting/surface; flooding → drainage/grade; violation →
   signal timing/signage; road_surface → pavement; crime → lighting/visibility). Templated,
   LLM-polished.
6. Record **object references**: `contributing_signal_ids[]` and `source_object_refs[]`
   (Supabase Storage handles of the underlying raw/staging objects).

Alternative considered: H3 hexbin (res 9–10) — fixed grid, needs the `h3` extension; kept as a
fallback if a grid is preferred over density clusters.

**Granularity:** `eps≈100m` + concave hulls keep ROIs intersection/block-scale, not
neighborhood blobs — satisfying the "granular ROIs" requirement; tunable per dimension.

## 6. Data model & lifecycle

```sql
CREATE EXTENSION IF NOT EXISTS postgis;

-- Normalized signals: clustering input, rebuildable from staging Parquet.
CREATE TABLE external_signals (
    signal_id          TEXT PRIMARY KEY,           -- deterministic hash (idempotent)
    source_id          TEXT NOT NULL,
    risk_dimension     TEXT NOT NULL,              -- crash|violation|flooding|road_surface|crime
    event_type         TEXT NOT NULL,
    event_subtype      TEXT,
    geom               geography(Point,4326) NOT NULL,
    geom_quality       TEXT NOT NULL,              -- point|geocoded|block_centroid
    occurred_at        TIMESTAMPTZ,
    reported_at        TIMESTAMPTZ,
    severity_weight    REAL NOT NULL DEFAULT 1,
    geocode_confidence REAL,
    attributes         JSONB NOT NULL DEFAULT '{}',
    source_object_ref  TEXT,                        -- storage path to the raw/staging object
    source_url         TEXT,
    license            TEXT,
    fetched_at         TIMESTAMPTZ,
    ingested_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX external_signals_gix    ON external_signals USING GIST (geom);
CREATE INDEX external_signals_dim_ix ON external_signals (risk_dimension);

-- One generation per recompute.
CREATE TABLE roi_runs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dimensions    TEXT[] NOT NULL,                 -- dims recomputed in this run
    params        JSONB  NOT NULL,                 -- eps, minpoints, weights, half_life
    signal_window TSTZRANGE,                       -- signal time window considered
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at  TIMESTAMPTZ,
    roi_count     INT
);

-- The product. Logical supersession (never hard delete) → history + time-travel.
CREATE TABLE rois (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id           UUID NOT NULL REFERENCES roi_runs(id),
    risk_dimension   TEXT NOT NULL,                -- app-toggleable layer
    geom             geography(Polygon,4326) NOT NULL,
    centroid         geography(Point,4326)   NOT NULL,
    area_m2          REAL NOT NULL,
    risk_score       REAL NOT NULL,
    signal_count     INT  NOT NULL,
    dominant_type    TEXT NOT NULL,
    risk_breakdown   JSONB NOT NULL,               -- per type + co-located dimensions
    occurred_from    TIMESTAMPTZ,
    occurred_to      TIMESTAMPTZ,
    recency_score    REAL,
    description      TEXT NOT NULL,                 -- generated VLM/analysis context
    contributing_signal_ids TEXT[] NOT NULL,        -- object references (signals)
    source_object_refs      TEXT[] NOT NULL,        -- object references (storage handles)
    valid_from       TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to         TIMESTAMPTZ,                   -- set on supersession (NULL = current)
    superseded_by_run_id UUID REFERENCES roi_runs(id),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX rois_current_gix ON rois USING GIST (geom) WHERE valid_to IS NULL;
CREATE INDEX rois_dim_ix      ON rois (risk_dimension)  WHERE valid_to IS NULL;

CREATE VIEW current_rois AS SELECT * FROM rois WHERE valid_to IS NULL;
```

**Supersession (per recompute, one transaction):** insert the new run's ROIs, then retire the
prior current ROIs **for the recomputed dimensions only** — so a single dimension can refresh
without disturbing the others:

```sql
UPDATE rois
   SET valid_to = now(), superseded_by_run_id = :new_run
 WHERE valid_to IS NULL
   AND run_id <> :new_run
   AND risk_dimension = ANY(:recomputed_dims);
```

Time-travel ("ROIs as of date X") falls out of `valid_from/valid_to`, same as observations.

## 7. Components
- `registry/sources.yaml` — the §2 catalog as config: source → dimension, subset filter,
  column map, severity, geom_quality, schedule, license.
- `adapters/ckan_csv.py`, `adapters/news_geocode.py` — extract → raw + staging (as §previous
  design; FGJ archive probe; RSS-first, ToS-respectful news).
- `core/normalize.py` — staging → `external_signals` (bbox filter, weight, geom_quality).
- `roi/engine.py` — DBSCAN clustering, polygon build, risk semantics, description generation.
- `roi/persist.py` — `roi_runs`/`rois` insert + supersession transaction.
- `db/migrations/*.sql` — the §6 DDL.
- `cli.py` — `extract` (`--source|--all`), `roi compute` (`--dimension|--all`, `--eps`,
  `--minpts`, `--half-life`), `roi current [--dimension]`, `status`.

## 8. Production concerns
- **Idempotency:** deterministic `signal_id`; per-source state (sha256 + CKAN `last_modified`)
  skips unchanged extracts; ROI recompute is a clean generation (supersede, never duplicate).
- **Scheduling:** registry cadence — `news` hourly/daily, `infracciones` weekly, batch-`crash`
  monthly; ROI recompute triggered after any dimension's signals change. Scheduler-agnostic CLI.
- **Resilience:** per-source isolation; retries w/ backoff; bad coords quarantined; out-of-CDMX
  bbox drop (SSC has stray coords).
- **Secrets (env):** `SUPABASE_DB_URL`, `SUPABASE_S3_ENDPOINT`, `SUPABASE_S3_ACCESS_KEY/SECRET`,
  `EXTERNAL_DATA_BUCKET`, `ANTHROPIC_API_KEY`, `NOMINATIM_BASE_URL`; `STORAGE_BACKEND=local|supabase`.
- **ToS:** open data is CC-BY-4.0 (attribute); news = RSS/sitemap + robots.txt, store extracted
  facts + link only.

## 9. Repository placement
Self-contained monorepo package `external-data/`: `registry/`, `adapters/`, `core/`, `roi/`,
`db/`, `schema.py`, `cli.py`, `tests/`, `pyproject.toml`, `.env.example`, `README.md`. The
`rois` schema (§6) and `external_signals` are the **shared contracts** the Priority Engine and
Latent Issue Detection depend on.

## 10. Testing
- Adapter units with recorded CKAN/RSS fixtures (no live network in CI).
- Normalization golden tests (native sample → `external_signals` rows; bbox/geom_quality edges).
- **ROI engine**: synthetic point clusters → expected polygons, risk_score, breakdown;
  granularity (eps) behavior; singletons excluded (minpoints).
- **Supersession**: recompute a dimension → old ROIs get `valid_to`, `current_rois` shows only
  new; other dimensions untouched; time-travel query reconstructs a past generation.
- **Idempotency**: re-extract = no new signals; re-run ROI = clean new generation.
- Live smoke (`-m live`, opt-in): one real fetch + one real ROI compute end-to-end.

## 11. Decisions & rejected alternatives
| Decision | Why | Rejected |
|---|---|---|
| ROIs are the product; signals intermediate | Matches the stated end goal (inspection triggers) | Landing signals as the deliverable |
| Per-dimension, tagged ROIs | App toggles dimensions (incl. crime) at query time | One blended ROI set |
| Keep crime as its own dimension | User: "don't drop it; app decides usage" | Dropping the freshest direct-point source |
| Drop C5-911 & RUSE | Block-centroid / 2020 — fail "granular" | Keeping coarse/old points |
| `ST_ClusterDBSCAN` in PostGIS | Native, deterministic, granular, explainable | H3 (needs extension); KDE (fuzzy edges) |
| Recency-decay weight + supersession | Two complementary time-sensitivity levers | Hard cutoff by date only |
| Logical supersession by run/dimension | "Current, superseded on recompute" + history/time-travel | Hard delete / overwrite |
| ROI stores object refs + description | The required analysis-context linkage | Geometry-only ROIs |
| Storage: Supabase (Storage objects + PostGIS ROIs) | Uses the chosen stack; ROIs need a spatial DB | Files-only (can't satisfy "in a database") |

## 12. Integration with the application data model (parallel agent)

A parallel agent is building the application's full Supabase data model on this branch
(`docs/.../application-data-model-*`): 5 ownership schemas — `platform`, `vision`,
`priority`, `geo`, `analysis` — with PostGIS in `extensions`, plus `pgmq`/`pg_cron`/`pg_net`,
applied to the **remote project `joixzhdpnxqhnuscxsoy` via the Supabase MCP** (migrations
`0001`–`0014`). **That model has no external-signal or ROI concept — this pipeline adds it.**
This pipeline builds *on top of* that schema; it does not create or modify their tables.

- **Schema placement (no new schema needed):** external-signal + ROI tables go in the
  existing **`priority`** schema — `priority.external_signals`, `priority.roi_runs`,
  `priority.rois`, view `priority.current_rois`. The README couples external signals to the
  Priority Engine and ROIs to latent detection, so `priority` is the right home and **no
  "missing schema" wait is required.**
- **Storage:** add one private bucket **`external-data`** (raw + staging objects), following
  the parallel agent's private-bucket + membership-scoped-policy pattern.
- **Conventions matched (from their migrations):** `id uuid primary key default
  gen_random_uuid()`; `text` + `check (... in (...))` enums; `timestamptz` with
  `default now()`; PostGIS `geography`/`geometry` + GIST indexes; security-definer functions
  set `search_path`; append-only / set-once triggers for immutable facts.
- **Tooling constraint (important):** this agent has **no Supabase MCP and no local
  CLI/Docker**. Migrations and SQL assertion tests are therefore **authored as files** under
  `supabase/migrations/` (numbered **`0101+`** to avoid the reserved `0003`–`0014` band) and
  `supabase/tests/`, to be **applied + verified by the DB-capable agent** via the Supabase
  MCP. The Python pipeline runs independently with a **local-FS storage backend in dev** and
  switches to Supabase Storage/Postgres once the migrations are applied.
- **Writes:** the pipeline writes via the **service role** (bypasses RLS). Tenant-scoped
  *read* policy for ROIs (geo-clip like observations) is deferred to coordinate with the DB
  agent; ROIs are global risk data, clipped per tenant at read time downstream.

## 13. Open items
- Validate per-outlet **RSS/sitemap URLs** (registry entries) at build time.
- Confirm Supabase **S3 endpoint/credentials** for the target project; whether `h3` ext is
  available if we ever want the grid fallback.
- Per-dimension `eps`/`minpoints` and the `severity`/`half_life` tables — tune on real data.
- `infracciones`/`0311` subset filters (moving violations; baches vs agua) — finalize at build.
- ROI ↔ recording linkage (for the VLM step) is consumed downstream by Latent Issue Detection;
  this pipeline only guarantees ROI geometry + description + object refs.
