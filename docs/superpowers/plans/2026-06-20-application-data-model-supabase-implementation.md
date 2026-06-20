# Application Data Model — Supabase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the entire application data model — all five domains plus shared media/video, the cached geo-clip read model, RLS, object storage, and the async queue — as reproducible Supabase CLI migrations.

**Architecture:** One Postgres database with five ownership schemas (`platform`, `vision`, `priority`, `geo`, `analysis`); media lives in `vision`; the tenant read-model cache lives in `platform`. PostGIS is in the `extensions` schema. Everything is infrastructure-as-code under `supabase/migrations/` + `config.toml` + `seed.sql`, rebuilt deterministically with `supabase db reset`. Tenant visibility is a *cached* geo-clip (`platform.tenant_visible_observations`), never a per-read spatial scan.

**Tech Stack:** Supabase (Postgres 15, PostGIS 3.3, `pgmq`, `pg_cron`, `pg_net`), Supabase Auth, Supabase Storage, Supabase CLI. Tests are plain-SQL assertion scripts run with `psql`.

## Global Constraints

Every task implicitly includes these (copied from the spec):

- **Source of truth:** the logical model `docs/superpowers/specs/2026-06-20-application-data-model-design.md` + the physical spec `docs/superpowers/specs/2026-06-20-application-data-model-supabase-implementation-design.md`.
- **Project ref:** `joixzhdpnxqhnuscxsoy`. Local DB URL: `postgresql://postgres:postgres@127.0.0.1:54322/postgres`.
- **Schemas:** `platform`, `vision`, `priority`, `geo`, `analysis`. Media (recordings, thumbnails) lives in `vision`. The read-model cache lives in `platform`.
- **PostGIS in `extensions`.** Any function calling PostGIS sets `search_path = extensions, public`. Security-definer functions that don't touch PostGIS set `search_path = ''` and fully schema-qualify.
- **Identifiers:** `id uuid primary key default gen_random_uuid()` (core function; no pgcrypto call needed). Timestamps are `timestamptz`; `created_at timestamptz not null default now()`.
- **Enums** are `text` + `check (... in (...))`. **Money** is `numeric(14,2)`. **INEGI keys** are `text` (preserve leading zeroes).
- **No `attributes` JSONB on observations** — typed `vision.observation_attribute_*` tables instead.
- **Immutability:** observation facts/provenance never change; `recording_id`/`media_offset_ms` are set-once; only lifecycle columns mutate (enforced by trigger in Task 12). `audit_events` and frozen `run_*` tables are append-only.
- **Geo-clip is cached, never recomputed on the hot path.**
- **Storage:** buckets are private; the global Storage size limit (50 MB today) must be raised before `sweep-video` uploads succeed.
- **Migrations** are authored with `supabase migration new` and applied with `supabase db reset` (local). Filenames below use a `NNNN_` prefix for readability; the CLI's timestamp prefix is equivalent.
- **Test loop per task:** write the assertion script → run it (red) → write the migration → `supabase db reset` → run the assertion script (green) → commit. Run scripts with:
  `psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f supabase/tests/<file>`
  A failed `assert` raises and exits non-zero (red); clean exit is green.

---

### Task 1: Project scaffolding, extensions & schemas

**Files:**
- Create: `supabase/config.toml`
- Create: `supabase/migrations/0001_extensions_schemas.sql`
- Test: `supabase/tests/0001_extensions_schemas.test.sql`

**Interfaces:**
- Consumes: nothing.
- Produces: schemas `platform`, `vision`, `priority`, `geo`, `analysis`; extensions `postgis` (in `extensions`), `pgmq`, `pg_cron`, `pg_net`.

- [ ] **Step 1: Initialize the Supabase project and set storage parity in config**

Run:
```bash
supabase init                 # creates supabase/ if absent; commit the result
supabase link --project-ref joixzhdpnxqhnuscxsoy
```
Then in `supabase/config.toml` set local/remote parity for large video:
```toml
[storage]
file_size_limit = "5GiB"
```

- [ ] **Step 2: Write the failing assertion test**

```sql
-- supabase/tests/0001_extensions_schemas.test.sql
do $$
begin
  assert (select count(*) from information_schema.schemata
          where schema_name in ('platform','vision','priority','geo','analysis')) = 5,
    'expected 5 domain schemas';
  assert (select count(*) from pg_extension where extname = 'postgis') = 1, 'postgis missing';
  assert (select count(*) from pg_extension where extname = 'pgmq') = 1, 'pgmq missing';
  assert (select count(*) from pg_extension where extname = 'pg_cron') = 1, 'pg_cron missing';
  assert (select count(*) from pg_extension where extname = 'pg_net') = 1, 'pg_net missing';
end $$;
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `supabase start && psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f supabase/tests/0001_extensions_schemas.test.sql`
Expected: FAIL — assertion `expected 5 domain schemas`.

- [ ] **Step 4: Write the migration**

```sql
-- supabase/migrations/0001_extensions_schemas.sql
create extension if not exists postgis with schema extensions;
create extension if not exists pgmq;     -- manages its own pgmq schema
create extension if not exists pg_cron;  -- manages its own cron schema
create extension if not exists pg_net;   -- exposes the net schema

create schema if not exists platform;
create schema if not exists vision;
create schema if not exists priority;
create schema if not exists geo;
create schema if not exists analysis;
```

- [ ] **Step 5: Apply and verify the test passes**

Run: `supabase db reset && psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f supabase/tests/0001_extensions_schemas.test.sql`
Expected: PASS (no output, exit 0).

- [ ] **Step 6: Commit**

```bash
git add supabase/config.toml supabase/migrations/0001_extensions_schemas.sql supabase/tests/0001_extensions_schemas.test.sql
git commit -m "feat(db): extensions and domain schemas"
```

---

### Task 2: Platform identities, memberships, audit & RLS helpers

**Files:**
- Create: `supabase/migrations/0002_platform.sql`
- Test: `supabase/tests/0002_platform.test.sql`

**Interfaces:**
- Consumes: Task 1 schemas; `auth.users` (Supabase Auth).
- Produces: `platform.tenants(id)`, `platform.oidc_subjects(id, user_id)`, `platform.tenant_memberships(tenant_id, subject_id, role)`, `platform.audit_events`; functions `platform.current_subject_id() -> uuid`, `platform.active_tenant_id() -> uuid`, `platform.is_member(p_tenant uuid, p_min_role text) -> boolean`.

- [ ] **Step 1: Write the failing assertion test**

```sql
-- supabase/tests/0002_platform.test.sql
do $$
begin
  assert to_regclass('platform.tenants') is not null, 'platform.tenants missing';
  assert to_regclass('platform.oidc_subjects') is not null, 'platform.oidc_subjects missing';
  assert to_regclass('platform.tenant_memberships') is not null, 'platform.tenant_memberships missing';
  assert to_regclass('platform.audit_events') is not null, 'platform.audit_events missing';
  -- unique (issuer, subject)
  assert exists (select 1 from pg_constraint
    where conrelid = 'platform.oidc_subjects'::regclass and contype = 'u'
      and conkey @> array[
        (select attnum from pg_attribute where attrelid='platform.oidc_subjects'::regclass and attname='issuer'),
        (select attnum from pg_attribute where attrelid='platform.oidc_subjects'::regclass and attname='subject')
      ]::smallint[]), 'unique(issuer,subject) missing';
  -- helper functions exist
  assert to_regprocedure('platform.is_member(uuid,text)') is not null, 'is_member missing';
  assert to_regprocedure('platform.active_tenant_id()') is not null, 'active_tenant_id missing';
end $$;
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f supabase/tests/0002_platform.test.sql`
Expected: FAIL — `platform.tenants missing`.

- [ ] **Step 3: Write the migration**

```sql
-- supabase/migrations/0002_platform.sql
create table platform.tenants (
    id         uuid primary key default gen_random_uuid(),
    name       text not null,
    status     text not null default 'active' check (status in ('active','disabled')),
    created_at timestamptz not null default now()
);

create table platform.oidc_subjects (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null unique references auth.users(id) on delete restrict,
    issuer       text,
    subject      text,
    display_name text,
    status       text not null default 'active' check (status in ('active','disabled')),
    created_at   timestamptz not null default now(),
    unique (issuer, subject)
);

create table platform.tenant_memberships (
    tenant_id  uuid not null references platform.tenants(id) on delete cascade,
    subject_id uuid not null references platform.oidc_subjects(id) on delete cascade,
    role       text not null check (role in ('viewer','analysis_author')),
    created_at timestamptz not null default now(),
    primary key (tenant_id, subject_id)
);
create index tenant_memberships_subject_ix on platform.tenant_memberships (subject_id);

