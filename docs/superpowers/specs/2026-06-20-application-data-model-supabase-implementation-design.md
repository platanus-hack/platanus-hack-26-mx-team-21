# Application Data Model — Supabase Implementation Design

**Date:** 2026-06-20
**Status:** Approved design
**Component:** Physical realization of the application data model on Supabase, the
shared object-storage / video model, and the cached geo-clip read model
**Extends:** `2026-06-20-application-data-model-design.md` (the logical model)
**Builds on:** `2026-06-20-application-system-architecture-design.md`,
`2026-06-20-observation-contract-design.md`

---

## 1. Scope

This spec turns the **logical** application data model into a **buildable physical
design on Supabase**. The logical model remains the source of truth for *meaning*;
this document adds the *mechanism*:

- Supabase platform baseline: extensions, schemas, identifier conventions, and the
  Supabase Auth ↔ application identity bridge.
- Two changes of plan, now in scope:
  1. **Object storage is shared with the application.** Media is no longer an
     external module. Recordings, video, and thumbnails are first-class entities in
     the `vision` schema with Supabase Storage as the byte store.
  2. **Sweep video is stored and inspectable.** A map observation can be traced back
     to the exact moment in its sweep recording that discovered it ("inspect the
     sweep" feature).
- A **cached geo-clip read model** so tenant boundary filtering is computed once per
  boundary version / data version instead of on every read.
- Concrete realization rules, reference DDL, RLS, Storage buckets and policies, the
  queue/outbox mechanism, immutability enforcement, and migration ordering.

### 1.1 What this spec does *not* change

The logical model's entities, invariants, lifecycle rules, and acceptance scenarios
stand. Where the SQL here and the logical prose differ on *meaning*, the logical
model controls; where they differ on *mechanism*, this document controls.

### 1.2 Relationship to the observation contract

The observation contract's `observations.attributes JSONB` column is **superseded**
by the logical model's typed `observation_attribute_*` tables and is **not created**.
The contract's standalone DDL is therefore not copied verbatim; observations are
realized as defined in §6 here.

---

## 2. Audit Carried Forward

The logical model is well-disciplined (facts vs. derived separation, immutability
invariants, reproducible frozen runs, outbox-driven consistency). The implementation
must close these seams, all created by the new direction:

| # | Finding | Resolved in |
|---|---|---|
| 1 | Media declared out-of-model, but the inspect feature pulls it in; `recording_id`/`frame_ref` dangle | §6, §7 |
| 2 | `frame_ref` (free text) is insufficient for deterministic playback seek | §6.3, §7 |
| 3 | Sweep↔video cardinality undefined (long sweeps segment) | §7.1 |
| 4 | Auth assumed generic OIDC; Supabase Auth overlaps | §4, §9 |
| 5 | Tenancy is geographic (no `tenant_id` on observations); naive per-row spatial RLS is too costly | §5, §9 |
| 6 | Object-storage access control unspecified | §8, §9.4 |
| 7 | Logical→physical mechanics undecided (schemas, ids, queue, immutability) | §3, §10, §11, §12 |
| 8 | `attributes JSONB` vs. typed attribute tables must be reconciled | §1.2 |

---

## 3. Platform Baseline

### 3.0 Verified live-project baseline (2026-06-20)

Checked against project `joixzhdpnxqhnuscxsoy` via the Supabase MCP:

- **Greenfield:** no tables and no migrations — this spec defines the full schema.
- **Extensions:** all required extensions are *available* but not yet installed
  (`postgis` 3.3.7, `pgmq` 1.5.1, `pg_cron` 1.6.4, `pg_net` 0.20.3). `pgcrypto`,
  `uuid-ossp`, and `pg_stat_statements` are already installed in the **`extensions`**
  schema — the convention this spec follows.
- **Storage:** global `fileSizeLimit` is **50 MB** (`52428800`); S3 protocol and image
  transformation are enabled. The 50 MB cap must be raised for sweep video (§8, §13.4).

### 3.1 Extensions

| Extension | Install schema | Purpose |
|---|---|---|
| `postgis` | `extensions` | Geography/geometry types, spatial indexes, tile generation |
| `pgmq` | `pgmq` (own) | Durable in-database message queues for async work |
| `pg_cron` | `cron` (own) | Scheduled outbox drains, cache rebuilds, retries |
| `pg_net` | `net` (own) | Optional async HTTP to wake the worker server |

```sql
-- gen_random_uuid() is Postgres core (pg_catalog); pgcrypto/uuid-ossp already present.
create extension if not exists postgis with schema extensions;
create extension if not exists pgmq;     -- manages its own `pgmq` schema
create extension if not exists pg_cron;  -- manages its own `cron` schema
create extension if not exists pg_net;   -- exposes the `net` schema
```

Because PostGIS lives in `extensions`, functions that call PostGIS set
`search_path = extensions, public` so `ST_*` and the `geometry`/`geography` types
resolve (see §9.4).

### 3.2 Schemas (= logical ownership domains)

```sql
create schema if not exists platform;  -- tenants, identities, audit, read-model cache
create schema if not exists vision;    -- sources, sweeps, observations, MEDIA (recordings, thumbnails)
create schema if not exists priority;  -- models, batches, values, current pointers
create schema if not exists geo;       -- INEGI editions/areas, tenant boundaries, bindings
create schema if not exists analysis;  -- providers, definitions, runs, frozen inputs, results
```

- **Media lives inside `vision`** — it is observation provenance, not a separate
  domain.
- The **cached read model** (`tenant_visible_observations`, `tenant_tile_sets`) lives
  in `platform`; it is derived, tenant-scoped, and may reference `vision`/`geo` by id
  without owning them.
- PostgREST exposes only the read views needed for simple authenticated reads
  (`db-schemas = platform, geo`). All writes, all shared/geo reads, and signed-URL
  minting go through the worker / service-role RPC, not direct PostgREST table access.

### 3.3 Conventions (apply to every logical table)

1. UUID primary keys: `id uuid primary key default gen_random_uuid()`.
2. Timestamps are `timestamptz`; `created_at timestamptz not null default now()`.
3. Each logical table is created in its owning schema (§3.2). Cross-schema FKs are
   allowed and express reference, never ownership transfer.
4. Status/enum fields use `text` + `check (... in (...))` to keep the catalog-driven
   extensibility the logical model relies on.
5. Money is `numeric(14,2)`; INEGI keys are `text` (preserve leading zeroes).
6. Spatial columns follow §6.5 (geography vs. geometry).
7. Immutable tables and immutable columns are enforced per §11.

These rules deterministically map every logical-model table to physical DDL. §6, §7,
§5, and §11 give full DDL for what this extension **adds or changes**; all other
logical tables are realized 1:1 under these conventions.

---

## 4. Identity: Supabase Auth Bridge

Supabase Auth (`auth.users`) is the identity provider. The application keeps its own
subject record so memberships, audit, and reviewer references stay stable and decoupled
from the auth row.

```sql
create table platform.oidc_subjects (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null unique references auth.users(id) on delete restrict,
    issuer       text,                       -- retained for provenance; null when Supabase is the issuer
    subject      text,                       -- external IdP subject when federated
    display_name text,
    status       text not null default 'active' check (status in ('active','disabled')),
    created_at   timestamptz not null default now(),
    unique (issuer, subject)
);
```

`tenants` and `tenant_memberships` are realized as in the logical model (§4 there),
in `platform`, under the §3.3 conventions. A subject may belong to multiple tenants,
so **tenant context is explicit per request** (§9.2).

---

## 5. Cached Geo-Clip Read Model

**Problem.** Observations are shared and carry **no `tenant_id`**; a tenant sees only
observations whose `location` is inside its **active boundary**. Running
`ST_Intersects(location, boundary)` on every map read — or as an RLS predicate on
every row — is too expensive.

**Decision.** Compute the clip **once** and cache it. The tenant's boundary union is
already materialized and immutable per boundary version
(`geo.tenant_boundary_versions.materialized_geometry`). On top of that, cache the
**result** of clipping the current observation set to that region.

### 5.1 Data-version stamp

A monotonic counter marks each change to the shared *current* observation set, so
caches can be invalidated/rebuilt deterministically. It advances from the vision
outbox (sweep commit, supersession, resolution).

```sql
create table vision.read_model_state (
    only_row     boolean primary key default true check (only_row),
    data_version bigint  not null default 0
);
insert into vision.read_model_state default values;

create or replace function vision.bump_data_version() returns bigint
language sql as $$
    update vision.read_model_state set data_version = data_version + 1
    returning data_version;
$$;
```

### 5.2 Cached visible set (baseline — required)

```sql
create table platform.tenant_visible_observations (
    tenant_id           uuid   not null references platform.tenants(id),
    boundary_version_id uuid   not null references geo.tenant_boundary_versions(id),
    observation_id      uuid   not null references vision.observations(id),
    data_version        bigint not null,
    primary key (tenant_id, observation_id)
);
create index tvo_tenant_ix on platform.tenant_visible_observations (tenant_id);
```

- **Full rebuild** when a tenant boundary version activates: clip the current set to
  the new `materialized_geometry`, stamping the latest `data_version`.
- **Incremental maintenance** as observations enter/leave the current set: the vision
  outbox event (new current / superseded / resolved) tells the worker which tenant
  rows to add or remove. Membership is a single `ST_Contains(boundary, point)` per
  affected observation, not a full scan.

Map and detail reads then join `tenant_visible_observations` for the active tenant —
a cheap indexed join — instead of a spatial intersection.

### 5.3 Precomputed tiles (optional — welcomed optimization)

Built from §5.2 by the worker, vector tiles (`ST_AsMVT`) and the heat/geographies
layers are written to Storage and tracked by a manifest. This removes per-request
geometry from the hot path entirely; it can be deferred without changing the schema.

```sql
create table platform.tenant_tile_sets (
    id                  uuid primary key default gen_random_uuid(),
    tenant_id           uuid   not null references platform.tenants(id),
    boundary_version_id uuid   not null references geo.tenant_boundary_versions(id),
    data_version        bigint not null,
    priority_model_id   uuid,                 -- pinned model for the heat layer
    edition_id          uuid,                 -- pinned INEGI edition for the geographies layer
    storage_bucket      text   not null default 'tenant-tiles',
    storage_prefix      text   not null,      -- '{tenant_id}/{boundary_version_id}/{data_version}/'
    status              text   not null check (status in ('building','ready','stale','failed')),
    checksum            text,
    built_at            timestamptz,
    created_at          timestamptz not null default now(),
    unique (tenant_id, boundary_version_id, data_version)
);
```

This mirrors the architecture spec's tile cache key (tenant + active observation data
version + active priority run + INEGI edition + tile coords).

