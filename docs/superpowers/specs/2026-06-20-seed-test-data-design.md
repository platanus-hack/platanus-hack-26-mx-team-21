# Seed & Test Data — Design

**Date:** 2026-06-20
**Status:** Approved design
**Component:** Database population (test tenant, users, observations, priority, geo, analysis, ROIs)

---

## 1. Purpose & scope

Populate the deployed Supabase data model with a deterministic, reproducible dataset so the
**City Priority Map application** (`apps/web`, the "Vialia" SPA) can be built and tested against
live data. This is the work referenced by that plan's **§4 "DB Data Contract"**: the DB is
populated by a separate agent (this work); the app side writes no observation/geo/priority/user
seed.

The dataset must let the UI team exercise every screen and state the application renders, and it
must behave correctly under the **live RLS** the read API depends on.

Source-of-truth chain this spec serves:

- UI data contract: `docs/superpowers/plans/2026-06-20-city-priority-map-application.md` §4 (§4.1–§4.6).
- UI surfaces & roles: `docs/superpowers/specs/2026-06-20-application-system-architecture-design.md`.
- Logical model: `docs/superpowers/specs/2026-06-20-application-data-model-design.md`.
- As-built physical schema: `supabase/SCHEMA.md` + `supabase/migrations/0001`–`0013`, `0101`–`0103`.

**In scope:** catalog, geography, one tenant + auth users, observations across all lifecycle/priority
states, priority values, analysis enablement + a few pre-seeded runs/results, ROIs, cache rebuild,
and a verification test.

**Out of scope:** the `public` read/analysis API layer (`0200`/`0201` — owned by the app team's
Task 0.1); real video/thumbnail bytes; the INEGI importer (geo areas are hand-authored fixtures);
the external-data pipeline run (ROIs are hand-authored, not produced by `services/external-data`);
a second tenant (explicitly one tenant — isolation is proven via in/out-of-boundary observations).

---

## 2. Grounding facts (drive every implementation decision)

These were verified against the migrations on disk and override the stale `SCHEMA.md`
"pending" notes (`SCHEMA.md` was last verified against `0001`–`0011` only; `0012`/`0013` are applied):

1. **RLS is live (`0012`) and scoped `to authenticated`.** `supabase db reset` runs `seed.sql`
   as the `postgres` superuser, which **bypasses RLS** — so seeding is unobstructed. The dataset
   must nonetheless be *shaped* so the read API (running as `authenticated`) returns the right
   rows: visibility = `tenant_visible_observations` ∩ active boundary, gated by `is_member`.
2. **Immutability triggers fire `BEFORE UPDATE` only**, never on INSERT
   (`vision.enforce_observation_immutability`; append-only `reject_mutation` on `audit_events`,
   `run_observations`, `run_observation_attributes`, `run_priority_values`,
   `observation_attribute_values`). Therefore every lifecycle state is **inserted in final form**:
   insert a successor observation first, then the superseded predecessor pointing at it
   (`superseded_by_observation_id` + `valid_to` set at INSERT). **No UPDATEs anywhere in the seed.**
3. **Single-active partial-unique indexes** exist: one active `priority_models`, one active
   `geo_editions`, one active `tenant_boundary_versions` per tenant. Seed must respect these.
4. **The read API depends on the cached geo-clip.** The seed must finish by advancing
   `vision.bump_data_version()` and calling `platform.rebuild_tenant_visible(<tenant>)` so
   `platform.tenant_visible_observations` is populated for the read functions.
5. **Auth login on local needs both `auth.users` and `auth.identities`** (email provider) plus the
   `platform.oidc_subjects.user_id` bridge and a `tenant_memberships` row.

---

## 3. Delivery mechanism

- **Modular fixtures** under `supabase/seed/`, applied in order via `[db.seed].sql_paths` in
  `supabase/config.toml`, run by `supabase db reset` (which applies `migrations/` then the seed).
  - `00_catalog.sql` — sources, types, attribute definitions/options, sweeps, recordings.
  - `10_geo.sql` — edition, areas (AGEE/AGEM), tenant + boundary + boundary areas.
  - `20_auth.sql` — `auth.users` + `auth.identities` + `oidc_subjects` + memberships.
  - `30_observations.sql` — procedural observations + attribute values + geo bindings.
  - `40_priority.sql` — model, batch, values, current values.
  - `50_analysis.sql` — providers/definitions/versions/snapshots + pre-seeded runs/results/artifacts.
  - `60_rois.sql` — roi_run + rois.
  - `99_finalize.sql` — `bump_data_version()` + `rebuild_tenant_visible()` + a few `audit_events`.