create table platform.audit_events (
    id              uuid primary key default gen_random_uuid(),
    tenant_id       uuid references platform.tenants(id),
    actor_subject_id uuid references platform.oidc_subjects(id),
    module          text not null,
    action          text not null,
    target_type     text,
    target_id       uuid,
    occurred_at     timestamptz not null default now(),
    details         jsonb not null default '{}'::jsonb
);
create index audit_events_tenant_ix on platform.audit_events (tenant_id, occurred_at);

-- RLS helper functions (immutable-search-path security definer)
create or replace function platform.current_subject_id() returns uuid
language sql stable security definer set search_path = '' as $$
    select s.id from platform.oidc_subjects s where s.user_id = auth.uid();
$$;

create or replace function platform.active_tenant_id() returns uuid
language sql stable as $$
    select nullif(current_setting('app.tenant_id', true), '')::uuid;
$$;

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

- [ ] **Step 4: Apply and verify the test passes**

Run: `supabase db reset && psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f supabase/tests/0002_platform.test.sql`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/0002_platform.sql supabase/tests/0002_platform.test.sql
git commit -m "feat(db): platform identities, memberships, audit, RLS helpers"
```

---

### Task 3: Vision catalog, sweeps & recordings

**Files:**
- Create: `supabase/migrations/0003_vision_catalog.sql`
- Test: `supabase/tests/0003_vision_catalog.test.sql`

**Interfaces:**
- Consumes: Task 1 schemas.
- Produces: `vision.sources(id,slug)`, `vision.observation_types(id,slug)`, `vision.observation_attribute_definitions(id)`, `vision.observation_attribute_options(id)`, `vision.sweeps(id, coverage geography)`, `vision.sweep_assessed_types(sweep_id, observation_type_id)`, `vision.recordings(id, sweep_id, started_at, ended_at)`.

- [ ] **Step 1: Write the failing assertion test**

```sql
-- supabase/tests/0003_vision_catalog.test.sql
do $$
begin
  assert to_regclass('vision.sources') is not null, 'vision.sources missing';
  assert to_regclass('vision.observation_types') is not null, 'vision.observation_types missing';
  assert to_regclass('vision.observation_attribute_definitions') is not null, 'attr defs missing';
  assert to_regclass('vision.observation_attribute_options') is not null, 'attr options missing';
  assert to_regclass('vision.sweeps') is not null, 'vision.sweeps missing';
  assert to_regclass('vision.sweep_assessed_types') is not null, 'sweep_assessed_types missing';
  assert to_regclass('vision.recordings') is not null, 'vision.recordings missing';
  -- coverage is geography
  assert (select format_type(atttypid, atttypmod) from pg_attribute
          where attrelid='vision.sweeps'::regclass and attname='coverage') like 'geography%',
    'sweeps.coverage must be geography';
  -- value_kind constraint present
  assert exists (select 1 from pg_constraint
    where conrelid='vision.observation_attribute_definitions'::regclass and contype='c'
      and pg_get_constraintdef(oid) ilike '%value_kind%'), 'value_kind check missing';
end $$;
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f supabase/tests/0003_vision_catalog.test.sql`
Expected: FAIL — `vision.sources missing`.

- [ ] **Step 3: Write the migration**

```sql
-- supabase/migrations/0003_vision_catalog.sql
create table vision.sources (
    id         uuid primary key default gen_random_uuid(),
    slug       text not null unique,
    name       text not null,
    status     text not null default 'active' check (status in ('active','retired')),
    created_at timestamptz not null default now()
);

create table vision.observation_types (
    id                          uuid primary key default gen_random_uuid(),
    slug                        text not null unique,
    label                       text not null,
    category                    text not null,
    description                 text,
    merge_radius_m              real not null default 10,
    auto_resolvable             boolean not null default true,
    auto_resolve_miss_threshold int,
    status                      text not null default 'active' check (status in ('active','retired'))
);

create table vision.observation_attribute_definitions (
    id                  uuid primary key default gen_random_uuid(),
    observation_type_id uuid not null references vision.observation_types(id),
    key                 text not null,
    version             int  not null default 1,
    label               text not null,
    value_kind          text not null check (value_kind in ('number','text','boolean','option')),
    unit                text,
    required            boolean not null default false,
    minimum_number      numeric,
    maximum_number      numeric,
    status              text not null default 'active' check (status in ('active','retired')),
    unique (observation_type_id, key, version)
);
-- at most one active version per (type, key)
create unique index observation_attr_def_active_ux
    on vision.observation_attribute_definitions (observation_type_id, key)
    where status = 'active';

create table vision.observation_attribute_options (
    id            uuid primary key default gen_random_uuid(),
    definition_id uuid not null references vision.observation_attribute_definitions(id),
    code          text not null,
    label         text not null,
    status        text not null default 'active' check (status in ('active','retired')),
    unique (definition_id, code)
);

create table vision.sweeps (
    id         uuid primary key default gen_random_uuid(),
    source_id  uuid not null references vision.sources(id),
    coverage   geography not null,
    started_at timestamptz not null,
    ended_at   timestamptz not null,
    created_at timestamptz not null default now(),
    check (ended_at >= started_at)
);
create index sweeps_coverage_gix on vision.sweeps using gist (coverage);
create index sweeps_source_ix on vision.sweeps (source_id);

create table vision.sweep_assessed_types (
    sweep_id            uuid not null references vision.sweeps(id) on delete cascade,
    observation_type_id uuid not null references vision.observation_types(id),
    primary key (sweep_id, observation_type_id)
);

create table vision.recordings (
    id             uuid primary key default gen_random_uuid(),
    sweep_id       uuid not null references vision.sweeps(id),
    storage_bucket text not null default 'sweep-video',
    storage_path   text not null,
    media_type     text not null default 'video/mp4',
    codec          text,
    width          int,
    height         int,
    fps            real,
    started_at     timestamptz not null,
    ended_at       timestamptz not null,
    duration_ms    integer,
    byte_size      bigint,
    checksum       text,
    status         text not null default 'uploading' check (status in ('uploading','ready','failed')),
    created_at     timestamptz not null default now(),
    unique (storage_bucket, storage_path),
    check (ended_at >= started_at)
);
create index recordings_sweep_ix on vision.recordings (sweep_id);
```

- [ ] **Step 4: Apply and verify the test passes**

Run: `supabase db reset && psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f supabase/tests/0003_vision_catalog.test.sql`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/0003_vision_catalog.sql supabase/tests/0003_vision_catalog.test.sql
git commit -m "feat(db): vision catalog, sweeps, recordings"
```

---

### Task 4: Observations, typed values & thumbnails

**Files:**
- Create: `supabase/migrations/0004_observations.sql`
- Test: `supabase/tests/0004_observations.test.sql`

**Interfaces:**
- Consumes: `vision.observation_types`, `vision.sweeps`, `vision.recordings`, `vision.observation_attribute_definitions`, `vision.observation_attribute_options`, `platform.oidc_subjects`.
- Produces: `vision.observations(id, recording_id, media_offset_ms, superseded_by_observation_id, resolved_at, valid_to, confirmation_count, miss_count)`, `vision.observation_attribute_values(observation_id, definition_id)`, `vision.observation_thumbnails(observation_id)`.

- [ ] **Step 1: Write the failing assertion test**

```sql
-- supabase/tests/0004_observations.test.sql
do $$
begin
  assert to_regclass('vision.observations') is not null, 'vision.observations missing';
  assert to_regclass('vision.observation_attribute_values') is not null, 'attr values missing';
  assert to_regclass('vision.observation_thumbnails') is not null, 'thumbnails missing';
  -- NO attributes column
  assert not exists (select 1 from pg_attribute
    where attrelid='vision.observations'::regclass and attname='attributes' and not attisdropped),
    'observations must NOT have an attributes column';
  -- recording_id is a real FK to vision.recordings
  assert exists (select 1 from pg_constraint c
    where c.conrelid='vision.observations'::regclass and c.contype='f'
      and c.confrelid='vision.recordings'::regclass), 'recording_id FK missing';
  -- media_offset_ms exists
  assert exists (select 1 from pg_attribute
    where attrelid='vision.observations'::regclass and attname='media_offset_ms'),
    'media_offset_ms missing';
end $$;
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f supabase/tests/0004_observations.test.sql`
Expected: FAIL — `vision.observations missing`.

- [ ] **Step 3: Write the migration**