---

## 6. Observations, Realized

The logical observation entity is realized in `vision` under §3.3, with these
implementation-specific points.

### 6.1 Reference DDL (provenance + media linkage highlighted)

```sql
create table vision.observations (
    id               uuid primary key default gen_random_uuid(),
    schema_version   smallint not null default 1,

    -- fact (immutable)
    observation_type_id uuid not null references vision.observation_types(id),
    location         geography(Point,4326) not null,
    observed_at      timestamptz not null,

    -- provenance (immutable); media handles are now real FKs
    sweep_id         uuid not null references vision.sweeps(id),
    recording_id     uuid references vision.recordings(id),   -- FK, not a dangling handle
    media_offset_ms  integer,                                 -- deterministic seek into recording_id
    frame_ref        text,                                    -- producer's native frame index (provenance)
    image_bbox       jsonb,                                   -- {x,y,w,h} normalized 0..1
    detector_name    text not null,
    detector_version text not null,
    detected_at      timestamptz not null,

    -- lifecycle signals (controlled mutation, §11)
    confirmation_count int not null default 1,
    miss_count         int not null default 0,

    -- supersession / resolution (set-once, §11)
    superseded_by_observation_id uuid references vision.observations(id),
    resolved_at         timestamptz,
    resolution_source   text check (resolution_source in ('human','auto_miss')),
    reviewed_by_subject_id uuid references platform.oidc_subjects(id),

    -- temporal validity
    valid_from       timestamptz not null,
    valid_to         timestamptz,
    created_at       timestamptz not null default now(),

    check (superseded_by_observation_id is null or resolved_at is null),  -- never both
    check (id <> superseded_by_observation_id),                            -- no self-supersession
    check (media_offset_ms is null or media_offset_ms >= 0)
);

create index observations_current_gix on vision.observations
    using gist (location)
    where superseded_by_observation_id is null and resolved_at is null;
create index observations_type_ix  on vision.observations (observation_type_id);
create index observations_sweep_ix on vision.observations (sweep_id);
create index observations_recording_ix on vision.observations (recording_id);
```

