# External-Data Extraction Pipeline (CDMX) — Design

**Date:** 2026-06-20
**Status:** Approved (design) — pending implementation
**Component:** Priority Engine input — ingestion of external geolocated risk signals (README §4)
**Scope:** **Mexico City (CDMX) only.** Monterrey / Nuevo León are explicitly out of scope for this iteration.

Builds on the research in
[`docs/research/external-risk-datasets.md`](../../research/external-risk-datasets.md) and
[`docs/research/external-data-followup.md`](../../research/external-data-followup.md).

---

## 1. Scope

Define and build a **production-ready pipeline that extracts up-to-date, point-granularity
(lat/long) urban-risk signals for CDMX** and lands them for the Priority Engine to consume.

In scope:

- **Batch open-portal point datasets** (CKAN `datos.cdmx.gob.mx`): crime, crashes,
  citizen reports, water/flooding, emergencies.
- **Geocoded tier** — address-level open data that has no lat/long but is *fresher*
  (`infracciones`, Sep 2025) plus **news / nota-roja → LLM geocoding** (live).

Explicitly **out of scope** (decided with the user):

- Real-time partner feeds (Waze for Cities), GDELT, ECOBICI GBFS, social-media scraping.
- A fully-normalized relational model for the signals. The pipeline lands **raw + staging**;
  a *thin optional* PostGIS serving table is the only DB write (see §6.4).
- These are **external risk signals**, distinct from `observations` (our own detected
  infrastructure issues, see the observation-contract spec). They share neither schema
  nor table; the Priority Engine joins them spatially.

**Hard requirement (unchanged):** per-record geolocation. A source qualifies if it has
lat/long *or* an address precise enough to geocode to a point.

## 2. Source catalog (live-verified 2026-06-20)

Verified directly against the CKAN API today. Dates are **actual data coverage**, not
portal timestamps. Exact lat/long column names and download handles are locked for the build.

### 2.1 Tier P — direct point (lat/long per record)

| `source_id` | CKAN slug | Signal | Lat/long cols | Freshest data | Cadence |
|---|---|---|---|---|---|
| `fgj_carpetas` | `carpetas-de-investigacion-fgj-de-la-ciudad-de-mexico` | crime | `latitud`,`longitud` | **2025-01** | monthly snapshots (see §5.2) |
| `fgj_victimas` | `victimas-en-carpetas-de-investigacion-fgj` | crime victims | `latitud`,`longitud` | 2024 | annual-ish |
| `ssc_hechos_transito` | `hechos-de-transito-registrados-por-la-ssc-2024-serie-de-datos-ampliada-no-comparativa` | crashes | `latitud`,`longitud` | 2024 | annual batch |
| `c5_incidentes_viales` | `incidentes-viales-c5` | traffic incidents | lat/long | 2024-02 (stalled) | historical prior |
| `locatel_0311` | `0311` | citizen reports (baches/agua) | `latitud`,`longitud` | 2024 (stalled) | historical prior |
| `sacmex_reportes_agua` | `reportes-de-agua` | water / flooding (`encharcamientos`) | `latitud`,`longitud` | 2024 (stalled) | historical prior |
| `c5_911` | `llamadas-numero-de-atencion-a-emergencias-911` | emergency calls | lat/long (**block centroid**) | 2022-H1 (discontinued) | historical prior |
| `ruse_emergencias` | `registro-unico-de-situaciones-de-emergencia` | civil-protection / flood | point geom (SHP/CSV) | 2020 (discontinued) | historical prior |

### 2.2 Tier G — geocoded (no lat/long; address or free text → point)

| `source_id` | Source | Signal | Freshest data | Geo input |
|---|---|---|---|---|
| `infracciones_parq` | `infracciones-al-reglamento-de-transito-de-la-ciudad-de-mexico` | traffic violations (officer) | **Q3 2025** | `en_la_calle`,`entre_calle`,`y_calle`,`colonia`,`alcaldia` |
| `infracciones_ee` | `…-equipos-electronicos` | camera/photo violations | **Q3 2025** | same address fields |
| `news_nota_roja` | RSS/sitemaps of CDMX outlets | crashes/crime/incidents | **live / daily** | free-text location → LLM extract + geocode |