```sql
-- supabase/migrations/0004_observations.sql
create table vision.observations (
    id               uuid primary key default gen_random_uuid(),
    schema_version   smallint not null default 1,

    observation_type_id uuid not null references vision.observation_types(id),
    location         geography(Point,4326) not null,
    observed_at      timestamptz not null,

    sweep_id         uuid not null references vision.sweeps(id),
    recording_id     uuid references vision.recordings(id),
    media_offset_ms  integer,
    frame_ref        text,
    image_bbox       jsonb,
    detector_name    text not null,
    detector_version text not null,
    detected_at      timestamptz not null,

    confirmation_count int not null default 1,
    miss_count         int not null default 0,

    superseded_by_observation_id uuid references vision.observations(id),
    resolved_at         timestamptz,
    resolution_source   text check (resolution_source in ('human','auto_miss')),
    reviewed_by_subject_id uuid references platform.oidc_subjects(id),

    valid_from       timestamptz not null,
    valid_to         timestamptz,
    created_at       timestamptz not null default now(),

    check (superseded_by_observation_id is null or resolved_at is null),
    check (id <> superseded_by_observation_id),
    check (media_offset_ms is null or media_offset_ms >= 0)
);
create index observations_current_gix on vision.observations
    using gist (location)
    where superseded_by_observation_id is null and resolved_at is null;
create index observations_type_ix  on vision.observations (observation_type_id);
create index observations_sweep_ix on vision.observations (sweep_id);
create index observations_recording_ix on vision.observations (recording_id);

create table vision.observation_attribute_values (
    observation_id uuid not null references vision.observations(id),
    definition_id  uuid not null references vision.observation_attribute_definitions(id),
    number_value   numeric,
    text_value     text,
    boolean_value  boolean,
    option_id      uuid references vision.observation_attribute_options(id),
    created_at     timestamptz not null default now(),
    primary key (observation_id, definition_id),
    check (num_nonnulls(number_value, text_value, boolean_value, option_id) = 1)
);

create table vision.observation_thumbnails (
    observation_id      uuid primary key references vision.observations(id),
    storage_bucket      text not null default 'observation-thumbnails',
    storage_path        text not null,
    width               int,
    height              int,
    source_recording_id uuid references vision.recordings(id),
    source_offset_ms    int,
    bbox                jsonb,
    status              text not null default 'pending' check (status in ('pending','ready','failed')),
    created_at          timestamptz not null default now(),
    unique (storage_bucket, storage_path)
);
```

- [ ] **Step 4: Apply and verify the test passes**

Run: `supabase db reset && psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f supabase/tests/0004_observations.test.sql`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/0004_observations.sql supabase/tests/0004_observations.test.sql
git commit -m "feat(db): observations, typed attribute values, thumbnails"
```

---

### Task 5: Priority models, batches & values

**Files:**
- Create: `supabase/migrations/0005_priority.sql`
- Test: `supabase/tests/0005_priority.test.sql`

**Interfaces:**
- Consumes: `vision.observations`, `vision.sweeps`.
- Produces: `priority.priority_models(id)`, `priority.priority_batches(id)`, `priority.priority_batch_items(batch_id, observation_id)`, `priority.priority_values(id, value_state, inherited_from_value_id, computed_by_batch_id)`, `priority.current_priority_values(observation_id, model_id, priority_value_id)`.

- [ ] **Step 1: Write the failing assertion test**

```sql
-- supabase/tests/0005_priority.test.sql
do $$
begin
  assert to_regclass('priority.priority_models') is not null, 'priority_models missing';
  assert to_regclass('priority.priority_batches') is not null, 'priority_batches missing';
  assert to_regclass('priority.priority_batch_items') is not null, 'priority_batch_items missing';
  assert to_regclass('priority.priority_values') is not null, 'priority_values missing';
  assert to_regclass('priority.current_priority_values') is not null, 'current_priority_values missing';
  -- only one active model allowed (partial unique index)
  assert exists (select 1 from pg_indexes where schemaname='priority'
    and indexname='priority_models_active_ux'), 'single-active-model index missing';
end $$;
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f supabase/tests/0005_priority.test.sql`
Expected: FAIL — `priority_models missing`.

- [ ] **Step 3: Write the migration**

```sql
-- supabase/migrations/0005_priority.sql
create table priority.priority_models (
    id         uuid primary key default gen_random_uuid(),
    name       text not null,
    version    text not null,
    status     text not null default 'active' check (status in ('active','retired')),
    created_at timestamptz not null default now(),
    unique (name, version)
);
create unique index priority_models_active_ux on priority.priority_models ((true)) where status = 'active';

create table priority.priority_batches (
    id               uuid primary key default gen_random_uuid(),
    model_id         uuid not null references priority.priority_models(id),
    trigger_sweep_id uuid references vision.sweeps(id),
    reason           text not null check (reason in ('new_sweep','model_refresh','manual')),
    status           text not null default 'queued'
                          check (status in ('queued','running','completed','completed_with_errors','failed')),
    created_at       timestamptz not null default now(),
    started_at       timestamptz,
    completed_at     timestamptz
);

create table priority.priority_batch_items (
    batch_id       uuid not null references priority.priority_batches(id) on delete cascade,
    observation_id uuid not null references vision.observations(id),
    status         text not null default 'pending' check (status in ('pending','running','completed','failed')),
    failure_code   text,
    updated_at     timestamptz not null default now(),
    primary key (batch_id, observation_id)
);

create table priority.priority_values (
    id                      uuid primary key default gen_random_uuid(),
    observation_id          uuid not null references vision.observations(id),
    model_id                uuid not null references priority.priority_models(id),
    weight                  numeric not null,
    value_state             text not null check (value_state in ('computed','inherited')),
    inherited_from_value_id uuid references priority.priority_values(id),
    computed_by_batch_id    uuid references priority.priority_batches(id),
    created_at              timestamptz not null default now(),
    check ((value_state = 'inherited' and inherited_from_value_id is not null)
        or (value_state = 'computed'  and computed_by_batch_id is not null))
);
create index priority_values_obs_model_ix on priority.priority_values (observation_id, model_id);

create table priority.current_priority_values (
    observation_id    uuid not null references vision.observations(id),
    model_id          uuid not null references priority.priority_models(id),
    priority_value_id uuid not null references priority.priority_values(id),
    updated_at        timestamptz not null default now(),
    primary key (observation_id, model_id)
);
```

- [ ] **Step 4: Apply and verify the test passes**

Run: `supabase db reset && psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f supabase/tests/0005_priority.test.sql`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/0005_priority.sql supabase/tests/0005_priority.test.sql
git commit -m "feat(db): priority models, batches, values, current pointers"
```

---

### Task 6: INEGI geography & tenant boundaries

**Files:**
- Create: `supabase/migrations/0006_geo.sql`
- Test: `supabase/tests/0006_geo.test.sql`

**Interfaces:**
- Consumes: `platform.tenants`, `vision.observations`.
- Produces: `geo.geo_editions(id)`, `geo.geo_areas(id, geometry)`, `geo.tenant_boundary_versions(id, tenant_id, materialized_geometry)`, `geo.tenant_boundary_areas(boundary_version_id, geo_area_id)`, `geo.observation_geo_bindings(observation_id, edition_id)`.

- [ ] **Step 1: Write the failing assertion test**

```sql
-- supabase/tests/0006_geo.test.sql
do $$
begin
  assert to_regclass('geo.geo_editions') is not null, 'geo_editions missing';
  assert to_regclass('geo.geo_areas') is not null, 'geo_areas missing';
  assert to_regclass('geo.tenant_boundary_versions') is not null, 'tenant_boundary_versions missing';
  assert to_regclass('geo.tenant_boundary_areas') is not null, 'tenant_boundary_areas missing';
  assert to_regclass('geo.observation_geo_bindings') is not null, 'observation_geo_bindings missing';
  -- geo_areas.geometry is a PostGIS geometry
  assert (select format_type(atttypid, atttypmod) from pg_attribute
          where attrelid='geo.geo_areas'::regclass and attname='geometry') like 'geometry%',
    'geo_areas.geometry must be geometry';
  -- one active boundary per tenant
  assert exists (select 1 from pg_indexes where schemaname='geo'
    and indexname='tenant_boundary_active_ux'), 'single-active-boundary index missing';
end $$;
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f supabase/tests/0006_geo.test.sql`
Expected: FAIL — `geo_editions missing`.

- [ ] **Step 3: Write the migration**

