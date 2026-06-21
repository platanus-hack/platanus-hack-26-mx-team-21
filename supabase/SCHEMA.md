# Database Schema Reference (as-built)

**Last verified:** 2026-06-20 against `supabase/migrations/0001`–`0011` + `0101`–`0103` + `0210`–`0211`.

This document describes the **database as it is actually built by the committed
migrations** — every schema, table, column, key constraint, index, function,
queue, cron job, and storage bucket that `supabase db reset` produces. It is the
bridge between the design specs (what the model *means*) and the SQL (what is
*deployed*).

## Source-of-truth chain

The meaning of every entity is owned upstream; this file only records the
physical realization and any drift.

| Layer | Document | Owns |
|---|---|---|
| Logical model | [`docs/superpowers/specs/2026-06-20-application-data-model-design.md`](../docs/superpowers/specs/2026-06-20-application-data-model-design.md) | Entities, fields, lifecycle rules, invariants — **controls meaning** |
| Physical design | [`docs/superpowers/specs/2026-06-20-application-data-model-supabase-implementation-design.md`](../docs/superpowers/specs/2026-06-20-application-data-model-supabase-implementation-design.md) | Schemas, ids, RLS, storage, queue, immutability — **controls mechanism** |
| External-data | [`docs/superpowers/specs/2026-06-20-external-data-pipeline-design.md`](../docs/superpowers/specs/2026-06-20-external-data-pipeline-design.md) | `priority.external_signals`, `priority.rois`, `external-data` bucket |
| Implementation plan | [`docs/superpowers/plans/2026-06-20-application-data-model-supabase-implementation.md`](../docs/superpowers/plans/2026-06-20-application-data-model-supabase-implementation.md) | Task-by-task migration build order |
| **As-built DDL** | `supabase/migrations/*.sql` (+ `supabase/tests/*.test.sql`) | The actual deployed schema this file documents |