**Recency reality to design around:** the freshest *direct-point* batch is FGJ crime
(through Jan 2025); everything else point-level is 2024 or older. The only **fresher than
2024** signals are the geocoded tier — `infracciones` (Sep 2025) and `news` (live). The
pipeline must therefore treat the geocoded tier as first-class, not an afterthought.

### 2.3 Rejected

`socavones-en-las-alcaldias-en-la-cdmx` (alcaldía-aggregated counts, no points);
`atlas-de-riesgo-*` (AGEB/grid hazard surfaces, not incident points); air-quality
networks (RAMA/REDMET/REDMA — station context, not risk incidents).

## 3. Architecture

**Registry-driven medallion-lite on object storage.** A declarative source registry feeds
thin per-kind adapters that write a **raw zone** (exact bytes + manifest) and a **staging
zone** (one canonical point-event schema as partitioned Parquet). A scheduler-agnostic CLI
runs sources on per-source cadence. Object storage and the optional serving DB are Supabase.

```
registry/sources.yaml
        │  (one declarative entry per source — new source = config, not code)
        ▼
   adapter.fetch()  ── ckan_csv | news_geocode ──┐
        │ exact source bytes                      │
        ▼                                         │
   RAW zone  (Supabase Storage)                   │  manifest.json
   raw/<source_id>/<fetch_ts>/<file>              │  (url, sha256, rows, license, fetched_at)
        │                                         │
        ▼  normalize() → canonical record         │
   STAGING zone (Supabase Storage)  ◀─────────────┘
   staging/<source_id>/event_date=YYYY-MM-DD/part.parquet
        │
        ├──────────────► Priority Engine reads Parquet (source of truth)
        ▼  (optional, thin)
   external_signals  (Supabase Postgres + PostGIS)  ── queryable serving projection
```

**Stack:** Python 3.11 · `httpx` (fetch) · `pyarrow`/`pandas` (normalize→Parquet) ·
`fsspec`+`s3fs` (storage abstraction; local FS in dev, Supabase Storage in prod) ·
`pydantic` (config + schema validation) · `typer` (CLI) · `psycopg` (serving loader) ·
Claude (news extraction + address geocoding fallback) · `pytest`.

**Why this shape:** matches the chosen "raw + staging only" sink; runs identically on a
laptop (local FS) and in cloud (Supabase S3); adding a source is a registry entry, echoing
the observation-contract's "a new type is a row, not a migration" principle.

## 4. Components

### 4.1 Source registry (`registry/sources.yaml`)
One entry per `source_id`. Declarative fields:
`kind` (`ckan_csv`|`news_geocode`), `enabled`, `ckan_slug` *or* `feeds[]`, `resource_match`
(regex to pick the right CSV resources), `schedule` (cron-ish hint), `tier` (`P`|`G`),
`event_type`, `column_map` (native→canonical), `attribute_cols[]`, `geom_quality`,
`bbox_filter` (default CDMX), `license`. The registry **is** the §2 catalog, machine-readable.

### 4.2 Adapter: `ckan_csv`
1. `package_show(slug)` → list resources; select by `resource_match`.
2. **FGJ special-case:** also probe the monthly archive pattern
   `…/FGJ/carpetas/carpetasFGJ_acumulado_YYYY_MM.csv` newest-first; use the freshest that
   resolves, else the CKAN-linked URL (§5.2).
3. Download with `httpx` (streaming), compute `sha256`, write raw + manifest.
4. **Skip-if-unchanged:** compare `sha256` and CKAN `last_modified` against per-source state.

### 4.3 Adapter: `news_geocode`
1. Pull configured **RSS/sitemap** feeds (RSS-first; never blind-scrape — respect
   `robots.txt`). Candidate CDMX outlets: El Universal *Metrópoli*, La Jornada *Capital*,
   Milenio CDMX, Excélsior *Comunidad*, Infobae México, La Prensa (OEM nota roja). Exact
   feed URLs validated at build time; each is a registry `feeds[]` entry.