There is **no `attributes` column** (§1.2). Typed facts live in
`vision.observation_attribute_values` per the logical model.

### 6.2 Why `recording_id` is nullable

A detection may arrive before its recording row is registered, or from a producer not
yet wired to the shared store. It is nullable so ingest never blocks on media; the
inspect feature is available exactly when the FK is populated. A producer targeting the
shared store SHOULD populate `recording_id` + `media_offset_ms` at ingest.

`recording_id` and `media_offset_ms` are **set-once**: a later media-registration step
may backfill them from null, but neither may be rewritten once set. This preserves the
"provenance is immutable" rule while allowing media to attach after the fact (§11.2).

### 6.3 The inspect-the-sweep flow

```
map pin (observation) → recording_id + media_offset_ms
                      → signed URL into 'sweep-video' (seek to media_offset_ms)
                      → overlay image_bbox on the seeked frame
```

`media_offset_ms` is authoritative for seek; it equals
`observed_at − recording.started_at` and is stored explicitly so playback never has to
recompute it or trust clock skew. `frame_ref` is kept only as producer provenance.

---

## 7. Media / Video Model (`vision`)

### 7.1 `vision.recordings` — the seekable unit

A sweep has **1..N** recordings; a long trash-truck sweep segments into several files,
each covering a contiguous wall-clock window. The recording is the unit a player seeks
within.