- **Fallback:** if the installed CLI does not support `sql_paths`, concatenate the same content into
  a single sectioned `supabase/seed.sql` with clear section banners. (The existing one-line dev
  `seed.sql` is replaced/superseded by this dataset.)
- **Determinism:** every row uses a **fixed, namespaced UUID** (e.g. `'0000…-tnnn'` conventions) so
  FKs are stable and integration tests can hard-reference IDs. Procedural rows derive their UUIDs
  from a deterministic expression of the series index (e.g. `md5(...)::uuid`). **No `random()`,
  no `now()`-relative values that drift between runs** — use a fixed reference timestamp constant.
- **Idempotency:** every insert is `on conflict do nothing` (or guarded) so re-running the seed
  without a full reset is safe.

**Rejected alternatives:** a single monolithic `seed.sql` (maintainable-by-nobody, hard to map to
§4); a TS/Python generator using the Auth admin API (correct for auth users, but abandons the
`supabase db reset` mechanism and creates a second source of truth).

---

## 4. Dataset specification (mapped to §4 of the app plan)

### 4.1 Catalog & provenance (`vision`)

- **`sources`** (≥1): 2 rows — `truck_fleet` ("Trash-truck fleet cam"), `adhoc_survey` ("Ad-hoc survey").
- **`observation_types`** — the reference five, with `auto_resolvable` driving the app's `is_latent`:
  | slug | label | category | auto_resolvable | is_latent (app) |
  |---|---|---|---|---|
  | `pothole` | Bache | road_surface | true | false |
  | `open_drain` | Coladera abierta | drainage | true | false |
  | `broken_light` | Luminaria dañada | lighting | true | false |
  | `missing_signage` | Señalización faltante | signage | **false** | **true** |
  | `damaged_sidewalk` | Banqueta dañada | pedestrian | true | false |