```sql
-- supabase/migrations/0006_geo.sql
create table geo.geo_editions (
    id             uuid primary key default gen_random_uuid(),
    source_name    text not null,
    source_release text not null,
    effective_date date,
    checksum       text,
    status         text not null default 'importing'
                        check (status in ('importing','ready','active','failed','retired')),
    imported_at    timestamptz
);
create unique index geo_editions_active_ux on geo.geo_editions ((true)) where status = 'active';

create table geo.geo_areas (
    id             uuid primary key default gen_random_uuid(),
    edition_id     uuid not null references geo.geo_editions(id),
    level          text not null check (level in ('AGEE','AGEM','AGEB')),
    source_cvegeo  text not null,
    cve_ent        text,
    cve_mun        text,
    cve_loc        text,
    cve_ageb       text,
    name           text,
    ageb_kind      text check (ageb_kind in ('urban','rural')),
    parent_area_id uuid references geo.geo_areas(id),
    geometry       geometry(MultiPolygon,4326) not null,
    unique (edition_id, level, source_cvegeo)
);
create index geo_areas_geom_gix on geo.geo_areas using gist (geometry);
create index geo_areas_parent_ix on geo.geo_areas (parent_area_id);

create table geo.tenant_boundary_versions (
    id                   uuid primary key default gen_random_uuid(),
    tenant_id            uuid not null references platform.tenants(id),
    edition_id           uuid not null references geo.geo_editions(id),
    version_number       int  not null,
    status               text not null default 'draft' check (status in ('draft','active','retired')),
    materialized_geometry geometry(MultiPolygon,4326),
    geometry_checksum    text,
    created_at           timestamptz not null default now(),
    activated_at         timestamptz,
    unique (tenant_id, version_number)
);
create unique index tenant_boundary_active_ux
    on geo.tenant_boundary_versions (tenant_id) where status = 'active';
create index tenant_boundary_geom_gix
    on geo.tenant_boundary_versions using gist (materialized_geometry);

create table geo.tenant_boundary_areas (
    boundary_version_id uuid not null references geo.tenant_boundary_versions(id) on delete cascade,
    geo_area_id         uuid not null references geo.geo_areas(id),
    primary key (boundary_version_id, geo_area_id)
);

create table geo.observation_geo_bindings (
    observation_id uuid not null references vision.observations(id),
    edition_id     uuid not null references geo.geo_editions(id),
    agee_area_id   uuid references geo.geo_areas(id),
    agem_area_id   uuid references geo.geo_areas(id),
    ageb_area_id   uuid references geo.geo_areas(id),
    bound_at       timestamptz not null default now(),
    primary key (observation_id, edition_id)
);
```

- [ ] **Step 4: Apply and verify the test passes**

Run: `supabase db reset && psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f supabase/tests/0006_geo.test.sql`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/0006_geo.sql supabase/tests/0006_geo.test.sql
git commit -m "feat(db): INEGI editions, areas, tenant boundaries, bindings"
```

---

### Task 7: Analysis definitions, runs, scope & type settings

**Files:**
- Create: `supabase/migrations/0007_analysis_definitions_runs.sql`
- Test: `supabase/tests/0007_analysis_definitions_runs.test.sql`

**Interfaces:**
- Consumes: `platform.tenants`, `platform.oidc_subjects`, `geo.tenant_boundary_versions`, `geo.geo_editions`, `geo.geo_areas`, `vision.observation_types`.
- Produces: `analysis.analysis_providers(id)`, `analysis.analysis_definitions(id, kind)`, `analysis.analysis_definition_versions(id)`, `analysis.provider_capability_snapshots(id)`, `analysis.analysis_runs(id, tenant_id, idempotency_key, status)`, `analysis.run_scope_areas(run_id, geo_area_id)`, `analysis.run_scope_geometry(run_id)`, `analysis.run_type_settings(run_id, observation_type_id)`.

- [ ] **Step 1: Write the failing assertion test**

```sql
-- supabase/tests/0007_analysis_definitions_runs.test.sql
do $$
begin
  assert to_regclass('analysis.analysis_providers') is not null, 'analysis_providers missing';
  assert to_regclass('analysis.analysis_definitions') is not null, 'analysis_definitions missing';
  assert to_regclass('analysis.analysis_definition_versions') is not null, 'definition_versions missing';
  assert to_regclass('analysis.provider_capability_snapshots') is not null, 'capability_snapshots missing';
  assert to_regclass('analysis.analysis_runs') is not null, 'analysis_runs missing';
  assert to_regclass('analysis.run_scope_areas') is not null, 'run_scope_areas missing';
  assert to_regclass('analysis.run_scope_geometry') is not null, 'run_scope_geometry missing';
  assert to_regclass('analysis.run_type_settings') is not null, 'run_type_settings missing';
  -- idempotency unique within tenant
  assert exists (select 1 from pg_constraint
    where conrelid='analysis.analysis_runs'::regclass and contype='u'
      and pg_get_constraintdef(oid) ilike '%idempotency_key%'), 'idempotency unique missing';
end $$;
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f supabase/tests/0007_analysis_definitions_runs.test.sql`
Expected: FAIL — `analysis_providers missing`.

- [ ] **Step 3: Write the migration**

```sql
-- supabase/migrations/0007_analysis_definitions_runs.sql
create table analysis.analysis_providers (
    id         uuid primary key default gen_random_uuid(),
    slug       text not null unique,
    name       text not null,
    status     text not null default 'enabled' check (status in ('enabled','disabled')),
    config_ref text,
    created_at timestamptz not null default now()
);

create table analysis.analysis_definitions (
    id         uuid primary key default gen_random_uuid(),
    kind       text not null unique,           -- e.g. 'budget.route'
    label      text not null,
    created_at timestamptz not null default now()
);

create table analysis.analysis_definition_versions (
    id                uuid primary key default gen_random_uuid(),
    definition_id     uuid not null references analysis.analysis_definitions(id),
    provider_id       uuid not null references analysis.analysis_providers(id),
    interface_version text not null,
    request_schema    jsonb not null,
    result_schema     jsonb not null,
    artifact_kinds    jsonb not null default '[]'::jsonb,
    ui_descriptor     jsonb not null default '{}'::jsonb,
    status            text not null default 'draft' check (status in ('draft','active','retired')),
    created_at        timestamptz not null default now(),
    unique (definition_id, interface_version)
);

create table analysis.provider_capability_snapshots (
    id                    uuid primary key default gen_random_uuid(),
    definition_version_id uuid not null references analysis.analysis_definition_versions(id),
    descriptor            jsonb not null,
    config_version        text not null,
    created_at            timestamptz not null default now()
);

create table analysis.analysis_runs (
    id                    uuid primary key default gen_random_uuid(),
    idempotency_key       text not null,
    tenant_id             uuid not null references platform.tenants(id),
    requested_by_subject_id uuid not null references platform.oidc_subjects(id),
    definition_version_id uuid not null references analysis.analysis_definition_versions(id),
    capability_snapshot_id uuid not null references analysis.provider_capability_snapshots(id),
    boundary_version_id   uuid not null references geo.tenant_boundary_versions(id),
    edition_id            uuid not null references geo.geo_editions(id),
    budget_amount         numeric(14,2) not null check (budget_amount >= 0),
    budget_currency       text not null,
    status                text not null default 'queued'
                              check (status in ('queued','running','succeeded','failed','cancelled')),
    created_at            timestamptz not null default now(),
    started_at           timestamptz,
    finished_at          timestamptz,
    cancel_requested_at  timestamptz,
    cancel_requested_by_subject_id uuid references platform.oidc_subjects(id),
    unique (tenant_id, idempotency_key)
);
create index analysis_runs_tenant_ix on analysis.analysis_runs (tenant_id, created_at);

create table analysis.run_scope_areas (
    run_id      uuid not null references analysis.analysis_runs(id) on delete cascade,
    geo_area_id uuid not null references geo.geo_areas(id),
    primary key (run_id, geo_area_id)
);

create table analysis.run_scope_geometry (
    run_id   uuid primary key references analysis.analysis_runs(id) on delete cascade,
    geometry geometry(Geometry,4326) not null
);

create table analysis.run_type_settings (
    run_id              uuid not null references analysis.analysis_runs(id) on delete cascade,
    observation_type_id uuid not null references vision.observation_types(id),
    enabled             boolean not null default true,
    cost_basis_id       text,
    unit                text,
    unit_rate           numeric(14,2) check (unit_rate is null or unit_rate >= 0),
    primary key (run_id, observation_type_id)
);
```

- [ ] **Step 4: Apply and verify the test passes**

Run: `supabase db reset && psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f supabase/tests/0007_analysis_definitions_runs.test.sql`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/0007_analysis_definitions_runs.sql supabase/tests/0007_analysis_definitions_runs.test.sql
git commit -m "feat(db): analysis providers, definitions, runs, scope, type settings"
```

---

### Task 8: Frozen run inputs & exclusions

**Files:**
- Create: `supabase/migrations/0008_analysis_frozen_inputs.sql`
- Test: `supabase/tests/0008_analysis_frozen_inputs.test.sql`

**Interfaces:**
- Consumes: `analysis.analysis_runs`, `vision.observations`.
- Produces: `analysis.run_observations(run_id, observation_id)`, `analysis.run_observation_attributes`, `analysis.run_priority_values(run_id, observation_id)`, `analysis.run_observation_exclusions`.

- [ ] **Step 1: Write the failing assertion test**