```sql
create table vision.recordings (
    id             uuid primary key default gen_random_uuid(),
    sweep_id       uuid not null references vision.sweeps(id),
    storage_bucket text not null default 'sweep-video',
    storage_path   text not null,                  -- 'sweeps/{sweep_id}/{recording_id}.mp4'
    media_type     text not null default 'video/mp4',
    codec          text,
    width          int,
    height         int,
    fps            real,
    started_at     timestamptz not null,           -- wall-clock at first frame
    ended_at       timestamptz not null,
    duration_ms    integer,
    byte_size      bigint,
    checksum       text,
    status         text not null default 'uploading'
                        check (status in ('uploading','ready','failed')),
    created_at     timestamptz not null default now(),
    unique (storage_bucket, storage_path),
    check (ended_at >= started_at)
);
create index recordings_sweep_ix on vision.recordings (sweep_id);
```

An observation maps to its recording by wall-clock containment
(`recording.started_at ≤ observed_at ≤ recording.ended_at`); `media_offset_ms` then
locates the frame. `status` supports resumable (TUS) uploads of large files and a
post-upload "ready" transition once probed.

> Segmentation strategy (single MP4 + byte-range seek vs. HLS chunks) is a capture/
> ingest concern. The model already supports "many recordings per sweep"; HLS would
> add a child `recording_segments` table later without disturbing observation linkage.

### 7.2 `vision.observation_thumbnails` — derived preview

Kept in its own table so `observations` stays immutable. Generated asynchronously after
ingest by the worker.

```sql
create table vision.observation_thumbnails (
    observation_id      uuid primary key references vision.observations(id),
    storage_bucket      text not null default 'observation-thumbnails',
    storage_path        text not null,            -- 'observations/{observation_id}/thumb.jpg'
    width               int,
    height              int,
    source_recording_id uuid references vision.recordings(id),
    source_offset_ms    int,
    bbox                jsonb,                     -- box drawn on the thumbnail
    status              text not null default 'pending'
                            check (status in ('pending','ready','failed')),
    created_at          timestamptz not null default now(),
    unique (storage_bucket, storage_path)
);
```

---