2. Filter to incident items (keyword + LLM classify): crash / crime / flooding / collapse.
3. **LLM extract** `{event_type, location_text, occurred_at}` from title+summary.
4. **Geocode** `location_text` → point (Nominatim primary; LLM fallback). Attach
   `geocode_confidence`; intersections/named cross-streets score high, vague areas low.
5. Land raw (article id, link, extracted JSON) + emit staged points. Store **only extracted
   facts + the source link**, never full article reproductions (§7).

### 4.4 Normalizer (`core/normalize.py`)
Maps each source's rows to the canonical record (§5.1) via `column_map`; applies the CDMX
bbox filter; stamps `geom_quality`; writes Parquet partitioned by `source_id` + `event_date`.

### 4.5 CLI (`cli.py`)
`ingest run <source_id>` · `ingest run --all` · `ingest run --tier G` · `ingest load-db`
(optional serving loader) · `ingest status` (freshness/row counts per source).

## 5. Data model & storage

### 5.1 Canonical staged record (external risk signal)
Distinct from the observation contract. One row per external incident/event.

| Field | Type | Notes |
|---|---|---|
| `signal_id` | text (PK) | deterministic `sha256(source_id + native_id|row_hash)` — idempotent re-runs |
| `source_id` | text | registry id (`fgj_carpetas`, …) |
| `source_dataset` | text | CKAN slug / feed host |
| `event_type` | text | canonical taxonomy: `crime`,`crash`,`citizen_report`,`water_flood`,`emergency`,`violation` |
| `event_subtype` | text | native category (e.g. `delito`, `tipo_incidente`) |
| `lon`,`lat` | double | WGS84 (EPSG:4326) |
| `geom_quality` | text | `point` \| `block_centroid` (911) \| `geocoded` (news, infracciones) |
| `occurred_at` | timestamptz | event time (nullable) |
| `reported_at` | timestamptz | report/registration time (nullable) |
| `event_date` | date | partition key (from `occurred_at`/`reported_at`) |
| `attributes` | json | native fields preserved verbatim |
| `geocode_confidence` | real | null for Tier P; 0–1 for Tier G |
| `source_url` | text | provenance |
| `license` | text | e.g. CC-BY-4.0 |
| `fetched_at`,`ingested_at` | timestamptz | run provenance |

`geom_quality` is the key downstream lever: the Priority Engine **down-weights**
`block_centroid` and low-confidence `geocoded` points rather than treating all points equally.

### 5.2 Storage layout (Supabase Storage, S3-compatible)
```
<bucket>/raw/<source_id>/<fetch_ts>/<original_filename>
<bucket>/raw/<source_id>/<fetch_ts>/manifest.json
<bucket>/staging/<source_id>/event_date=YYYY-MM-DD/part-*.parquet
<bucket>/_state/<source_id>.json          # last sha256, last_modified, last_run
```
Raw is immutable (exact bytes, audit + replay). Staging is the consumable contract. Access
via `fsspec`/`s3fs` against the Supabase S3 endpoint; identical code uses a local path in dev.

### 5.3 Manifest (per raw fetch)
`{source_id, ckan_slug, resource_id, source_url, sha256, byte_size, row_count, license,
fetched_at, adapter, adapter_version}` — enables freshness reporting and dedup without
re-downloading.

## 6. Production concerns

### 6.1 Idempotency & incrementality
Per-source `_state` file holds last `sha256` + CKAN `last_modified`; an unchanged source is
skipped before download. `signal_id` is deterministic, so re-processing the same rows is a
no-op (no duplicates) and the serving loader uses `INSERT … ON CONFLICT (signal_id) DO UPDATE`.

### 6.2 Resilience
CKAN resource URLs are resolved dynamically per run (survive portal reshuffles). Network
calls retry with backoff. A failing source fails *in isolation*; the run continues and
reports per-source status. Bad rows (unparseable coords) are quarantined, not fatal.