```sql
-- supabase/tests/0008_analysis_frozen_inputs.test.sql
do $$
begin
  assert to_regclass('analysis.run_observations') is not null, 'run_observations missing';
  assert to_regclass('analysis.run_observation_attributes') is not null, 'run_observation_attributes missing';
  assert to_regclass('analysis.run_priority_values') is not null, 'run_priority_values missing';
  assert to_regclass('analysis.run_observation_exclusions') is not null, 'run_observation_exclusions missing';
  -- composite PK (run_id, observation_id) on run_observations (target of later artifact refs)
  assert (select count(*) from pg_constraint
    where conrelid='analysis.run_observations'::regclass and contype='p') = 1, 'run_observations PK missing';
  -- exclusion reason constraint
  assert exists (select 1 from pg_constraint
    where conrelid='analysis.run_observation_exclusions'::regclass and contype='c'
      and pg_get_constraintdef(oid) ilike '%unscored%'), 'exclusion reason check missing';
end $$;
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f supabase/tests/0008_analysis_frozen_inputs.test.sql`
Expected: FAIL — `run_observations missing`.

- [ ] **Step 3: Write the migration**

```sql
-- supabase/migrations/0008_analysis_frozen_inputs.sql
create table analysis.run_observations (
    run_id              uuid not null references analysis.analysis_runs(id) on delete cascade,
    observation_id      uuid not null references vision.observations(id),
    observation_type_id uuid not null references vision.observation_types(id),
    location            geography(Point,4326) not null,
    observed_at         timestamptz not null,
    recording_id        uuid,
    frame_ref           text,
    lifecycle_version   bigint,
    primary key (run_id, observation_id)
);

create table analysis.run_observation_attributes (
    run_id         uuid not null,
    observation_id uuid not null,
    definition_key text not null,
    value_kind     text not null,
    number_value   numeric,
    text_value     text,
    boolean_value  boolean,
    option_code    text,
    unit           text,
    primary key (run_id, observation_id, definition_key),
    foreign key (run_id, observation_id)
        references analysis.run_observations (run_id, observation_id) on delete cascade
);

create table analysis.run_priority_values (
    run_id         uuid not null,
    observation_id uuid not null,
    weight         numeric not null,
    model_name     text not null,
    model_version  text not null,
    value_state    text not null check (value_state in ('computed','inherited')),
    primary key (run_id, observation_id),
    foreign key (run_id, observation_id)
        references analysis.run_observations (run_id, observation_id) on delete cascade
);

create table analysis.run_observation_exclusions (
    run_id         uuid not null references analysis.analysis_runs(id) on delete cascade,
    observation_id uuid not null references vision.observations(id),
    reason         text not null check (reason in
                     ('unscored','unsupported_type','disabled_type','missing_required_fact')),
    primary key (run_id, observation_id)
);
```

- [ ] **Step 4: Apply and verify the test passes**

Run: `supabase db reset && psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f supabase/tests/0008_analysis_frozen_inputs.test.sql`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/0008_analysis_frozen_inputs.sql supabase/tests/0008_analysis_frozen_inputs.test.sql
git commit -m "feat(db): frozen run inputs and exclusions"
```

---

### Task 9: Analysis execution, results & artifacts + vision outbox

**Files:**
- Create: `supabase/migrations/0009_analysis_results.sql`
- Test: `supabase/tests/0009_analysis_results.test.sql`

**Interfaces:**
- Consumes: `analysis.analysis_runs`, `analysis.run_observations`.
- Produces: `vision.vision_outbox_events`, `analysis.analysis_outbox_events`, `analysis.analysis_attempts(run_id, attempt_number)`, `analysis.analysis_results(run_id)`, `analysis.result_metrics`, `analysis.result_warnings`, `analysis.artifacts(id)`, `analysis.map_features(geometry)`, `analysis.artifact_observation_refs`, `analysis.sequence_items`, `analysis.asset_refs`.

- [ ] **Step 1: Write the failing assertion test**

```sql
-- supabase/tests/0009_analysis_results.test.sql
do $$
begin
  assert to_regclass('vision.vision_outbox_events') is not null, 'vision_outbox_events missing';
  assert to_regclass('analysis.analysis_outbox_events') is not null, 'analysis_outbox_events missing';
  assert to_regclass('analysis.analysis_attempts') is not null, 'analysis_attempts missing';
  assert to_regclass('analysis.analysis_results') is not null, 'analysis_results missing';
  assert to_regclass('analysis.result_metrics') is not null, 'result_metrics missing';
  assert to_regclass('analysis.result_warnings') is not null, 'result_warnings missing';
  assert to_regclass('analysis.artifacts') is not null, 'artifacts missing';
  assert to_regclass('analysis.map_features') is not null, 'map_features missing';
  assert to_regclass('analysis.artifact_observation_refs') is not null, 'artifact_observation_refs missing';
  assert to_regclass('analysis.sequence_items') is not null, 'sequence_items missing';
  assert to_regclass('analysis.asset_refs') is not null, 'asset_refs missing';
  -- one result per run
  assert exists (select 1 from pg_constraint
    where conrelid='analysis.analysis_results'::regclass and contype='u'
      and pg_get_constraintdef(oid) ilike '%run_id%'), 'one-result-per-run unique missing';
  -- attempt number unique within run
  assert exists (select 1 from pg_constraint
    where conrelid='analysis.analysis_attempts'::regclass and contype='u'
      and pg_get_constraintdef(oid) ilike '%attempt_number%'), 'attempt uniqueness missing';
end $$;
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f supabase/tests/0009_analysis_results.test.sql`
Expected: FAIL — `vision_outbox_events missing`.

- [ ] **Step 3: Write the migration**

```sql
-- supabase/migrations/0009_analysis_results.sql
create table vision.vision_outbox_events (
    id            uuid primary key default gen_random_uuid(),
    event_kind    text not null,                 -- 'sweep_completed','observation_superseded','observation_resolved'
    entity_id     uuid,
    related_id    uuid,
    occurred_at   timestamptz not null default now(),
    delivery_state text not null default 'pending' check (delivery_state in ('pending','delivered'))
);
create index vision_outbox_pending_ix on vision.vision_outbox_events (occurred_at)
    where delivery_state = 'pending';

create table analysis.analysis_outbox_events (
    id            uuid primary key default gen_random_uuid(),
    aggregate_id  uuid not null,
    event_kind    text not null,
    payload       jsonb not null default '{}'::jsonb,
    created_at    timestamptz not null default now(),
    delivery_state text not null default 'pending' check (delivery_state in ('pending','delivered'))
);
create index analysis_outbox_pending_ix on analysis.analysis_outbox_events (created_at)
    where delivery_state = 'pending';

create table analysis.analysis_attempts (
    id                  uuid primary key default gen_random_uuid(),
    run_id              uuid not null references analysis.analysis_runs(id) on delete cascade,
    attempt_number      int not null,
    provider_request_id text,
    status              text not null default 'running'
                            check (status in ('running','succeeded','failed','cancelled')),
    started_at          timestamptz not null default now(),
    finished_at         timestamptz,
    response_hash       text,
    failure_code        text,
    failure_details     jsonb,
    unique (run_id, attempt_number)
);

create table analysis.analysis_results (
    id                  uuid primary key default gen_random_uuid(),
    run_id              uuid not null unique references analysis.analysis_runs(id) on delete cascade,
    accepted_attempt_id uuid not null references analysis.analysis_attempts(id),
    provider_version    text not null,
    config_version      text not null,
    result_schema_version text not null,
    payload             jsonb not null,
    created_at          timestamptz not null default now()
);

create table analysis.result_metrics (
    id           uuid primary key default gen_random_uuid(),
    result_id    uuid not null references analysis.analysis_results(id) on delete cascade,
    key          text not null,
    label        text,
    unit         text,
    number_value numeric,
    text_value   text
);

create table analysis.result_warnings (
    id        uuid primary key default gen_random_uuid(),
    result_id uuid not null references analysis.analysis_results(id) on delete cascade,
    code      text not null,
    severity  text,
    message   text
);

create table analysis.artifacts (
    id             uuid primary key default gen_random_uuid(),
    result_id      uuid not null references analysis.analysis_results(id) on delete cascade,
    kind           text not null check (kind in ('map_features','ordered_sequence','table','chart','asset_ref')),
    schema_version text not null,
    display_order  int not null default 0,
    title          text,
    payload        jsonb not null default '{}'::jsonb
);

create table analysis.map_features (
    id          uuid primary key default gen_random_uuid(),
    artifact_id uuid not null references analysis.artifacts(id) on delete cascade,
    geometry    geometry(Geometry,4326) not null,
    feature_key text,
    properties  jsonb not null default '{}'::jsonb
);
create index map_features_geom_gix on analysis.map_features using gist (geometry);