## 8. Object Storage

All buckets are **private**. Access is granted per §9.4.

| Bucket | Contents | Path |
|---|---|---|
| `sweep-video` | Per-sweep recordings | `sweeps/{sweep_id}/{recording_id}.mp4` |
| `observation-thumbnails` | Per-observation previews | `observations/{observation_id}/thumb.jpg` |
| `tenant-tiles` | Precomputed geo-clipped tiles/layers (§5.3) | `{tenant_id}/{boundary_version_id}/{data_version}/...` |

Bucket definitions are infrastructure-as-code in a migration (per-bucket size limit and
MIME allow-list inline):

```sql
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types) values
    ('sweep-video', 'sweep-video', false, 5368709120,                 -- 5 GiB
        array['video/mp4','video/webm','application/x-mpegURL']),
    ('observation-thumbnails', 'observation-thumbnails', false, 5242880,  -- 5 MiB
        array['image/jpeg','image/webp','image/png']),
    ('tenant-tiles', 'tenant-tiles', false, 52428800,                 -- 50 MiB
        array['application/x-protobuf','application/octet-stream','application/json','application/gzip'])
on conflict (id) do update
    set file_size_limit = excluded.file_size_limit,
        allowed_mime_types = excluded.allowed_mime_types;
```

**Required dependency:** a bucket's `file_size_limit` cannot exceed the **global**
storage limit, which is **50 MB on this project**. The `sweep-video` 5 GiB limit only
takes effect after the global limit is raised (§13.4). Large video uses **resumable
(TUS) uploads**.

---

## 9. Authorization (RLS) Model

### 9.1 Roles

Supabase's `authenticated` role is the only client-facing role; the worker uses the
`service_role` key and bypasses RLS. RLS is the **guard** for direct client reads;
the geo-clip cache and signed-URL minting are the primary access paths.

### 9.2 Helper functions

```sql
-- the application subject behind the current JWT
create or replace function platform.current_subject_id() returns uuid
language sql stable security definer set search_path = '' as $$
    select s.id from platform.oidc_subjects s where s.user_id = auth.uid();
$$;

-- the explicitly-selected tenant for this request (set by the API per transaction)
create or replace function platform.active_tenant_id() returns uuid
language sql stable as $$
    select nullif(current_setting('app.tenant_id', true), '')::uuid;
$$;

-- membership + role check (analysis_author implies viewer)
create or replace function platform.is_member(p_tenant uuid, p_min_role text default 'viewer')
returns boolean language sql stable security definer set search_path = '' as $$
    select exists (
        select 1
        from platform.tenant_memberships m
        join platform.oidc_subjects s on s.id = m.subject_id
        where s.user_id = auth.uid()
          and m.tenant_id = p_tenant
          and (p_min_role = 'viewer' or m.role = 'analysis_author')
    );
$$;
```

The API selects a tenant per request with `select set_config('app.tenant_id', :id, true)`
after verifying membership, so a multi-tenant subject never leaks across tenants.

### 9.3 Representative policies

```sql
-- tenant-owned read model: members of the active tenant only
alter table platform.tenant_visible_observations enable row level security;
create policy tvo_read on platform.tenant_visible_observations
    for select to authenticated
    using (tenant_id = platform.active_tenant_id()
           and platform.is_member(tenant_id, 'viewer'));

-- observation detail: only via the active tenant's cached visible set
alter table vision.observations enable row level security;
create policy obs_read on vision.observations
    for select to authenticated
    using (exists (
        select 1 from platform.tenant_visible_observations v
        where v.observation_id = vision.observations.id
          and v.tenant_id = platform.active_tenant_id()
          and platform.is_member(v.tenant_id, 'viewer')
    ));

-- analysis runs: tenant-scoped; authoring requires analysis_author
alter table analysis.analysis_runs enable row level security;
create policy runs_read on analysis.analysis_runs
    for select to authenticated
    using (platform.is_member(tenant_id, 'viewer'));
create policy runs_write on analysis.analysis_runs
    for insert to authenticated
    with check (platform.is_member(tenant_id, 'analysis_author'));
```