### 6.3 Scheduling
Cadence hints live in the registry; the runner is scheduler-agnostic. Suggested:
batch Tier-P = **monthly** freshness check (data rarely changes); `infracciones` =
**weekly**; `news` = **hourly/daily**. Wire via cron / Supabase scheduled function /
GitHub Actions — the CLI is the single entrypoint.

### 6.4 Optional Supabase Postgres serving loader
`ingest load-db` reads staging Parquet → upserts into `external_signals` (PostGIS):
`geom geography(Point,4326)` via `ST_SetSRID(ST_MakePoint(lon,lat),4326)`, GIST index,
plus `event_type`/`event_date` btree indexes. Files remain source of truth; the table is a
rebuildable projection so the Priority Engine can spatial-join in SQL. **Optional** — the
pipeline never depends on the DB being up.

### 6.5 Config / secrets
Env (`.env`, not committed): `SUPABASE_DB_URL`, `SUPABASE_S3_ENDPOINT`,
`SUPABASE_S3_ACCESS_KEY`, `SUPABASE_S3_SECRET`, `EXTERNAL_DATA_BUCKET`, `ANTHROPIC_API_KEY`,
`NOMINATIM_BASE_URL`. A `STORAGE_BACKEND=local|supabase` switch drives dev vs prod.

## 7. Legal / ToS posture
Open-portal datasets are **CC-BY-4.0** — attribute the source. For news: pull **RSS/sitemaps
only**, honor `robots.txt`, rate-limit politely, and persist **only extracted facts + the
link** (event type, location, time, URL) — not article text or layout. Facts aren't
copyrightable; reproductions are. Any source whose ToS forbids automated access is excluded.

## 8. Repository placement
Self-contained package `external-data/` (monorepo, per README principles): `registry/`,
`adapters/`, `core/`, `schema.py`, `cli.py`, `tests/`, `pyproject.toml`, `.env.example`,
`README.md`. The §5.1 canonical record is the **shared contract** the Priority Engine
depends on; it lives in `schema.py` and is documented here.

## 9. Testing
- **Adapter units** with recorded CKAN/RSS fixtures (no live network in CI).
- **Normalization golden tests** per source (native sample → expected canonical rows).
- **Bbox / geom_quality** edge cases (out-of-CDMX SSC coords dropped; 911 → `block_centroid`).
- **Idempotency**: re-run yields zero new `signal_id`s; loader upsert is stable.
- **News geocoding**: fixture articles → expected points + confidence banding.
- **Live smoke** (`-m live`, opt-in): one small real fetch per source kind.

## 10. Decisions & rejected alternatives
| Decision | Why | Rejected |
|---|---|---|
| Registry-driven adapters | New source = config; mirrors observation-contract ethos | Hardcoded per-source scripts |
| Raw + staging on object storage | Matches user's chosen sink; replayable; cloud/local parity | Normalized DB as primary sink |
| Canonical record separate from `observations` | External signals are inputs, not detections | Reusing the observation schema |
| `geom_quality` flag | Lets Priority Engine down-weight coarse/geocoded points | Treating all points as equal |
| Geocoded tier first-class | Only path to fresher-than-2024 data (infracciones, news) | Batch-only (would ship ~18-mo-stale data) |
| FGJ monthly-archive probe + CKAN fallback | Auto-picks up fresher FGJ than CKAN links | Trusting the CKAN resource URL alone |
| Thin optional PostGIS loader | Supabase Postgres is in the stack; SQL spatial joins for free | Either no DB, or DB as mandatory sink |
| Medallion-lite over Airflow/Dagster | ~10 sources, hackathon clock | Heavy orchestrator |

## 11. Open items
- Validate exact **RSS/sitemap URLs** per news outlet at build time (registry entries).
- Confirm **Supabase Storage S3** credentials/endpoint format for the target project.
- `infracciones` geocoding quality on `en_la_calle`+`entre_calle`+`y_calle` intersections
  (expected high — they are named cross-streets).
- Whether the FGJ monthly-archive pattern yields anything newer than 2025-01 (probe in prod;
  the archive subdomain is not routable from the dev sandbox).
- Per-source `event_type` taxonomy mapping table (finalize during build).
