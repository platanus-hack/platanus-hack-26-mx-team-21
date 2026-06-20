# Object Storage (Buckets) Reference

**Last verified:** 2026-06-20 against `supabase/migrations/0103`, the column
defaults in `0003`/`0004`/`0011`, the physical design spec §8–§9.4, and
`services/external-data` (the only code that reads/writes a bucket today).

This is the contract for **every storage bucket**: what it holds, the exact path
layout, which database rows point into it, how access is granted, and how to
create or extend one. It is written for two readers:

- **Agents** — see [For agents](#for-agents): never invent a path or read bytes
  directly; resolve objects through the DB row that owns them and mint access
  through the documented RPC.
- **Engineers** — see [For engineers](#for-engineers): buckets are
  infrastructure-as-code; create them in a migration, mind the global size cap,
  keep local and remote in parity.

Companion: [`SCHEMA.md`](./SCHEMA.md) (the tables that reference these buckets).

---

## At a glance

| Bucket | Status | Private | Size limit | Written by | Read by | Path root |
|---|---|---|---|---|---|---|
| `external-data` | **Live** (`0103`) | yes | 5 GiB* | external-data pipeline (S3 creds) | external-data pipeline; ROI/signal lineage lookups | `raw/…`, `staging/…` |
| `sweep-video` | **Pending** (default only) | yes | 5 GiB* | capture/ingest worker (service role) | app users via signed URL | `sweeps/{sweep_id}/…` |
| `observation-thumbnails` | **Pending** (default only) | yes | 5 MiB | media worker (service role) | app users via signed URL | `observations/{observation_id}/…` |
| `tenant-tiles` | **Pending** (default only) | yes | 50 MiB | materialization worker (service role) | app users via path-prefix RLS | `{tenant_id}/{boundary_version_id}/{data_version}/…` |

\* A bucket's `file_size_limit` **cannot exceed the project-global Storage
limit**, which is **50 MB** by default. The 5 GiB values only take effect after
the global limit is raised (physical spec §13.4 — still pending). Until then,
objects larger than 50 MB fail to upload regardless of the per-bucket value.

> **"Pending"** means the bucket name exists only as a column **default**
> (`storage_bucket text not null default '…'`); no `storage.buckets` row is
> inserted yet, and no Storage RLS policy exists. Inserting the row + policy is
> the remaining work (see [Pending](#pending--ongoing)). `external-data` is the
> only bucket actually created.

All buckets are **private**. There are no public buckets.

---

## `external-data` — live

**Purpose.** Raw fetched source files and normalized staging artifacts for the
external-data pipeline (crash/violation/flooding/road-surface/crime signals and
the ROIs clustered from them). It is the byte store behind `priority.external_signals`
and `priority.rois`.

**Created by** `0103_external_data_storage.sql`:

```sql
insert into storage.buckets (id, name, public, file_size_limit) values
    ('external-data', 'external-data', false, 5368709120)   -- 5 GiB (capped by global limit)
on conflict (id) do update set file_size_limit = excluded.file_size_limit;
```

### Path layout (authoritative — produced by `services/external-data`)

| Path | Contents | Producer |
|---|---|---|
| `raw/{source_id}/{stamp}/{original_filename}` | The exact bytes fetched from the upstream source (e.g. a CKAN CSV) | `adapters/ckan_csv.py` |
| `raw/{source_id}/{stamp}/manifest.json` | `Manifest`: `source_id`, `source_url`, `sha256`, `byte_size`, `row_count`, `license`, `fetched_at`, `adapter` | `core/manifest.py` |
| `staging/{source_id}/signals.jsonl` | Normalized `Signal` records, one JSON object per line | `cli.py extract` |
| `staging/rois/current.geojson` | The current ROI set as a GeoJSON `FeatureCollection` | `cli.py roi-compute --export` |

- `{stamp}` is a UTC fetch timestamp formatted `%Y%m%dT%H%M%SZ` (e.g. `20260620T141500Z`).
- `{source_id}` is the registry source id (see `registry/sources.yaml`).

### Database lineage (how objects are referenced)

Objects are addressed from the rows they belong to — **do not scan the bucket to
find them**:

| Column | Points at |
|---|---|
| `priority.external_signals.source_object_ref` (text) | the signal's `raw/{source_id}/{stamp}/{file}` object |
| `priority.rois.source_object_refs` (text[]) | the union of contributing signals' `source_object_ref`s |

`external_signals.source_url` / `rois`-level provenance keep the upstream URL;
the `source_object_ref` is the *local copy* in this bucket.

### Backend abstraction & access

The pipeline reaches storage through an **fsspec** `ObjectStore`
(`core/storage.py`), selected by `STORAGE_BACKEND`:

| `STORAGE_BACKEND` | Filesystem | Root | Use |
|---|---|---|---|
| `local` (default) | `file://` | `LOCAL_ROOT` (default `.data`) | dev / tests — no Supabase needed |
| `supabase` | `s3://` (Supabase S3 protocol) | the `EXTERNAL_DATA_BUCKET` name | real bucket |

Configuration (`services/external-data/.env`, see `.env.example`):

```bash
STORAGE_BACKEND=local                  # local | supabase
LOCAL_ROOT=.data                       # root dir for the local backend
SUPABASE_S3_ENDPOINT=https://<ref>.storage.supabase.co/storage/v1/s3
SUPABASE_S3_ACCESS_KEY=__set_me__      # Supabase S3 access key
SUPABASE_S3_SECRET=__set_me__          # Supabase S3 secret
EXTERNAL_DATA_BUCKET=external-data     # bucket id == ObjectStore root
```

The external-data service authenticates with **S3 access keys** (server-side); it
is not a client-facing bucket, so no per-user Storage RLS applies to it. CLI
verbs that touch it: `extract` (writes `staging/.../signals.jsonl` + `raw/...`),
`roi-compute --export` (writes `staging/rois/current.geojson`), `load` (reads
staging back to upsert into `priority.external_signals`).

---

## `sweep-video` — pending

**Purpose.** Per-sweep camera recordings, the seekable source for the
"inspect-the-sweep" feature (jump a map pin to the exact frame that found it).

- **Path:** `sweeps/{sweep_id}/{recording_id}.mp4`
- **Referenced by:** `vision.recordings (storage_bucket, storage_path)` — unique
  together; `vision.observations.recording_id` + `media_offset_ms` then locate the
  frame.
- **Default in DDL:** `vision.recordings.storage_bucket default 'sweep-video'`.
- **Size:** 5 GiB intended (needs the global limit raised); large uploads use
  **resumable (TUS)** uploads.
- **Access:** see [Access control](#access-control). Reads require the geographic
  guard (`platform.can_view_observation`) and a service-role signed URL.

## `observation-thumbnails` — pending

**Purpose.** Small derived previews per observation, generated asynchronously so
`vision.observations` stays immutable.

- **Path:** `observations/{observation_id}/thumb.jpg`
- **Referenced by:** `vision.observation_thumbnails (storage_bucket, storage_path)` — unique together.
- **Default in DDL:** `vision.observation_thumbnails.storage_bucket default 'observation-thumbnails'`.
- **Size:** 5 MiB; MIME allow-list `image/jpeg|webp|png` (physical spec §8).
- **Access:** same geographic guard + signed URL as `sweep-video`.

## `tenant-tiles` — pending

**Purpose.** Precomputed, geo-clipped vector tiles / map layers per tenant, so the
map hot path serves bytes instead of running PostGIS per request.

- **Path:** `{tenant_id}/{boundary_version_id}/{data_version}/…`
- **Referenced by:** `platform.tenant_tile_sets (storage_bucket, storage_prefix, …)` —
  `storage_prefix` holds `{tenant_id}/{boundary_version_id}/{data_version}/`.
- **Default in DDL:** `platform.tenant_tile_sets.storage_bucket default 'tenant-tiles'`.
- **Size:** 50 MiB; MIME allow-list protobuf/octet-stream/json/gzip (physical spec §8).
- **Access:** **path-prefix RLS** — the first path folder is the `tenant_id`, and a
  caller may read it only if `platform.is_member(tenant_id, 'viewer')`. Pure
  membership, no geometry. (Policy defined in the spec, not yet applied.)

---

## Access control

Every bucket is private; nothing is world-readable. Two access shapes:

### 1. Geographic guard + service-role signed URL (`sweep-video`, `observation-thumbnails`)
The "can this user see this object" question is geographic (is the observation
inside the caller's active tenant boundary?), which is awkward as Storage RLS. So
the API/worker:

1. resolves `observation → recording_id + media_offset_ms` (or thumbnail path),
2. calls **`platform.can_view_observation(observation_id)`** — **implemented** in
   `0011`; returns true only if the caller is a tenant member *and*
   `ST_Contains(active boundary, observation.location)`,
3. on success, mints a short-lived **service-role** signed URL to the object.

The service-role key bypasses RLS and must never reach a client.

### 2. Path-prefix Storage RLS (`tenant-tiles`)
Membership-only, keyed on the first path segment (the tenant id). From the spec
(to be added as a migration):

```sql
create policy tenant_tiles_read on storage.objects
    for select to authenticated
    using (
        bucket_id = 'tenant-tiles'
        and platform.is_member(((storage.foldername(name))[1])::uuid, 'viewer')
    );
```

### 3. Server-side S3 credentials (`external-data`)
Not client-facing. The external-data service uses Supabase **S3 access keys** and
addresses the bucket directly via fsspec. No per-user policy applies.

---

## For agents

When you (or the app's runtime agents) deal with stored objects:

- **Resolve, don't guess.** Find an object through the DB row that owns it
  (`recordings.storage_path`, `observation_thumbnails.storage_path`,
  `tenant_tile_sets.storage_prefix`, `external_signals.source_object_ref`). Never
  hand-build a path you didn't read from a row, and never assume an object exists —
  check the owning row's `status` (`uploading`/`ready`/`failed`, `pending`/`ready`/`failed`).
- **Never embed bytes in the database.** Store the object, keep only its
  bucket+path (and a hash/size) in the row. `asset_refs`, `recordings`, and
  `thumbnails` are pointers, not blobs.
- **Mint access through the guard, not by widening a bucket.** For video/thumbnails,
  call `platform.can_view_observation(:id)` and only then request a signed URL via
  a service-role caller. For tiles, rely on the tenant path-prefix. Do not make a
  bucket public to "make it work."
- **Honor the path templates exactly** (table above). The external-data pipeline
  keys raw lineage on `raw/{source_id}/{stamp}/…`; tile cache keys on
  `{tenant_id}/{boundary_version_id}/{data_version}/…`. Diverging breaks lineage and
  cache invalidation.
- **Local vs. Supabase is a config switch, not a code change.** For external-data,
  set `STORAGE_BACKEND` and the same logical paths work on both.

## For engineers

- **Buckets are IaC.** Create or modify a bucket in a migration with an idempotent
  upsert, never via click-ops:
  ```sql
  insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
  values ('my-bucket', 'my-bucket', false, <bytes>, array['…'])
  on conflict (id) do update
      set file_size_limit = excluded.file_size_limit,
          allowed_mime_types = excluded.allowed_mime_types;
  ```
- **Mind the global cap.** `storage.buckets.file_size_limit` is clamped by the
  project-global Storage limit (50 MB today). Raise it once for video
  (`[storage] file_size_limit` in `config.toml` for local parity; apply the same to
  the remote project — the Supabase MCP `update_storage_config` can do it). Until
  then every bucket is effectively ≤50 MB.
- **Add the policy with the bucket.** A private bucket with no Storage RLS policy is
  unreadable by `authenticated`; that's intentional, but ship the matching policy
  (path-prefix for tiles, or signed-URL-only for video/thumbnails) in the same
  migration that creates the bucket.
- **Keep DDL defaults and bucket ids in sync.** Tables carry the bucket id as a
  column default (`recordings.storage_bucket`, etc.). If you rename a bucket, update
  the default and write a backfill — the unique `(storage_bucket, storage_path)`
  constraints assume they match.
- **Worker credentials.** The vision/tile workers read `SUPABASE_URL` +
  `SUPABASE_SERVICE_ROLE_KEY` (service role, bypasses RLS, signs URLs). The
  external-data service reads the `SUPABASE_S3_*` keys. Neither secret may reach a
  client.

---

## Pending / ongoing

| Item | Spec | State |
|---|---|---|
| Create `sweep-video`, `observation-thumbnails`, `tenant-tiles` `storage.buckets` rows | §8 | Not yet — only column defaults exist |
| Storage RLS policies (`tenant_tiles_read`; signed-URL flow wiring) | §9.4 | Not yet (`can_view_observation` exists; the policy + minting path do not) |
| Raise the project-global Storage size limit (>50 MB) for video | §13.4 | Not yet — caps all buckets at 50 MB |
| Worker that uploads recordings/thumbnails and builds tiles | §10 | Not in repo (queues drain, nothing consumes) |
| MIME allow-lists on the live `external-data` bucket | §8 | Not set (only `file_size_limit` is) |