Where the SQL and the logical prose differ on *meaning*, the logical model wins;
where they differ on *mechanism*, the physical design wins. Drift that already
exists in the migrations is called out under [Notes & drift](#notes--drift).

## How it is built

Everything is infrastructure-as-code under `supabase/`, rebuilt deterministically:

```bash
supabase start
supabase db reset    # applies migrations/ in filename order, then seed.sql
```

Migrations are applied in lexical filename order. The `0001`–`0011` band is the
application data model; the `0101`+ band is the external-data pipeline, numbered
above the reserved core band so the two streams never collide.

## Migration map

| File | Adds |
|---|---|
| `0001_extensions_schemas.sql` | Extensions (`postgis`→`extensions`, `pgmq`, `pg_cron`, `pg_net`); schemas `platform`, `vision`, `priority`, `geo`, `analysis` |
| `0002_platform.sql` | `platform.tenants`, `oidc_subjects`, `tenant_memberships`, `audit_events`; helper fns `current_subject_id()`, `active_tenant_id()`, `is_member()` |
| `0003_vision_catalog.sql` | `vision.sources`, `observation_types`, `observation_attribute_definitions`, `observation_attribute_options`, `sweeps`, `sweep_assessed_types`, `recordings` |
| `0004_observations.sql` | `vision.observations`, `observation_attribute_values`, `observation_thumbnails` |
| `0005_priority.sql` | `priority.priority_models`, `priority_batches`, `priority_batch_items`, `priority_values`, `current_priority_values` |
| `0006_geo.sql` | `geo.geo_editions`, `geo_areas`, `tenant_boundary_versions`, `tenant_boundary_areas`, `observation_geo_bindings` |
| `0007_analysis_definitions_runs.sql` | `analysis.analysis_providers`, `analysis_definitions`, `analysis_definition_versions`, `provider_capability_snapshots`, `analysis_runs`, `run_scope_areas`, `run_scope_geometry`, `run_type_settings` |
| `0008_analysis_frozen_inputs.sql` | `analysis.run_observations`, `run_observation_attributes`, `run_priority_values`, `run_observation_exclusions` |
| `0009_analysis_results.sql` | `vision.vision_outbox_events`, `analysis.analysis_outbox_events`, `analysis_attempts`, `analysis_results`, `result_metrics`, `result_warnings`, `artifacts`, `map_features`, `artifact_observation_refs`, `sequence_items`, `asset_refs` |
| `0010_queues_cron.sql` | `pgmq` queues `analysis_jobs`, `materialization_jobs`, `thumbnail_jobs`; `platform.drain_outbox()`; `pg_cron` job `drain_outbox` (every 10s) |
| `0011_read_model_cache.sql` | `vision.read_model_state` + `bump_data_version()`; `platform.tenant_visible_observations`, `tenant_tile_sets`; fns `rebuild_tenant_visible()`, `can_view_observation()` |
| `0101_priority_external_signals.sql` | `priority.external_signals` |
| `0102_priority_rois.sql` | `priority.roi_runs`, `rois`, view `current_rois` |
| `0103_external_data_storage.sql` | private storage bucket `external-data` (Supabase Storage — **superseded by `0211`**) |
| `0210_r2_access_api.sql` | `public.app_authorize_object(p_bucket, p_path)` — RPC gate for R2 access broker |
| `0211_drop_supabase_storage.sql` | removes Supabase Storage bucket + RLS policies; object storage migrated to Cloudflare R2 |

## Conventions (apply to every table unless noted)

- **PK:** `id uuid primary key default gen_random_uuid()` (join tables use composite PKs).
- **Time:** all timestamps are `timestamptz`; `created_at timestamptz not null default now()`.
- **Enums:** `text` + `check (col in (...))` — never PG `enum` types, to keep the catalog extensible.
- **Money:** `numeric(14,2)`. **INEGI keys:** `text` (preserve leading zeroes).
- **Spatial:** `geography(...,4326)` for real-world point/coverage measurements;
  `geometry(...,4326)` for derived/clipped shapes that PostGIS predicates run against.
- **PostGIS** lives in the `extensions` schema, so functions that call `ST_*` set
  `search_path = extensions, public`.

## Schemas (ownership domains)

| Schema | Owns | Implemented in |
|---|---|---|
| `platform` | Tenants, identities, memberships, audit, cached read model, async drain | `0002`, `0010`, `0011` |
| `vision` | Sources, sweep provenance, type catalog, observations, media, vision outbox, data-version stamp | `0003`, `0004`, `0009`, `0011` |
| `priority` | App: priority models/batches/values. External-data: risk signals + ROIs | `0005`; `0101`, `0102` |
| `geo` | INEGI editions/areas, versioned tenant boundaries, observation bindings | `0006` |
| `analysis` | Providers, definitions, runs, frozen inputs, attempts, results, artifacts, analysis outbox | `0007`, `0008`, `0009` |
| `extensions` | PostGIS (+ pre-installed `pgcrypto`, `uuid-ossp`, `pg_stat_statements`) | `0001` |
| `pgmq`, `cron`, `net` | Owned by their extensions (queues, scheduler, async HTTP) | `0001`, `0010` |

---

## `platform`

### `platform.tenants`
An organization using the application. Tenant identity never appears on sources, sweeps, observations, or priority values — tenancy is geographic (via `geo`).

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `name` | text not null | |
| `status` | text not null `'active'` | check `in ('active','disabled')` |
| `created_at` | timestamptz not null | |

### `platform.oidc_subjects`
Application identity bridged to Supabase Auth. `user_id` links to `auth.users`; `issuer`/`subject` are retained for federated provenance and are unique together.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `user_id` | uuid not null **unique** → `auth.users(id)` `on delete restrict` | the Supabase Auth bridge |
| `issuer` | text | null when Supabase is the issuer |
| `subject` | text | external IdP subject |
| `display_name` | text | |
| `status` | text not null `'active'` | check `in ('active','disabled')` |
| `created_at` | timestamptz not null | |
| | | **unique** `(issuer, subject)` |

### `platform.tenant_memberships`
Associates a subject with a tenant and one baseline role. A subject may belong to many tenants, so tenant context is explicit per request (`app.tenant_id`).

| Column | Type | Notes |
|---|---|---|
| `tenant_id` | uuid → `tenants(id)` `on delete cascade` | PK part |
| `subject_id` | uuid → `oidc_subjects(id)` `on delete cascade` | PK part |
| `role` | text not null | check `in ('viewer','analysis_author')` |
| `created_at` | timestamptz not null | |
| | | **PK** `(tenant_id, subject_id)`; index on `(subject_id)` |

### `platform.audit_events`
Append-only audit trail (append-only enforcement is **pending**, see [Pending](#specced-but-not-yet-implemented-ongoing)).

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `tenant_id` | uuid → `tenants(id)` | nullable |
| `actor_subject_id` | uuid → `oidc_subjects(id)` | nullable |
| `module` | text not null | owning module |
| `action` | text not null | stable action code |
| `target_type` | text | |
| `target_id` | uuid | |
| `occurred_at` | timestamptz not null | |
| `details` | jsonb not null `'{}'` | redacted context |
| | | index on `(tenant_id, occurred_at)` |

### `platform.tenant_visible_observations`  *(cached geo-clip read model)*
The materialized result of clipping the current observation set to a tenant's active boundary, so map reads are an indexed join instead of a per-row spatial scan. Stamped with the `data_version` it was computed at.

| Column | Type | Notes |
|---|---|---|
| `tenant_id` | uuid → `tenants(id)` `on delete cascade` | PK part |
| `boundary_version_id` | uuid → `geo.tenant_boundary_versions(id)` | |
| `observation_id` | uuid → `vision.observations(id)` | PK part |
| `data_version` | bigint not null | from `vision.read_model_state` |
| | | **PK** `(tenant_id, observation_id)`; index on `(tenant_id)` |

### `platform.tenant_tile_sets`  *(optional precomputed tiles)*
Manifest of geo-clipped vector tiles written to the `tenant-tiles` bucket. Keyed by tenant + boundary version + data version.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `tenant_id` | uuid → `tenants(id)` `on delete cascade` | |
| `boundary_version_id` | uuid → `geo.tenant_boundary_versions(id)` | |
| `data_version` | bigint not null | |
| `priority_model_id` | uuid | pinned model for the heat layer |
| `edition_id` | uuid | pinned INEGI edition for the geographies layer |
| `storage_bucket` | text not null `'tenant-tiles'` | |
| `storage_prefix` | text not null | `{tenant}/{boundary}/{data_version}/` |
| `status` | text not null | check `in ('building','ready','stale','failed')` |
| `checksum` | text | |
| `built_at` | timestamptz | |
| `created_at` | timestamptz not null | |
| | | **unique** `(tenant_id, boundary_version_id, data_version)` |

### Functions
| Function | Returns | Notes |
|---|---|---|
| `platform.current_subject_id()` | uuid | subject behind the current JWT (`security definer`, `search_path=''`) |
| `platform.active_tenant_id()` | uuid | reads per-request GUC `app.tenant_id` |
| `platform.is_member(p_tenant uuid, p_min_role text = 'viewer')` | boolean | membership + role check; `analysis_author` implies `viewer` |
| `platform.rebuild_tenant_visible(p_tenant uuid)` | int | full rebuild of the cached visible set against the active boundary; returns row count |
| `platform.can_view_observation(p_observation_id uuid)` | boolean | membership + `ST_Contains(active boundary, location)`; called by `app_authorize_object` to gate R2 media access |
| `platform.drain_outbox()` | void | moves pending outbox rows into `pgmq` queues (see [Async](#async-infrastructure)) |

---

## `vision`

### `vision.read_model_state`  *(singleton)*
A single-row monotonic counter advanced by the vision outbox so caches can be invalidated/rebuilt deterministically.

| Column | Type | Notes |
|---|---|---|
| `only_row` | boolean PK `true` | check `(only_row)` — enforces a single row |
| `data_version` | bigint not null `0` | bumped via `vision.bump_data_version()` |

`vision.bump_data_version()` → bigint increments and returns the new version.

### `vision.sources`
Camera system that produced a sweep. Provenance only — data is shared across all tenants.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `slug` | text not null **unique** | |
| `name` | text not null | |
| `status` | text not null `'active'` | check `in ('active','retired')` |
| `created_at` | timestamptz not null | |

### `vision.observation_types`
Extensible infrastructure-observation type catalog.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `slug` | text not null **unique** | e.g. `pothole` |
| `label` | text not null | |
| `category` | text not null | |
| `description` | text | |
| `merge_radius_m` | real not null `10` | same-type supersession match radius |
| `auto_resolvable` | boolean not null `true` | |
| `auto_resolve_miss_threshold` | int | |
| `status` | text not null `'active'` | check `in ('active','retired')` |

### `vision.observation_attribute_definitions`
A typed factual field that may be recorded for one observation type. Versioned per type-local key; at most one active version per `(type, key)`.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `observation_type_id` | uuid not null → `observation_types(id)` | |
| `key` | text not null | type-local key, e.g. `surface_area_m2` |
| `version` | int not null `1` | |
| `label` | text not null | |
| `value_kind` | text not null | check `in ('number','text','boolean','option')` |
| `unit` | text | |
| `required` | boolean not null `false` | |
| `minimum_number` | numeric | |
| `maximum_number` | numeric | |
| `status` | text not null `'active'` | check `in ('active','retired')` |
| | | **unique** `(observation_type_id, key, version)`; partial **unique** `(observation_type_id, key) where status='active'` |

### `vision.observation_attribute_options`
Allowed codes for an `option`-kind definition.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `definition_id` | uuid not null → `observation_attribute_definitions(id)` | |
| `code` | text not null | |
| `label` | text not null | |
| `status` | text not null `'active'` | check `in ('active','retired')` |
| | | **unique** `(definition_id, code)` |

### `vision.sweeps`
One survey pass and the area it examined.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `source_id` | uuid not null → `sources(id)` | |
| `coverage` | geography not null | swath examined; GiST indexed |
| `started_at` / `ended_at` | timestamptz not null | check `ended_at >= started_at` |
| `created_at` | timestamptz not null | |
| | | GiST index on `coverage`; index on `(source_id)` |

### `vision.sweep_assessed_types`
Explicit list of types a sweep was capable of finding (drives miss detection).

| Column | Type | Notes |
|---|---|---|
| `sweep_id` | uuid → `sweeps(id)` `on delete cascade` | PK part |
| `observation_type_id` | uuid → `observation_types(id)` | PK part |
| | | **PK** `(sweep_id, observation_type_id)` |

### `vision.recordings`
The seekable media unit. A sweep has 1..N recordings (long sweeps segment). Bytes live in the `sweep-video` bucket.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `sweep_id` | uuid not null → `sweeps(id)` | |
| `storage_bucket` | text not null `'sweep-video'` | |
| `storage_path` | text not null | `sweeps/{sweep_id}/{recording_id}.mp4` |
| `media_type` | text not null `'video/mp4'` | |
| `codec`/`width`/`height`/`fps` | text/int/int/real | optional probe metadata |
| `started_at` / `ended_at` | timestamptz not null | wall-clock window; check `ended_at >= started_at` |
| `duration_ms` | integer | |
| `byte_size` | bigint | |
| `checksum` | text | |
| `status` | text not null `'uploading'` | check `in ('uploading','ready','failed')` |
| `created_at` | timestamptz not null | |
| | | **unique** `(storage_bucket, storage_path)`; index on `(sweep_id)` |

### `vision.observations`
One factual detection and its narrow lifecycle state. **No `attributes` JSONB** — typed facts live in `observation_attribute_values`.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `schema_version` | smallint not null `1` | |
| `observation_type_id` | uuid not null → `observation_types(id)` | fact (immutable) |
| `location` | geography(Point,4326) not null | fact (immutable) |
| `observed_at` | timestamptz not null | fact (immutable) |
| `sweep_id` | uuid not null → `sweeps(id)` | provenance |
| `recording_id` | uuid → `recordings(id)` | **set-once**, nullable; enables "inspect the sweep" |
| `media_offset_ms` | integer | **set-once**; deterministic seek; check `>= 0` |
| `frame_ref` | text | producer's native frame index |
| `image_bbox` | jsonb | `{x,y,w,h}` normalized 0..1 |
| `detector_name` / `detector_version` | text not null | |
| `detected_at` | timestamptz not null | |
| `confirmation_count` | int not null `1` | controlled mutation |
| `miss_count` | int not null `0` | controlled mutation |
| `superseded_by_observation_id` | uuid → `observations(id)` | set-once |
| `resolved_at` | timestamptz | set-once |
| `resolution_source` | text | check `in ('human','auto_miss')` |
| `reviewed_by_subject_id` | uuid → `platform.oidc_subjects(id)` | |
| `valid_from` | timestamptz not null | |
| `valid_to` | timestamptz | set-once |
| `created_at` | timestamptz not null | |

Checks: never both superseded and resolved; no self-supersession; `media_offset_ms >= 0`.
Indexes: partial GiST on `location where superseded_by is null and resolved_at is null` (the "current" set); `(observation_type_id)`; `(sweep_id)`; `(recording_id)`.
*An observation is **current** when both `superseded_by_observation_id` and `resolved_at` are null.*

### `vision.observation_attribute_values`
One validated factual measurement per observation per definition. Exactly one value column is populated.

| Column | Type | Notes |
|---|---|---|
| `observation_id` | uuid → `observations(id)` | PK part |
| `definition_id` | uuid → `observation_attribute_definitions(id)` | PK part; supplies kind/unit/bounds |
| `number_value` / `text_value` / `boolean_value` | numeric / text / boolean | one populated |
| `option_id` | uuid → `observation_attribute_options(id)` | one populated |
| `created_at` | timestamptz not null | |
| | | **PK** `(observation_id, definition_id)`; check `num_nonnulls(...) = 1` |

### `vision.observation_thumbnails`
Derived preview, kept in its own table so `observations` stays immutable.

| Column | Type | Notes |
|---|---|---|
| `observation_id` | uuid PK → `observations(id)` | |
| `storage_bucket` | text not null `'observation-thumbnails'` | |
| `storage_path` | text not null | |
| `width`/`height` | int | |
| `source_recording_id` | uuid → `recordings(id)` | |
| `source_offset_ms` | int | |
| `bbox` | jsonb | |
| `status` | text not null `'pending'` | check `in ('pending','ready','failed')` |
| `created_at` | timestamptz not null | |
| | | **unique** `(storage_bucket, storage_path)` |

### `vision.vision_outbox_events`
Committed vision changes for downstream consumers (priority inheritance, cache maintenance, thumbnails). At-least-once delivery; dedupe on `id`.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | idempotency key |
| `event_kind` | text not null | free text — see drift note; drain recognizes `observation_inserted`; design names `sweep_completed`, `observation_superseded`, `observation_resolved` |
| `entity_id` | uuid | affected entity |
| `related_id` | uuid | |
| `occurred_at` | timestamptz not null | |
| `delivery_state` | text not null `'pending'` | check `in ('pending','delivered')` |
| | | partial index on `(occurred_at) where delivery_state='pending'` |

---

## `priority` — application model

### `priority.priority_models`
Versioned priority producer. Exactly one model is active at a time.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `name` | text not null | |
| `version` | text not null | |
| `status` | text not null `'active'` | check `in ('active','retired')` |
| `created_at` | timestamptz not null | |
| | | **unique** `(name, version)`; partial **unique** `((true)) where status='active'` (single active model) |

### `priority.priority_batches`
Operational recomputation work coordination.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `model_id` | uuid not null → `priority_models(id)` | |
| `trigger_sweep_id` | uuid → `vision.sweeps(id)` | null only for non-sweep refreshes |
| `reason` | text not null | check `in ('new_sweep','model_refresh','manual')` |
| `status` | text not null `'queued'` | check `in ('queued','running','completed','completed_with_errors','failed')` |
| `created_at`/`started_at`/`completed_at` | timestamptz | |

### `priority.priority_batch_items`
One observation to recompute within a batch.

| Column | Type | Notes |
|---|---|---|
| `batch_id` | uuid → `priority_batches(id)` `on delete cascade` | PK part |
| `observation_id` | uuid → `vision.observations(id)` | PK part |
| `status` | text not null `'pending'` | check `in ('pending','running','completed','failed')` |
| `failure_code` | text | |
| `updated_at` | timestamptz not null | |
| | | **PK** `(batch_id, observation_id)` |

### `priority.priority_values`
Immutable priority values; `computed` or `inherited`.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `observation_id` | uuid not null → `vision.observations(id)` | |
| `model_id` | uuid not null → `priority_models(id)` | |
| `weight` | numeric not null | |
| `value_state` | text not null | check `in ('computed','inherited')` |
| `inherited_from_value_id` | uuid → `priority_values(id)` | required when inherited |
| `computed_by_batch_id` | uuid → `priority_batches(id)` | required when computed |
| `created_at` | timestamptz not null | |
| | | check enforces the inherited/computed ↔ pointer pairing; index on `(observation_id, model_id)` |

### `priority.current_priority_values`
Selects the currently usable value per `(observation_id, model_id)`.

| Column | Type | Notes |
|---|---|---|
| `observation_id` | uuid → `vision.observations(id)` | PK part |
| `model_id` | uuid → `priority_models(id)` | PK part |
| `priority_value_id` | uuid not null → `priority_values(id)` | |
| `updated_at` | timestamptz not null | |
| | | **PK** `(observation_id, model_id)` |

## `priority` — external-data extension

> These tables are produced by the external-data pipeline, not the application
> data model. They reuse the `priority` schema because ROIs are priority inputs.
> See the external-data pipeline design + `services/external-data`.

### `priority.external_signals`
External risk events (crash/violation/flooding/road_surface/crime), the clustering input for ROIs. PK is a producer-supplied `text` id (not uuid).

| Column | Type | Notes |
|---|---|---|
| `signal_id` | text **PK** | producer id |
| `source_id` | text not null | |
| `risk_dimension` | text not null | check `in ('crash','violation','flooding','road_surface','crime')` |
| `event_type` | text not null | |
| `event_subtype` | text | |
| `geom` | geography(Point,4326) not null | GiST indexed |
| `geom_quality` | text not null | check `in ('point','geocoded','block_centroid')` |
| `occurred_at` / `reported_at` | timestamptz | |
| `severity_weight` | real not null `1` | |
| `geocode_confidence` | real | |
| `attributes` | jsonb not null `'{}'` | |
| `source_object_ref` / `source_url` / `license` | text | provenance |
| `fetched_at` | timestamptz | |
| `ingested_at` | timestamptz not null | |
| | | GiST index on `geom`; index on `(risk_dimension)` |

### `priority.roi_runs`
One ROI-generation run.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `dimensions` | text[] not null | |
| `params` | jsonb not null `'{}'` | |
| `signal_window` | tstzrange | |
| `started_at`/`completed_at` | timestamptz | |
| `roi_count` | int | |

### `priority.rois`
Region-of-interest polygons with risk semantics and a supersession lifecycle (`valid_to`/`superseded_by_run_id`).

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `run_id` | uuid not null → `roi_runs(id)` | |
| `risk_dimension` | text not null | check (same 5 dimensions) |
| `geom` | geography(Polygon,4326) not null | |
| `centroid` | geography(Point,4326) not null | |
| `area_m2` | real not null | |
| `risk_score` | real not null | |
| `signal_count` | int not null | |
| `dominant_type` | text not null | |
| `risk_breakdown` | jsonb not null `'{}'` | |
| `occurred_from`/`occurred_to` | timestamptz | |
| `recency_score` | real | |
| `description` | text not null | |
| `contributing_signal_ids` | text[] not null `'{}'` | |
| `source_object_refs` | text[] not null `'{}'` | |
| `valid_from` | timestamptz not null | |
| `valid_to` | timestamptz | null = current |
| `superseded_by_run_id` | uuid → `roi_runs(id)` | |
| `created_at` | timestamptz not null | |
| | | partial GiST on `geom where valid_to is null`; partial index on `(risk_dimension) where valid_to is null` |

**View `priority.current_rois`** = `select * from priority.rois where valid_to is null`.

---

## `geo`

### `geo.geo_editions`
An imported INEGI dataset edition. Exactly one is active for new bindings/boundary drafts.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `source_name` | text not null | |
| `source_release` | text not null | |
| `effective_date` | date | |
| `checksum` | text | |
| `status` | text not null `'importing'` | check `in ('importing','ready','active','failed','retired')` |
| `imported_at` | timestamptz | |
| | | partial **unique** `((true)) where status='active'` (single active edition) |

### `geo.geo_areas`
INEGI areas (state/municipality/AGEB). Source keys are `text` to preserve leading zeroes; self-referential parent hierarchy.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `edition_id` | uuid not null → `geo_editions(id)` | |
| `level` | text not null | check `in ('AGEE','AGEM','AGEB')` |
| `source_cvegeo` | text not null | complete INEGI key |
| `cve_ent`/`cve_mun`/`cve_loc`/`cve_ageb` | text | component keys |
| `name` | text | |
| `ageb_kind` | text | check `in ('urban','rural')` |
| `parent_area_id` | uuid → `geo_areas(id)` | AGEE→AGEM→AGEB |
| `geometry` | geometry(MultiPolygon,4326) not null | GiST indexed |
| | | **unique** `(edition_id, level, source_cvegeo)`; GiST on `geometry`; index on `(parent_area_id)` |

### `geo.tenant_boundary_versions`
Immutable configured working boundary for a tenant. One active version per tenant.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `tenant_id` | uuid not null → `platform.tenants(id)` | |
| `edition_id` | uuid not null → `geo_editions(id)` | pinned edition |
| `version_number` | int not null | tenant-local monotonic |
| `status` | text not null `'draft'` | check `in ('draft','active','retired')` |
| `materialized_geometry` | geometry(MultiPolygon,4326) | union of selected areas; GiST indexed |
| `geometry_checksum` | text | |
| `created_at`/`activated_at` | timestamptz | |
| | | **unique** `(tenant_id, version_number)`; partial **unique** `(tenant_id) where status='active'` (single active boundary); GiST on `materialized_geometry` |

### `geo.tenant_boundary_areas`
INEGI areas selected into a boundary version.

| Column | Type | Notes |
|---|---|---|
| `boundary_version_id` | uuid → `tenant_boundary_versions(id)` `on delete cascade` | PK part |
| `geo_area_id` | uuid → `geo_areas(id)` | PK part |
| | | **PK** `(boundary_version_id, geo_area_id)` |

### `geo.observation_geo_bindings`
Classifies an observation point under one INEGI edition's hierarchy. At most one binding per `(observation, edition)`.

| Column | Type | Notes |
|---|---|---|
| `observation_id` | uuid → `vision.observations(id)` | PK part |
| `edition_id` | uuid → `geo_editions(id)` | PK part |
| `agee_area_id`/`agem_area_id`/`ageb_area_id` | uuid → `geo_areas(id)` | containing areas |
| `bound_at` | timestamptz not null | |
| | | **PK** `(observation_id, edition_id)` |

---

## `analysis`

### Definition layer

**`analysis.analysis_providers`** — external provider + enabled status (`id`, `slug` unique, `name`, `status in ('enabled','disabled')`, `config_ref`, `created_at`).

**`analysis.analysis_definitions`** — stable analysis kind (`id`, `kind` unique e.g. `budget.route`, `label`, `created_at`).

**`analysis.analysis_definition_versions`** — pins one provider interface version per definition.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `definition_id` | uuid not null → `analysis_definitions(id)` | |
| `provider_id` | uuid not null → `analysis_providers(id)` | |
| `interface_version` | text not null | |
| `request_schema` / `result_schema` | jsonb not null | versioned provider contracts |
| `artifact_kinds` | jsonb not null `'[]'` | |
| `ui_descriptor` | jsonb not null `'{}'` | |
| `status` | text not null `'draft'` | check `in ('draft','active','retired')` |
| `created_at` | timestamptz not null | |
| | | **unique** `(definition_id, interface_version)` |

**`analysis.provider_capability_snapshots`** — frozen provider descriptor used to construct/reproduce a submission (`id`, `definition_version_id`, `descriptor jsonb`, `config_version`, `created_at`).

### `analysis.analysis_runs`
One submitted analysis. Idempotency key unique within tenant; pins boundary version + edition + definition version + capability snapshot.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `idempotency_key` | text not null | |
| `tenant_id` | uuid not null → `platform.tenants(id)` | |
| `requested_by_subject_id` | uuid not null → `platform.oidc_subjects(id)` | |
| `definition_version_id` | uuid not null → `analysis_definition_versions(id)` | |
| `capability_snapshot_id` | uuid not null → `provider_capability_snapshots(id)` | |
| `boundary_version_id` | uuid not null → `geo.tenant_boundary_versions(id)` | |
| `edition_id` | uuid not null → `geo.geo_editions(id)` | |
| `budget_amount` | numeric(14,2) not null | check `>= 0` |
| `budget_currency` | text not null | |
| `status` | text not null `'queued'` | check `in ('queued','running','succeeded','failed','cancelled')` |
| `created_at`/`started_at`/`finished_at` | timestamptz | |
| `cancel_requested_at` | timestamptz | |
| `cancel_requested_by_subject_id` | uuid → `platform.oidc_subjects(id)` | |
| | | **unique** `(tenant_id, idempotency_key)`; index on `(tenant_id, created_at)` |

### Scope (mutually exclusive forms)
- **`analysis.run_scope_areas`** — `(run_id, geo_area_id)` PK; union of areas. `run_id` cascades.
- **`analysis.run_scope_geometry`** — `run_id` PK; single `geometry(Geometry,4326) not null` drawn shape.
- **`analysis.run_type_settings`** — per-type investment controls: `(run_id, observation_type_id)` PK, `enabled bool`, `cost_basis_id`, `unit`, `unit_rate numeric(14,2)` (check `>= 0`).

### Frozen inputs (immutable after queueing — enforcement **pending**)
- **`analysis.run_observations`** — frozen copy of eligible observations: `(run_id, observation_id)` **PK** (target of artifact FKs), plus `observation_type_id`, `location geography(Point,4326)`, `observed_at`, `recording_id`, `frame_ref`, `lifecycle_version bigint`.
- **`analysis.run_observation_attributes`** — frozen typed facts: `(run_id, observation_id, definition_key)` PK; `value_kind`, `number_value`/`text_value`/`boolean_value`/`option_code`, `unit`; composite FK → `run_observations(run_id, observation_id)` cascade.
- **`analysis.run_priority_values`** — frozen weights: `(run_id, observation_id)` PK; `weight`, `model_name`, `model_version`, `value_state in ('computed','inherited')`; composite FK → `run_observations` cascade.
- **`analysis.run_observation_exclusions`** — `(run_id, observation_id)` PK; `reason in ('unscored','unsupported_type','disabled_type','missing_required_fact')`.

### Execution
**`analysis.analysis_attempts`** — one row per retry: `id`, `run_id` (cascade), `attempt_number`, `provider_request_id`, `status in ('running','succeeded','failed','cancelled')`, `started_at`/`finished_at`, `response_hash`, `failure_code`, `failure_details jsonb`; **unique** `(run_id, attempt_number)`.

**`analysis.analysis_results`** — one accepted result per run: `id`, `run_id` not null **unique** (cascade), `accepted_attempt_id` → `analysis_attempts(id)`, `provider_version`, `config_version`, `result_schema_version`, `payload jsonb not null`, `created_at`.

### Result detail & artifacts
- **`analysis.result_metrics`** — `(id, result_id↓, key, label, unit, number_value, text_value)`.
- **`analysis.result_warnings`** — `(id, result_id↓, code, severity, message)`.
- **`analysis.artifacts`** — `(id, result_id↓, kind in ('map_features','ordered_sequence','table','chart','asset_ref'), schema_version, display_order, title, payload jsonb)`.
- **`analysis.map_features`** — normalized geometry output: `(id, artifact_id↓, geometry(Geometry,4326), feature_key, properties jsonb)`; GiST on `geometry`.
- **`analysis.artifact_observation_refs`** — links artifact to frozen run observations: `(id, artifact_id↓, run_id, observation_id, role, display_order)`; composite FK → `run_observations(run_id, observation_id)` (no cross-run refs).
- **`analysis.sequence_items`** — ordered route/sequence items: `(id, artifact_id↓, position, run_id, observation_id, provider_ref, label)`; composite FK → `run_observations`.
- **`analysis.asset_refs`** — provider asset pointers (no bytes): `(id, artifact_id↓, provider_asset_id, media_type, integrity_hash, storage_ref)`.

(↓ = `on delete cascade` from the parent.)

---

## Async infrastructure

**Outbox tables** (`vision.vision_outbox_events`, `analysis.analysis_outbox_events`) capture committed changes with a `delivery_state` and partial "pending" indexes.

**`pgmq` queues** (`0010`): `analysis_jobs`, `materialization_jobs`, `thumbnail_jobs`.

**`platform.drain_outbox()`** (`security definer`, `search_path=''`) moves pending outbox rows into the matching queue and marks them `delivered`:
- every pending `vision_outbox_events` row → `materialization_jobs`; rows with `event_kind = 'observation_inserted'` also → `thumbnail_jobs`.
- every pending `analysis_outbox_events` row → `analysis_jobs`.

**`pg_cron`** runs `select platform.drain_outbox();` on the job named `drain_outbox` every **10 seconds**.

A worker (not yet in this repo) is expected to consume the queues, run the provider adapter, rebuild the read-model cache, and produce thumbnails. The worker writes media/tiles to Cloudflare R2 over the S3 API (`STORAGE_BACKEND=r2`) and connects to Supabase Postgres for DB writes — no service-role key is used for storage.

## Storage buckets

Object storage is on **Cloudflare R2** — not Supabase Storage. All four buckets are
private R2 buckets declared as IaC in `services/broker/wrangler.toml`. There are no
`storage.buckets` rows and no Supabase Storage RLS policies.

Full reference (paths, lineage, access control, agent/engineer guidance):
[**`STORAGE.md`**](./STORAGE.md). Summary:

| Bucket | Provider | Holds | Path root | Referenced by |
|---|---|---|---|---|
| `external-data` | Cloudflare R2 | raw + staging external-data objects | `raw/…`, `staging/…` | `priority.external_signals.source_object_ref`, `priority.rois.source_object_refs` |
| `sweep-video` | Cloudflare R2 | per-sweep recordings | `sweeps/{sweep_id}/…` | `vision.recordings` |
| `observation-thumbnails` | Cloudflare R2 | per-observation previews | `observations/{observation_id}/…` | `vision.observation_thumbnails` |
| `tenant-tiles` | Cloudflare R2 | precomputed geo-clipped tiles | `{tenant_id}/{boundary_version_id}/{data_version}/…` | `platform.tenant_tile_sets` |

**Access model:** protected media and tiles are served by the Python Cloudflare Worker
broker at `https://r2-access-broker.alamst.workers.dev`. Clients call
`GET /api/r2/object?bucket=&path=` with their Supabase JWT; the broker calls
`public.app_authorize_object(p_bucket, p_path)` (which reuses `platform.is_member` /
`platform.can_view_observation`) and, on allow, streams bytes from R2 via an R2 binding
(Range → 206). There are no Supabase signed URLs and no service-role key for storage.
External-data pipeline and vision/tile workers write to R2 over the S3 API. See
`STORAGE.md` for full path templates and access-control rules.

## Invariants enforced in-database today

- **Single active row** via partial unique indexes: one active `priority_models`, one active `geo_editions`, one active `tenant_boundary_versions` per tenant.
- **Idempotency:** `analysis_runs (tenant_id, idempotency_key)` unique; **one result per run** via `analysis_results.run_id` unique; **attempt uniqueness** via `(run_id, attempt_number)`.
- **No cross-run artifact refs:** `artifact_observation_refs`/`sequence_items` FK the composite `run_observations(run_id, observation_id)`.
- **Exactly one attribute value:** `observation_attribute_values` `num_nonnulls(...) = 1`.
- **Observation lifecycle:** never both superseded and resolved; no self-supersession.
- **Priority value pairing:** inherited ⇒ predecessor pointer set; computed ⇒ batch pointer set.
- **Budget / rates nonnegative:** `budget_amount >= 0`, `unit_rate >= 0`.

## Row-level security & immutability (implemented)

RLS and the immutability/append-only triggers ARE in the migrations (this was
previously documented as pending; corrected to reflect `0012`/`0300`):

- **RLS enabled (with policies):**
  - `platform.tenant_visible_observations` — `tvo_read` (`0012`): select for `authenticated`
    where `tenant_id = active_tenant_id()` and member-viewer.
  - `vision.observations` — `obs_read` (`0012`): select for `authenticated` gated through
    `tenant_visible_observations` for the active tenant.
  - `analysis.analysis_runs` — `runs_read` (member-viewer) / `runs_write` (member-author) (`0012`).
  - `community.inference_jobs` — RLS enabled **deny-by-default, no policies** (`0300`); trusted
    backends connect as a `BYPASSRLS`/`service_role` role, so `anon`/`authenticated` get nothing.
- **Immutability / append-only triggers (`0012`):** `vision.observations`
  (`enforce_observation_immutability` — immutable fact/provenance columns, set-once lifecycle
  columns); append-only rejects on `platform.audit_events`, `analysis.run_observations`,
  `analysis.run_observation_attributes`, `analysis.run_priority_values`,
  `vision.observation_attribute_values`. `community.inference_jobs` has a `touch_updated_at`
  trigger (`0300`).

**Defense-in-depth gap (still recommended):** the remaining factual tables — e.g. the
catalogs in `vision`/`priority`, `platform.tenants`/`tenant_memberships`/`oidc_subjects`,
`geo.*`, `analysis.analysis_results` and the frozen-input tables — do **not** have RLS
enabled and rely on absence-of-grants (service-role-only writes by convention). Adding
deny-by-default RLS (`enable row level security` with no/explicit policies) to these would
make the access posture explicit rather than grant-dependent. The `revoke`/`grant` hardening
on factual tables (§11.1) is likewise not yet applied.

## Specced-but-not-yet-implemented (ongoing)

The migrations build the tables, helper functions, queues, and the read-model
cache. The following are designed (physical spec §9–§13) but **not yet in any
migration** — track them as the remaining data-model work:

| Pending | Spec | Effect today |
|---|---|---|
| **`revoke`/`grant`** hardening on factual tables | §11.1 | Not applied |
| **Deny-by-default RLS on remaining factual tables** | §9 | Only the tables listed above are row-secured; the rest rely on absence-of-grants |
| **`sweep-video`, `observation-thumbnails`, `tenant-tiles` R2 buckets** | §8 | Declared in `services/broker/wrangler.toml`; DB pointer columns reference them but no seed rows exist yet |
| **Incremental cache maintenance** (worker adds/removes single rows on outbox events) | §5.2 | Only full `rebuild_tenant_visible()` exists |
| **`seed.sql`** (type catalog, dev tenant, INEGI fixture, active boundary) | §13.5 | `supabase db reset` produces an empty schema |
| **Generated TS types** (`packages/db-types`) | §13.1 | Not generated |
| **Worker server** (`services/worker`) consuming the queues | §10 | Queues drain into `pgmq` but nothing consumes them |

## Notes & drift

- **`vision_outbox_events.event_kind` is free text** (no CHECK). The `0009` comment
  names `sweep_completed` / `observation_superseded` / `observation_resolved`, while
  `drain_outbox()` branches on `observation_inserted` for thumbnail jobs. Treat the
  set of kinds as an open producer/consumer contract until a CHECK or enum doc pins it.
- **`priority` schema is shared by two streams.** The application model owns
  `priority_models`…`current_priority_values`; the external-data pipeline owns
  `external_signals` / `roi_runs` / `rois`. They are independent — the only link is
  conceptual (ROIs feed prioritization).
- **`external_signals.signal_id` is a `text` natural key**, not a uuid, because it
  carries the producer's stable object reference.
- The implemented DDL matches the implementation plan and physical design 1:1 for the
  `0001`–`0011` band; this reference reflects the migrations, not the plan, where they
  could differ.