- **`observation_attribute_definitions`** (active, version 1) per type: a quantity field —
  `pothole`→`surface_area_m2` (number, m²), `damaged_sidewalk`→`length_m` (number, m),
  `open_drain`/`broken_light`/`missing_signage`→`count` (number) — **plus** an optional
  `confidence` (number, 0..1) on each type (drives the card's `conf`).
- **`sweeps`** (2–3) with `geography` `coverage` over the CDMX bbox, `started_at`/`ended_at` at the
  fixed reference time; each with `sweep_assessed_types` covering all five types and 1–2 `recordings`
  (storage paths only — no bytes; the `sweep-video` bucket is column-default-only).

### 4.2 Geography (`geo`)

- **`geo_editions`**: 1 row, `status='active'`, `source_name='INEGI MGN'`, `source_release='2020'`
  (synthetic fixture — flagged as such in `description`/notes; no importer exists).
- **`geo_areas`**: 1 **AGEE** (`cve_ent='09'`, "Ciudad de México") + ~7 **AGEM** alcaldías with
  **real** `cve_mun`/names and approximate `MultiPolygon` geometries placed over the true bbox:
  Cuauhtémoc (`015`), Iztapalapa (`007`), Coyoacán (`003`), Gustavo A. Madero (`005`),
  Álvaro Obregón (`010`), Tlalpan (`012`), Venustiano Carranza (`017`). Each AGEM `parent_area_id`
  → the AGEE. (A couple of AGEBs are optional for the area-picker depth; deferred unless cheap.)
- **`tenant_boundary_versions`** / **`tenant_boundary_areas`**: see §4.3.

### 4.3 Tenant & auth (`platform`, `auth`)

- **One tenant**: `platform.tenants` "Vialia CDMX" (`status='active'`).
- **Active boundary**: one `tenant_boundary_versions` (`status='active'`, `version_number=1`)
  whose `materialized_geometry` = `ST_Multi(ST_Union(...))` of **~6** AGEM polygons.
  **One alcaldía (e.g. Tlalpan) is deliberately excluded** so observations there test the geo-clip.
  `tenant_boundary_areas` links the 6 included areas.
- **Users** (each: `auth.users` + `auth.identities`[email] + `platform.oidc_subjects.user_id` +
  membership). One shared fixed dev password (e.g. `vialia-dev-2026!`), documented in
  `apps/web/.env.example` placeholders and the seed PR description:
  | email | oidc status | role | purpose |
  |---|---|---|---|
  | `author.a@vialia.test` | active | `analysis_author` | the §4.4 dev login (full app) |
  | `viewer.a@vialia.test` | active | `viewer` | read-only role coverage |
  | `nomember@vialia.test` | active | *(none)* | §5 "no membership" empty-state |
  - Optional: a `disabled@vialia.test` with `oidc_subjects.status='disabled'` (exercise disabled).

### 4.4 Observations & priority (`vision`, `priority`)

- **`observations`**: **~120–150** rows, deterministically placed across the seven hot zones
  (Centro/Cuauhtémoc, Iztapalapa, Coyoacán, GAM, Álvaro Obregón, V. Carranza, + Tlalpan as the
  out-of-boundary zone). Each row sets `location`, `observed_at`, `confirmation_count`, `miss_count`,
  `image_bbox` (`{x,y,w,h}` 0..1), `frame_ref`, `recording_id`, `media_offset_ms`, detector
  name/version, `valid_from`. Type mix is zone-weighted (deterministic by index). Distribution:
  - **Majority** current + **scored** (have a `current_priority_values` row).
  - **~10–15** current + **pending** (no `current_priority_values` → app `state='pending'`, dashed pin).
  - **~3–5 superseded**: successor (current, with an `inherited` priority value) + predecessor
    (`superseded_by_observation_id`, `valid_to` set, higher `confirmation_count` on successor).
  - **~3–5 resolved**: `resolved_at` + `resolution_source` (`human` and `auto_miss`),
    `reviewed_by_subject_id` for human ones, `valid_to` set.
  - **~8–10 placed OUTSIDE the active boundary** (in Tlalpan / outside bbox) — current+scored, used
    to prove the geo-clip hides them from the tenant.
- **`observation_attribute_values`**: a quantity value per observation (per its type's definition) +
  a `confidence` value on most. Exactly one value column populated (`num_nonnulls=1`).
- **`observation_geo_bindings`**: one binding per observation under the active edition, resolving
  `agee_area_id` + `agem_area_id` (so `district_cve`/`district_name`/`zone` resolve in the read API).
- **`priority_models`**: 1 active (`baseline`/`v1`). **`priority_batches`**: 1 (`reason='new_sweep'`,
  `status='completed'`, `trigger_sweep_id`). **`priority_values`**: a `computed` value (weights 1–99,
  deterministic) for each scored observation (`computed_by_batch_id` set); an `inherited` value for
  each superseded→successor pair (`inherited_from_value_id` set). **`current_priority_values`**:
  points at the current value for every scored/superseded-successor observation; **absent** for
  pending ones.

### 4.5 Analysis enablement & pre-seeded runs (`analysis`)

- **Enablement (required so RPC inserts satisfy FKs):** 1 `analysis_providers`
  (`in_db_executor`, enabled); `analysis_definitions` `budget.route`, `budget.cluster`,
  `inspection.latent`; one active `analysis_definition_versions` each (minimal `request_schema`/
  `result_schema`/`artifact_kinds`/`ui_descriptor` with per-type cost-basis defaults in MXN);
  one `provider_capability_snapshots` per version.
- **Pre-seeded runs (for the History popover + "open past run"):** all tenant-scoped, requested by
  `author.a`, with fixed `idempotency_key`s:
  - **1 succeeded `budget.route`** — frozen inputs (`run_observations` subset + `run_priority_values`
    + `run_observation_attributes` + `run_observation_exclusions` for the pending ones), a succeeded
    `analysis_attempts`, an `analysis_results` whose `payload` matches the app's `app_run_analysis`
    return shape, `result_metrics` (`spent`, `count`, `riskRed`, `distKm`, `zones`), and an `artifacts`
    row (`map_features` line + `sequence_items` ordered stops + `artifact_observation_refs` role `stop`).
  - **1 succeeded `budget.cluster`** — polygon `map_features` + member `artifact_observation_refs`
    (role `member`) + metrics.
  - **1 failed** run (failed `analysis_attempts` + `failure_code`, no result) and **1 queued** run —
    for History status coverage.

### 4.6 ROIs (`priority` external-data tables)

- **1 `roi_runs`** + **~5 `rois`** (`valid_to` null → `current_rois`) as `Polygon` geometries with
  `centroid`, `risk_score`, `dominant_type`, `risk_dimension` across `crash`/`crime`/`flooding`,
  placed in high-risk / low-observation zones (e.g. parts of Iztapalapa, GAM) so the latent layer
  shows real ROIs rather than synthetic grid cells.

### 4.7 Finalize (`99_finalize.sql`)

- `select vision.bump_data_version();`
- `select platform.rebuild_tenant_visible('<tenant-uuid>');`
- A few `platform.audit_events` (boundary activation, analysis submission) for completeness.

---

## 5. Verification (Definition of Done #3 — tests run & pass)

A SQL/pgTAP test (e.g. `supabase/tests/0202_seed_contract.test.sql`) run after `supabase db reset`:

**Contract coverage**
- `observation_types` count = 5 and includes the latent `missing_signage`.
- `observations` count ≥ 120; ≥1 each of pending / superseded / resolved; ≥1 outside the boundary.
- Exactly one active `priority_models`, one active `geo_editions`, one active boundary.
- `current_priority_values` exists for scored observations and is absent for pending ones.
- Every in-boundary observation has an `observation_geo_bindings` row resolving an AGEM.
- ≥1 succeeded `budget.route` run with a `map_features`+`sequence_items` artifact; definitions enabled.

**Live RLS path (the real proof the read API will work)**
- `set local role authenticated` + `set local request.jwt.claims` (`sub` = `author.a`'s `user_id`) +
  `set local app.tenant_id = '<tenant>'`:
  - `select count(*) from vision.observations` > 0 and equals the in-boundary visible count.
  - `platform.tenant_visible_observations` excludes the Tlalpan / out-of-bbox observations.
- Repeat with the `nomember` user's `sub`: visible count = 0 (and `app_active_tenant()` will error,
  once `0200` lands).

> Once the app team's `0200`/`0201` migrations land, extend this test to assert `app_map_observations()`,
> `app_observation_types_counts()`, `app_priority_cells()`, `app_current_rois()`,
> `app_observation_detail()`, and `app_list_runs()` return populated, correctly-shaped rows for the
> dev session. These functions are the contract; this seed exists to make them return data.

---

## 6. Coordination & handoff

- **Credentials handoff:** the seed PR documents the dev users + shared password; `apps/web/.env.example`
  gets placeholder entries (`VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, and a comment listing the
  dev login). No real keys committed.
- **Contract stays in sync:** if the app team's read API needs a field this seed doesn't populate
  (e.g. an explicit `latent`/`color` catalog column), update §4 of the app plan and this spec together.
- **Definition of done** (per repo bar): schema-compatible with `migrations/*` + `SCHEMA.md`; the
  verification test in §5 is **run and shown green** (no "should pass"); the dataset makes the
  reference screen render credibly once `apps/web` is wired.

---

## 7. Risks & open items

- **CLI `sql_paths` support** — confirm the installed `supabase` CLI honors `[db.seed].sql_paths`;
  else use the single-file fallback. (Resolve in implementation Task 1.)
- **`auth.identities` shape drift** — the exact required columns for email login vary by GoTrue
  version; pin the working insert during implementation and keep it idempotent.
- **Procedural SQL density** — generating ~120 placed observations in pure SQL is the trickiest part;
  isolate it in `30_observations.sql` with a clear zones CTE and a single tunable count constant.
- **Geo realism** — alcaldía polygons are approximate fixtures (no INEGI import); good enough for
  clip/zone resolution and the map, not for precise boundary rendering.