create table analysis.artifact_observation_refs (
    id            uuid primary key default gen_random_uuid(),
    artifact_id   uuid not null references analysis.artifacts(id) on delete cascade,
    run_id        uuid not null,
    observation_id uuid not null,
    role          text not null,
    display_order int,
    foreign key (run_id, observation_id)
        references analysis.run_observations (run_id, observation_id)
);

create table analysis.sequence_items (
    id                 uuid primary key default gen_random_uuid(),
    artifact_id        uuid not null references analysis.artifacts(id) on delete cascade,
    position           int not null,
    run_id             uuid,
    observation_id     uuid,
    provider_ref       text,
    label              text,
    foreign key (run_id, observation_id)
        references analysis.run_observations (run_id, observation_id)
);

create table analysis.asset_refs (
    id                uuid primary key default gen_random_uuid(),
    artifact_id       uuid not null references analysis.artifacts(id) on delete cascade,
    provider_asset_id text not null,
    media_type        text,
    integrity_hash    text,
    storage_ref       text
);
```

- [ ] **Step 4: Apply and verify the test passes**

Run: `supabase db reset && psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f supabase/tests/0009_analysis_results.test.sql`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/0009_analysis_results.sql supabase/tests/0009_analysis_results.test.sql
git commit -m "feat(db): analysis attempts, results, artifacts, outbox events"
```

---

### Task 10: Queues & scheduled drains

**Files:**
- Create: `supabase/migrations/0010_queues_cron.sql`
- Test: `supabase/tests/0010_queues_cron.test.sql`

**Interfaces:**
- Consumes: `vision.vision_outbox_events`, `analysis.analysis_outbox_events`.
- Produces: `pgmq` queues `analysis_jobs`, `materialization_jobs`, `thumbnail_jobs`; function `platform.drain_outbox()`; a `pg_cron` job running it.

- [ ] **Step 1: Write the failing assertion test**

```sql
-- supabase/tests/0010_queues_cron.test.sql
do $$
begin
  assert exists (select 1 from pgmq.list_queues() where queue_name = 'analysis_jobs'), 'analysis_jobs queue missing';
  assert exists (select 1 from pgmq.list_queues() where queue_name = 'materialization_jobs'), 'materialization_jobs queue missing';
  assert exists (select 1 from pgmq.list_queues() where queue_name = 'thumbnail_jobs'), 'thumbnail_jobs queue missing';
  assert to_regprocedure('platform.drain_outbox()') is not null, 'drain_outbox missing';
  assert exists (select 1 from cron.job where jobname = 'drain_outbox'), 'cron drain job missing';
end $$;
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f supabase/tests/0010_queues_cron.test.sql`
Expected: FAIL — `analysis_jobs queue missing`.

- [ ] **Step 3: Write the migration**

```sql
-- supabase/migrations/0010_queues_cron.sql
select pgmq.create('analysis_jobs');
select pgmq.create('materialization_jobs');
select pgmq.create('thumbnail_jobs');

-- Move undelivered outbox rows into pgmq, marking them delivered.
create or replace function platform.drain_outbox() returns void
language plpgsql security definer set search_path = '' as $$
declare r record;
begin
  for r in select id, event_kind, entity_id, related_id
           from vision.vision_outbox_events where delivery_state = 'pending'
           order by occurred_at loop
    perform pgmq.send('materialization_jobs',
      jsonb_build_object('outbox_id', r.id, 'kind', r.event_kind,
                         'entity_id', r.entity_id, 'related_id', r.related_id));
    if r.event_kind = 'observation_inserted' then
      perform pgmq.send('thumbnail_jobs', jsonb_build_object('observation_id', r.entity_id));
    end if;
    update vision.vision_outbox_events set delivery_state = 'delivered' where id = r.id;
  end loop;

  for r in select id, aggregate_id, event_kind, payload
           from analysis.analysis_outbox_events where delivery_state = 'pending'
           order by created_at loop
    perform pgmq.send('analysis_jobs',
      jsonb_build_object('outbox_id', r.id, 'kind', r.event_kind,
                         'aggregate_id', r.aggregate_id, 'payload', r.payload));
    update analysis.analysis_outbox_events set delivery_state = 'delivered' where id = r.id;
  end loop;
end $$;

select cron.schedule('drain_outbox', '10 seconds', 'select platform.drain_outbox();');
```

- [ ] **Step 4: Apply and verify the test passes**

Run: `supabase db reset && psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f supabase/tests/0010_queues_cron.test.sql`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/0010_queues_cron.sql supabase/tests/0010_queues_cron.test.sql
git commit -m "feat(db): pgmq queues and outbox drain cron"
```

---

### Task 11: Geo-clip read-model cache & functions

**Files:**
- Create: `supabase/migrations/0011_read_model_cache.sql`
- Test: `supabase/tests/0011_read_model_cache.test.sql`

**Interfaces:**
- Consumes: `platform.tenants`, `geo.tenant_boundary_versions`, `vision.observations`, `platform.is_member`.
- Produces: `vision.read_model_state`, `vision.bump_data_version() -> bigint`, `platform.tenant_visible_observations(tenant_id, observation_id)`, `platform.tenant_tile_sets(id)`, `platform.rebuild_tenant_visible(p_tenant uuid) -> int`, `platform.can_view_observation(p_observation_id uuid) -> boolean`.

- [ ] **Step 1: Write the failing assertion test (existence + cache correctness)**

```sql
-- supabase/tests/0011_read_model_cache.test.sql
do $$
declare
  v_tenant uuid; v_edition uuid; v_bv uuid; v_src uuid; v_type uuid; v_sweep uuid;
  v_in uuid; v_out uuid; v_count int;
begin
  assert to_regclass('vision.read_model_state') is not null, 'read_model_state missing';
  assert to_regclass('platform.tenant_visible_observations') is not null, 'tenant_visible_observations missing';
  assert to_regclass('platform.tenant_tile_sets') is not null, 'tenant_tile_sets missing';
  assert to_regprocedure('platform.rebuild_tenant_visible(uuid)') is not null, 'rebuild fn missing';
  assert to_regprocedure('platform.can_view_observation(uuid)') is not null, 'can_view fn missing';

  -- Seed a tiny scenario: a 0..10 / 0..10 boundary; one point inside, one outside.
  insert into platform.tenants(name) values ('t') returning id into v_tenant;
  insert into geo.geo_editions(source_name,source_release,status)
    values ('test','r1','active') returning id into v_edition;
  insert into geo.tenant_boundary_versions(tenant_id,edition_id,version_number,status,materialized_geometry)
    values (v_tenant, v_edition, 1, 'active',
            ST_Multi(ST_GeomFromText('POLYGON((0 0,0 10,10 10,10 0,0 0))',4326)))
    returning id into v_bv;
  insert into vision.sources(slug,name) values ('s','s') returning id into v_src;
  insert into vision.observation_types(slug,label,category) values ('pothole','P','road')
    returning id into v_type;
  insert into vision.sweeps(source_id,coverage,started_at,ended_at)
    values (v_src, ST_GeogFromText('POLYGON((0 0,0 10,10 10,10 0,0 0))'), now(), now())
    returning id into v_sweep;
  insert into vision.observations(observation_type_id,location,observed_at,sweep_id,
        detector_name,detector_version,detected_at,valid_from)
    values (v_type, ST_GeogFromText('POINT(5 5)'), now(), v_sweep, 'd','1', now(), now())
    returning id into v_in;
  insert into vision.observations(observation_type_id,location,observed_at,sweep_id,
        detector_name,detector_version,detected_at,valid_from)
    values (v_type, ST_GeogFromText('POINT(20 20)'), now(), v_sweep, 'd','1', now(), now())
    returning id into v_out;

  perform platform.rebuild_tenant_visible(v_tenant);

  select count(*) into v_count from platform.tenant_visible_observations
    where tenant_id = v_tenant;
  assert v_count = 1, 'cache should contain exactly the inside observation';
  assert exists (select 1 from platform.tenant_visible_observations
    where tenant_id = v_tenant and observation_id = v_in), 'inside obs should be cached';
  assert not exists (select 1 from platform.tenant_visible_observations
    where tenant_id = v_tenant and observation_id = v_out), 'outside obs must not be cached';
end $$;
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f supabase/tests/0011_read_model_cache.test.sql`
Expected: FAIL — `read_model_state missing`.

- [ ] **Step 3: Write the migration**

```sql
-- supabase/migrations/0011_read_model_cache.sql
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

create table platform.tenant_visible_observations (
    tenant_id           uuid   not null references platform.tenants(id) on delete cascade,
    boundary_version_id uuid   not null references geo.tenant_boundary_versions(id),
    observation_id      uuid   not null references vision.observations(id),
    data_version        bigint not null,
    primary key (tenant_id, observation_id)
);
create index tvo_tenant_ix on platform.tenant_visible_observations (tenant_id);