Observation reads reuse the cached visible set as their predicate — **the geo clip is
never recomputed at read time**, it is looked up.

### 9.4 Storage access

- **`tenant-tiles`** — Storage RLS by path prefix; pure membership, no geometry:

```sql
create policy tenant_tiles_read on storage.objects
    for select to authenticated
    using (
        bucket_id = 'tenant-tiles'
        and platform.is_member(((storage.foldername(name))[1])::uuid, 'viewer')
    );
```

- **`sweep-video` + `observation-thumbnails`** — the guard is geographic (the
  observation must be in the caller's active boundary), which is awkward in Storage RLS.
  The API calls an authz RPC, then mints a **service-role signed URL** only on success:

```sql
-- PostGIS is installed in `extensions` (§3.1), so ST_Contains and the geometry type
-- resolve via that schema; app tables stay schema-qualified.
create or replace function platform.can_view_observation(p_observation_id uuid)
returns boolean language sql stable security definer set search_path = extensions, public as $$
    select platform.is_member(platform.active_tenant_id(), 'viewer')
       and exists (
            select 1
            from vision.observations o
            join geo.tenant_boundary_versions b
              on b.tenant_id = platform.active_tenant_id()
             and b.status = 'active'
            where o.id = p_observation_id
              and ST_Contains(b.materialized_geometry::geometry, o.location::geometry)
       );
$$;
```

The worker/API resolves `observation → recording_id + media_offset_ms` (or thumbnail
path), confirms `can_view_observation`, and returns a short-lived signed URL.

---

## 10. Queue, Outbox & Worker

The logical `*_outbox_events` tables are realized as-is. Delivery and execution:

- **`pgmq` queues:** `analysis_jobs`, `materialization_jobs`, `thumbnail_jobs`.
- **`pg_cron`** runs a drain function that moves undelivered outbox rows into the
  matching `pgmq` queue (and retries stuck items).
- **Custom worker server** (Node or Python, long-running, `service_role` key) consumes
  the queues:
  - *provider adapter* — loads a frozen run, calls the external optimization provider
    (long calls; this is why a worker, not an Edge Function), validates and persists an
    immutable result attempt;
  - *materialization* — rebuilds `tenant_visible_observations` (and optional tiles) on
    boundary activation / data-version bump;
  - *media* — probes uploaded recordings (`status → ready`) and generates thumbnails.
- **`pg_net`** optionally pings the worker to reduce latency vs. pure cron polling.

```sql
select pgmq.create('analysis_jobs');
select pgmq.create('materialization_jobs');
select pgmq.create('thumbnail_jobs');
```

Consumers treat delivery as at-least-once and dedupe on the outbox event id / run
idempotency key, exactly as the logical model requires.

---

## 11. Immutability & Integrity Enforcement

### 11.1 Strategy

1. **Revoke** `update`/`delete` from `authenticated`/`anon` on factual and frozen-input
   tables; only `service_role` and controlled functions write.
2. **Whitelist triggers** allow only the lifecycle columns to change.
3. **Append-only triggers** on `audit_events` and frozen `run_*` tables reject any
   `update`/`delete`.

### 11.2 Observation lifecycle whitelist

```sql
create or replace function vision.enforce_observation_immutability()
returns trigger language plpgsql as $$
begin
    if (new.observation_type_id, new.location, new.observed_at, new.sweep_id,
        new.frame_ref, new.detector_name, new.detector_version, new.detected_at,
        new.valid_from, new.created_at)
       is distinct from
       (old.observation_type_id, old.location, old.observed_at, old.sweep_id,
        old.frame_ref, old.detector_name, old.detector_version, old.detected_at,
        old.valid_from, old.created_at)
    then
        raise exception 'immutable observation fact/provenance column changed';
    end if;

    -- set-once media linkage (null -> value once, never rewritten)
    if old.recording_id is not null
       and new.recording_id is distinct from old.recording_id then
        raise exception 'recording_id is set-once';
    end if;
    if old.media_offset_ms is not null
       and new.media_offset_ms is distinct from old.media_offset_ms then
        raise exception 'media_offset_ms is set-once';
    end if;

    -- set-once pointers
    if old.superseded_by_observation_id is not null
       and new.superseded_by_observation_id is distinct from old.superseded_by_observation_id then
        raise exception 'superseded_by is set-once';
    end if;
    if old.resolved_at is not null
       and new.resolved_at is distinct from old.resolved_at then
        raise exception 'resolved_at is set-once';
    end if;
    if old.valid_to is not null
       and new.valid_to is distinct from old.valid_to then
        raise exception 'valid_to is set-once';
    end if;
    return new;
end;
$$;

create trigger observations_immutable
    before update on vision.observations
    for each row execute function vision.enforce_observation_immutability();
```

Factual `observation_attribute_values`, frozen `run_observations` /
`run_observation_attributes` / `run_priority_values`, and `audit_events` get a simpler
`raise exception` on `update`/`delete`. The remaining logical invariants in its §11
(priority pointer consistency, single active edition/boundary/model, scope containment,
attempt-number uniqueness, one accepted result) are realized as `check`, partial
`unique` indexes, and FK constraints under §3.3.

---

## 12. Migration & Delivery Order

Supabase migrations under `supabase/migrations/`, applied in dependency order:

1. Extensions + schemas + Supabase Auth bridge (`oidc_subjects`).
2. `platform` tenants + memberships.
3. `vision` catalog, attribute definitions/options, sweeps, **recordings**.
4. `vision` observations, typed values, **thumbnails**, supersession/miss fields.
5. `priority` models, batches, values, current pointers.
6. `geo` editions, areas, bindings, versioned tenant boundaries.
7. `analysis` providers, definitions, capability snapshots, runs, scopes.
8. Frozen run inputs + exclusions.
9. Outbox tables + `pgmq` queues + `pg_cron` jobs.
10. RLS policies + immutability triggers + Storage buckets/policies.
11. Read-model cache: `read_model_state`, `tenant_visible_observations`,
    `tenant_tile_sets`, and materialization wiring.

Each stage is one or more files under `supabase/migrations/` (§13.1), authored with
`supabase migration new` and applied with `supabase db reset` (local) / `supabase db push`
(remote). Each stage preserves domain ownership and exposes stable identifiers to the next.

---

## 13. Monorepo Layout, Infrastructure-as-Code & Setup

The database and object storage are **shared infrastructure** (per the system
architecture: vision, priority, geo, analysis, and the map client all depend on them).
They therefore live in **one** place at the repo root, managed entirely through the
**Supabase CLI** — the existing, reproducible mechanism for migrations and IaC. Nothing
in this design requires click-ops that isn't also captured as code.

### 13.1 Placement in the monorepo

```
/ (repo root)
├─ supabase/                     # single source of truth for shared DB + Storage (IaC)
│  ├─ config.toml                # declarative project + local-stack config
│  ├─ migrations/                # ordered SQL migrations (§12), one+ file per stage
│  │   ├─ 0001_extensions_schemas_auth.sql
│  │   ├─ 0002_platform_tenants.sql
│  │   └─ ...                     # through 0011_read_model_cache.sql
│  └─ seed.sql                   # replicable seed: type catalog, dev tenant, fixtures
├─ services/
│  └─ worker/                    # custom worker server (service_role): queues, signed URLs, materialization
│     └─ .env.example            # SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY (real .env not committed)
├─ packages/
│  └─ db-types/                  # generated TypeScript types (supabase gen types)
└─ ...                           # other modules (vision, priority, map client) depend on the above
```

Module application code stays in its own package; **schema ownership** (§3.2) is enforced
inside the one database, not by splitting the migrations across packages — that keeps the
dependency-ordered migration history (§12) linear and replayable.

### 13.2 IaC mechanism

Everything is code and committed:

- `supabase/migrations/*.sql` — schema, RLS, triggers, Storage buckets, `pgmq` queues,
  and `pg_cron` jobs (all the DDL in this spec).
- `supabase/config.toml` — Postgres major version, `[storage] file_size_limit`, and
  `[auth]` settings; gives local/remote parity.
- `supabase/seed.sql` — deterministic seed data.

`supabase db reset` rebuilds the **entire** database from `migrations/` + `seed.sql`, so
any contributor reproduces an identical environment; `supabase db push` applies the same
migrations to the linked remote project. No schema change is ever made by hand.

### 13.3 Setup commands

```bash
# 1. Install the CLI (existing mechanism)
brew install supabase/tap/supabase        # or run any command below as: npx supabase <cmd>

# 2. From repo root, link to the project
supabase link --project-ref joixzhdpnxqhnuscxsoy

# 3. Local dev: start the full stack, then build the DB from code
supabase start
supabase db reset                          # applies migrations/ + seed.sql deterministically

# 4. Author a new migration during development
supabase migration new <description>       # creates supabase/migrations/<ts>_<description>.sql

# 5. Apply migrations to the linked remote
supabase db push

# 6. Regenerate typed DB client for app modules
supabase gen types typescript --linked > packages/db-types/database.ts
```

### 13.4 Required project settings (one-time, captured as config)

- **Raise the global Storage file-size limit.** It is **50 MB** today; sweep video needs
  more (the `sweep-video` bucket requests 5 GiB, §8). Set `[storage] file_size_limit`
  in `config.toml` for local parity and apply the same value to the remote project
  (`supabase config push` where supported, otherwise Storage settings / management API;
  the Supabase MCP `update_storage_config` can apply it on request). Per-bucket limits
  cannot exceed this global value.
- **Auth providers** are configured under `[auth]` in `config.toml`. Tenant context is
  carried by a per-request GUC (`app.tenant_id`, §9.2), so **no custom JWT access-token
  hook is required** — one less manual step.
- **Worker credentials:** `services/worker` reads `SUPABASE_URL` and
  `SUPABASE_SERVICE_ROLE_KEY` from its environment (documented in `.env.example`, real
  values uncommitted). The service-role key bypasses RLS and must never reach a client.

### 13.5 Seed data (`seed.sql`)

For a working local map after `supabase db reset`: the `observation_types` catalog with
their attribute definitions, one active `priority_model`, and a dev tenant with a small
INEGI edition fixture and an active boundary. This makes the geo-clip cache and inspect
flow exercisable locally without the upstream capture/vision pipeline.

## 14. Testing & Acceptance (Supabase-specific)

In addition to the logical model's acceptance scenarios:

- **Auth bridge:** a Supabase user with no `oidc_subjects` row has no tenant access;
  creating the bridge row grants exactly its memberships.
- **Tenant isolation:** with `app.tenant_id` set to tenant A, observation/detail/run
  reads return only A's data; switching the GUC to B (same JWT) flips visibility;
  unset GUC returns nothing.
- **Geo-clip cache correctness:** `tenant_visible_observations` for a boundary equals a
  fresh `ST_Contains` clip of the current set; activating a new boundary rebuilds it;
  superseding/resolving an observation removes it incrementally; a new current
  observation inside the boundary adds it.
- **Inspect flow:** an observation with `recording_id` yields a signed URL that seeks to
  `media_offset_ms`; `can_view_observation` denies an out-of-boundary observation.
- **Storage policy:** a member of tenant A can read `tenant-tiles/A/...` and not
  `tenant-tiles/B/...`; video/thumbnail access requires a successful authz RPC.
- **Immutability:** updating any whitelisted-out observation column, or re-setting a
  set-once pointer, raises; `audit_events`/frozen `run_*` reject update/delete.
- **Queue idempotency:** redelivering an `analysis_jobs` message accepts at most one
  result; a failed materialization leaves the prior cache/tiles intact.

---

## 15. Deferred / Out of Scope

- Capture/ingest implementation, video transcoding/segmentation (HLS), and thumbnail
  rendering internals (only their schema hooks and statuses are here).
- The worker server's language, framework, and deployment topology.
- Optimization, costing, routing, and clustering algorithms (provider-owned).
- Tile rendering/styling and the map client.
- Natural-language drafting model and prompt design.
- Applying the global Storage upload-limit change to the remote project (the value and
  mechanism are specified in §13.4; no JWT custom-claim hook is needed).
- Historical map playback UI (records retained, UI deferred).