create table platform.tenant_tile_sets (
    id                  uuid primary key default gen_random_uuid(),
    tenant_id           uuid   not null references platform.tenants(id) on delete cascade,
    boundary_version_id uuid   not null references geo.tenant_boundary_versions(id),
    data_version        bigint not null,
    priority_model_id   uuid,
    edition_id          uuid,
    storage_bucket      text   not null default 'tenant-tiles',
    storage_prefix      text   not null,
    status              text   not null check (status in ('building','ready','stale','failed')),
    checksum            text,
    built_at            timestamptz,
    created_at          timestamptz not null default now(),
    unique (tenant_id, boundary_version_id, data_version)
);

-- Full rebuild of a tenant's cached visible set against its active boundary.
create or replace function platform.rebuild_tenant_visible(p_tenant uuid) returns int
language plpgsql security definer set search_path = extensions, public as $$
declare v_bv uuid; v_geom geometry; v_dv bigint; v_count int;
begin
  select id, materialized_geometry into v_bv, v_geom
    from geo.tenant_boundary_versions
    where tenant_id = p_tenant and status = 'active';
  if v_bv is null then return 0; end if;

  select data_version into v_dv from vision.read_model_state;

  delete from platform.tenant_visible_observations where tenant_id = p_tenant;

  insert into platform.tenant_visible_observations (tenant_id, boundary_version_id, observation_id, data_version)
  select p_tenant, v_bv, o.id, v_dv
    from vision.observations o
   where o.superseded_by_observation_id is null
     and o.resolved_at is null
     and ST_Contains(v_geom, o.location::geometry);

  get diagnostics v_count = row_count;
  return v_count;
end $$;

create or replace function platform.can_view_observation(p_observation_id uuid)
returns boolean language sql stable security definer set search_path = extensions, public as $$
    select platform.is_member(platform.active_tenant_id(), 'viewer')
       and exists (
            select 1
            from vision.observations o
            join geo.tenant_boundary_versions b
              on b.tenant_id = platform.active_tenant_id() and b.status = 'active'
            where o.id = p_observation_id
              and ST_Contains(b.materialized_geometry, o.location::geometry)
       );
$$;
```

- [ ] **Step 4: Apply and verify the test passes**

Run: `supabase db reset && psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f supabase/tests/0011_read_model_cache.test.sql`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/0011_read_model_cache.sql supabase/tests/0011_read_model_cache.test.sql
git commit -m "feat(db): cached geo-clip read model and visibility functions"
```

---

### Task 12: RLS policies & immutability triggers

**Files:**
- Create: `supabase/migrations/0012_rls_immutability.sql`
- Test: `supabase/tests/0012_rls_immutability.test.sql`

**Interfaces:**
- Consumes: helper functions (Task 2), cache (Task 11), all domain tables.
- Produces: RLS enabled + policies on `platform.tenant_visible_observations`, `vision.observations`, `analysis.analysis_runs`; trigger `vision.enforce_observation_immutability` on `vision.observations`; append-only triggers on `platform.audit_events` and frozen `analysis.run_*` tables.

- [ ] **Step 1: Write the failing assertion test (immutability + policy presence)**

```sql
-- supabase/tests/0012_rls_immutability.test.sql
do $$
declare v_src uuid; v_type uuid; v_sweep uuid; v_rec1 uuid; v_rec2 uuid; v_obs uuid; v_threw boolean;
begin
  -- policies present
  assert exists (select 1 from pg_policies where schemaname='vision' and tablename='observations'),
    'observations RLS policy missing';
  assert (select relrowsecurity from pg_class where oid='vision.observations'::regclass),
    'RLS not enabled on observations';
  assert exists (select 1 from pg_trigger where tgrelid='vision.observations'::regclass
    and tgname='observations_immutable'), 'immutability trigger missing';

  -- immutability: changing a fact column must raise
  insert into vision.sources(slug,name) values ('s2','s2') returning id into v_src;
  insert into vision.observation_types(slug,label,category) values ('t2','T2','c') returning id into v_type;
  insert into vision.sweeps(source_id,coverage,started_at,ended_at)
    values (v_src, ST_GeogFromText('POLYGON((0 0,0 1,1 1,1 0,0 0))'), now(), now())
    returning id into v_sweep;
  insert into vision.recordings(sweep_id,storage_path,started_at,ended_at)
    values (v_sweep,'a.mp4', now(), now()) returning id into v_rec1;
  insert into vision.recordings(sweep_id,storage_path,started_at,ended_at)
    values (v_sweep,'b.mp4', now(), now()) returning id into v_rec2;
  insert into vision.observations(observation_type_id,location,observed_at,sweep_id,
        detector_name,detector_version,detected_at,valid_from)
    values (v_type, ST_GeogFromText('POINT(0.5 0.5)'), now(), v_sweep, 'd','1', now(), now())
    returning id into v_obs;

  -- mutating detector_name must throw
  v_threw := false;
  begin
    update vision.observations set detector_name = 'changed' where id = v_obs;
  exception when others then v_threw := true; end;
  assert v_threw, 'mutating a fact column should raise';

  -- set-once recording_id: first set ok, rewrite raises
  update vision.observations set recording_id = v_rec1 where id = v_obs;     -- null -> value OK
  v_threw := false;
  begin
    update vision.observations set recording_id = v_rec2 where id = v_obs;   -- rewrite -> raise
  exception when others then v_threw := true; end;
  assert v_threw, 'rewriting set-once recording_id should raise';

  -- lifecycle column may change
  update vision.observations set miss_count = miss_count + 1 where id = v_obs;  -- allowed
end $$;
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f supabase/tests/0012_rls_immutability.test.sql`
Expected: FAIL — `observations RLS policy missing`.

- [ ] **Step 3: Write the migration**

```sql
-- supabase/migrations/0012_rls_immutability.sql

-- ---- RLS ----
alter table platform.tenant_visible_observations enable row level security;
create policy tvo_read on platform.tenant_visible_observations
    for select to authenticated
    using (tenant_id = platform.active_tenant_id() and platform.is_member(tenant_id, 'viewer'));

alter table vision.observations enable row level security;
create policy obs_read on vision.observations
    for select to authenticated
    using (exists (
        select 1 from platform.tenant_visible_observations v
        where v.observation_id = vision.observations.id
          and v.tenant_id = platform.active_tenant_id()
          and platform.is_member(v.tenant_id, 'viewer')
    ));

alter table analysis.analysis_runs enable row level security;
create policy runs_read on analysis.analysis_runs
    for select to authenticated
    using (platform.is_member(tenant_id, 'viewer'));
create policy runs_write on analysis.analysis_runs
    for insert to authenticated
    with check (platform.is_member(tenant_id, 'analysis_author'));

-- ---- Observation immutability ----
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
    then raise exception 'immutable observation fact/provenance column changed'; end if;

    if old.recording_id is not null and new.recording_id is distinct from old.recording_id then
        raise exception 'recording_id is set-once'; end if;
    if old.media_offset_ms is not null and new.media_offset_ms is distinct from old.media_offset_ms then
        raise exception 'media_offset_ms is set-once'; end if;
    if old.superseded_by_observation_id is not null
       and new.superseded_by_observation_id is distinct from old.superseded_by_observation_id then
        raise exception 'superseded_by is set-once'; end if;
    if old.resolved_at is not null and new.resolved_at is distinct from old.resolved_at then
        raise exception 'resolved_at is set-once'; end if;
    if old.valid_to is not null and new.valid_to is distinct from old.valid_to then
        raise exception 'valid_to is set-once'; end if;
    return new;
end $$;
create trigger observations_immutable before update on vision.observations
    for each row execute function vision.enforce_observation_immutability();

-- ---- Append-only tables ----
create or replace function platform.reject_mutation() returns trigger
language plpgsql as $$
begin raise exception 'table % is append-only', tg_table_name; end $$;

create trigger audit_events_append_only before update or delete on platform.audit_events
    for each row execute function platform.reject_mutation();
create trigger run_observations_append_only before update or delete on analysis.run_observations
    for each row execute function platform.reject_mutation();
create trigger run_observation_attributes_append_only before update or delete on analysis.run_observation_attributes
    for each row execute function platform.reject_mutation();
create trigger run_priority_values_append_only before update or delete on analysis.run_priority_values
    for each row execute function platform.reject_mutation();
create trigger obs_attr_values_append_only before update or delete on vision.observation_attribute_values
    for each row execute function platform.reject_mutation();
```

- [ ] **Step 4: Apply and verify the test passes**

Run: `supabase db reset && psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f supabase/tests/0012_rls_immutability.test.sql`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/0012_rls_immutability.sql supabase/tests/0012_rls_immutability.test.sql
git commit -m "feat(db): RLS policies and immutability/append-only enforcement"
```

---

### Task 13: Storage buckets & policies

**Files:**
- Create: `supabase/migrations/0013_storage.sql`
- Test: `supabase/tests/0013_storage.test.sql`

**Interfaces:**
- Consumes: `platform.is_member` (Task 2).
- Produces: buckets `sweep-video`, `observation-thumbnails`, `tenant-tiles`; a SELECT policy on `storage.objects` for `tenant-tiles`.

- [ ] **Step 1: Write the failing assertion test**

```sql
-- supabase/tests/0013_storage.test.sql
do $$
begin
  assert exists (select 1 from storage.buckets where id = 'sweep-video' and public = false), 'sweep-video bucket missing';
  assert exists (select 1 from storage.buckets where id = 'observation-thumbnails' and public = false), 'thumbnails bucket missing';
  assert exists (select 1 from storage.buckets where id = 'tenant-tiles' and public = false), 'tenant-tiles bucket missing';
  assert (select file_size_limit from storage.buckets where id = 'sweep-video') = 5368709120, 'sweep-video limit wrong';
  assert exists (select 1 from pg_policies where schemaname='storage' and tablename='objects'
    and policyname='tenant_tiles_read'), 'tenant_tiles_read policy missing';
end $$;
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f supabase/tests/0013_storage.test.sql`
Expected: FAIL — `sweep-video bucket missing`.

- [ ] **Step 3: Write the migration**

```sql
-- supabase/migrations/0013_storage.sql
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types) values
    ('sweep-video', 'sweep-video', false, 5368709120,
        array['video/mp4','video/webm','application/x-mpegURL']),
    ('observation-thumbnails', 'observation-thumbnails', false, 5242880,
        array['image/jpeg','image/webp','image/png']),
    ('tenant-tiles', 'tenant-tiles', false, 52428800,
        array['application/x-protobuf','application/octet-stream','application/json','application/gzip'])
on conflict (id) do update
    set file_size_limit = excluded.file_size_limit,
        allowed_mime_types = excluded.allowed_mime_types;

-- tenant-tiles readable by members of the tenant in the path's first folder
create policy tenant_tiles_read on storage.objects
    for select to authenticated
    using (
        bucket_id = 'tenant-tiles'
        and platform.is_member(((storage.foldername(name))[1])::uuid, 'viewer')
    );
```

- [ ] **Step 4: Apply and verify the test passes**

Run: `supabase db reset && psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f supabase/tests/0013_storage.test.sql`
Expected: PASS.

> Reminder: `sweep-video`'s 5 GiB limit only takes effect once the **global** Storage limit is raised above 50 MB (Task 14, Step 2).

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/0013_storage.sql supabase/tests/0013_storage.test.sql
git commit -m "feat(db): private storage buckets and tenant-tiles policy"
```

---

### Task 14: Seed data, generated types & full integration

**Files:**
- Create: `supabase/seed.sql`
- Create: `packages/db-types/database.ts` (generated)
- Create: `services/worker/.env.example`
- Test: `supabase/tests/0014_integration.test.sql`

**Interfaces:**
- Consumes: everything.
- Produces: a working local map dataset (`observation_types`, an active `priority_model`, a dev tenant + edition + active boundary), generated TS types, and the worker env template.

- [ ] **Step 1: Raise the remote global Storage limit (one-time infra)**

Set `[storage] file_size_limit = "5GiB"` in `supabase/config.toml` (done in Task 1) and apply to the remote project. Either run `supabase config push` (if the CLI version supports storage config sync) or, if not supported, apply via the management API / dashboard. Verify:
```bash
# expect fileSizeLimit well above 52428800
supabase projects api ... # or confirm via dashboard Storage settings
```

- [ ] **Step 2: Write the seed file**

```sql
-- supabase/seed.sql
insert into vision.sources(slug,name) values ('seed_truck','Seed truck') on conflict do nothing;
insert into vision.observation_types(slug,label,category,merge_radius_m,auto_resolvable)
  values ('pothole','Pothole','road_surface',10,true),
         ('missing_streetlight','Missing streetlight','lighting',15,false)
  on conflict (slug) do nothing;

insert into priority.priority_models(name,version,status)
  values ('baseline','v1','active') on conflict (name,version) do nothing;

insert into platform.tenants(name) values ('Dev Tenant') on conflict do nothing;
insert into geo.geo_editions(source_name,source_release,status)
  values ('seed-inegi','2020','active') on conflict do nothing;

-- A dev boundary covering a CDMX-ish bbox so the inside/outside cache logic is exercisable.
insert into geo.tenant_boundary_versions(tenant_id, edition_id, version_number, status, materialized_geometry)
select t.id, e.id, 1, 'active',
       ST_Multi(ST_GeomFromText('POLYGON((-99.3 19.2,-99.3 19.6,-98.9 19.6,-98.9 19.2,-99.3 19.2))',4326))
  from platform.tenants t, geo.geo_editions e
 where t.name='Dev Tenant' and e.source_name='seed-inegi'
 on conflict (tenant_id, version_number) do nothing;
```

- [ ] **Step 3: Write the end-to-end integration assertion test**

```sql
-- supabase/tests/0014_integration.test.sql
do $$
declare v_tenant uuid; v_count int;
begin
  -- seed produced an active model and an active boundary
  assert exists (select 1 from priority.priority_models where status='active'), 'no active priority model';
  select id into v_tenant from platform.tenants where name='Dev Tenant';
  assert v_tenant is not null, 'dev tenant missing';
  assert exists (select 1 from geo.tenant_boundary_versions where tenant_id=v_tenant and status='active'),
    'dev tenant has no active boundary';

  -- full pipeline smoke: bump version, rebuild cache, no error
  perform vision.bump_data_version();
  select platform.rebuild_tenant_visible(v_tenant) into v_count;  -- 0 obs seeded is fine
  assert v_count >= 0, 'rebuild failed';
end $$;
```

- [ ] **Step 4: Run full reset + every test (green suite)**

Run:
```bash
supabase db reset
for f in supabase/tests/*.test.sql; do
  echo "== $f"; psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f "$f" || exit 1
done
```
Expected: every file exits 0.

- [ ] **Step 5: Generate types and the worker env template**

```bash
supabase gen types typescript --linked > packages/db-types/database.ts
```
```bash
# services/worker/.env.example
cat > services/worker/.env.example <<'EOF'
SUPABASE_URL=https://joixzhdpnxqhnuscxsoy.supabase.co
SUPABASE_SERVICE_ROLE_KEY=__set_me__   # service role; bypasses RLS; never ship to a client
EOF
```

- [ ] **Step 6: Commit**

```bash
git add supabase/seed.sql supabase/tests/0014_integration.test.sql packages/db-types/database.ts services/worker/.env.example
git commit -m "feat(db): seed data, generated types, worker env, full integration test"
```

---

## Self-Review

**1. Spec coverage** — every spec section maps to a task:

- §3 baseline → Task 1. §4 auth bridge → Task 2. §5 cache → Task 11. §6 observations → Task 4. §7 media → Tasks 3–4. §8 storage → Task 13. §9 RLS → Tasks 2 (helpers), 11 (`can_view_observation`), 12 (policies), 13 (storage policy). §10 queue → Task 10. §11 immutability → Task 12. §12 migration order → Tasks 1–13 (cache moved before RLS, noted). §13 IaC/setup → Tasks 1, 14. Logical-model domains: platform (2), vision (3–4), priority (5), geo (6), analysis (7–9).
- Gap check: `vision_outbox_events` (logical §5) is created in Task 9; `analysis_outbox_events` (logical §9.2) in Task 9; both drained in Task 10. Covered.

**2. Placeholder scan** — no "TBD/TODO"; every code step contains complete SQL. The only deferred-to-runtime items are the worker server internals and tile rendering, which the spec lists as out of scope (§14 there), not part of this data-model plan.

**3. Type consistency** — names verified across tasks: `platform.is_member(uuid,text)`, `platform.active_tenant_id()`, `platform.rebuild_tenant_visible(uuid)`, `platform.can_view_observation(uuid)`, `vision.bump_data_version()` are defined once and referenced with matching signatures. `analysis.run_observations(run_id, observation_id)` composite key is the FK target used by `run_observation_attributes`, `run_priority_values`, `artifact_observation_refs`, and `sequence_items`. `tenant_visible_observations(tenant_id, observation_id)` shape matches the `obs_read` policy and the cache test.

**Note on ordering vs. spec §12:** the read-model cache (Task 11) is built *before* RLS (Task 12) because the `obs_read` policy references `platform.tenant_visible_observations`. This is the one intentional deviation from the spec's stated numeric order.
