# Object Storage (Buckets) Reference

**Last verified:** 2026-06-20 against `supabase/migrations/0211` (Supabase Storage decommissioned), R2 buckets via `services/broker/wrangler.toml`, the column defaults in `0003`/`0004`/`0011`, the physical design spec §8–§9.4, and `services/external-data` (the only code that reads/writes a bucket today).

This is the contract for **every storage bucket**: what it holds, the exact path layout, which database rows point into it, how access is granted, and how to create or extend one. It is written for two readers:

- **Agents** — see [For agents](#for-agents): never invent a path or read bytes directly; resolve objects through the DB row that owns them and mint access through the documented RPC.
- **Engineers** — see [For engineers](#for-engineers): buckets are infrastructure-as-code on Cloudflare R2 (via `services/broker/wrangler.toml`); keep local (external-data S3 backend) and remote in parity.

Companion: [`SCHEMA.md`](./SCHEMA.md) (the tables that reference these buckets).

---

## At a glance

| Bucket | Status | Private | Size | Written by | Read by | Path root |
|---|---|---|---|---|---|---|
| `external-data` | **Live** (R2) | yes | — | external-data pipeline (S3 creds) | external-data pipeline; ROI/signal lineage lookups | `raw/…`, `staging/…` |
| `sweep-video` | **Live** (R2) | yes | — | recording ingestion (S3) | app users via broker Worker + `app_authorize_object` | `sweeps/{sweep_id}/…` |
| `observation-thumbnails` | **Live** (R2) | yes | — | media worker (S3) | app users via broker Worker + `app_authorize_object` | `observations/{observation_id}/…` |
| `tenant-tiles` | **Live** (R2) | yes | — | materialization worker (S3) | app users via broker Worker + `app_authorize_object` | `{tenant_id}/{boundary_version_id}/{data_version}/…` |

All buckets are **private**. There are no public buckets. Buckets are created and managed in `services/broker/wrangler.toml` (R2 IaC), not SQL.

---

## `external-data` — live (R2)

**Purpose.** Raw fetched source files and normalized staging artifacts for the external-data pipeline (crash/violation/flooding/road-surface/crime signals and the ROIs clustered from them). It is the byte store behind `priority.external_signals` and `priority.rois`.

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

Objects are addressed from the rows they belong to — **do not scan the bucket to find them**:

| Column | Points at |
|---|---|
| `priority.external_signals.source_object_ref` (text) | the signal's `raw/{source_id}/{stamp}/{file}` object |
| `priority.rois.source_object_refs` (text[]) | the union of contributing signals' `source_object_ref`s |

`external_signals.source_url` / `rois`-level provenance keep the upstream URL; the `source_object_ref` is the *local copy* in this bucket.

### Backend abstraction & access

The pipeline reaches storage through an **fsspec** `ObjectStore` (`core/storage.py`), selected by `STORAGE_BACKEND`:

| `STORAGE_BACKEND` | Filesystem | Root | Use |
|---|---|---|---|
| `local` (default) | `file://` | `LOCAL_ROOT` (default `.data`) | dev / tests — no R2 needed |
| `r2` | `s3://` (R2 S3 protocol) | the `EXTERNAL_DATA_BUCKET` name | production bucket |

Configuration (`services/external-data/.env`, see `.env.example`):

```bash
STORAGE_BACKEND=local                  # local | r2
LOCAL_ROOT=.data                       # root dir for the local backend
R2_S3_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com  # R2 endpoint
R2_ACCESS_KEY=__set_me__               # R2 S3 access key
R2_SECRET=__set_me__                   # R2 S3 secret
EXTERNAL_DATA_BUCKET=external-data     # bucket id == ObjectStore root
```

The external-data service authenticates with **S3 access keys** (server-side); it is not a client-facing bucket. CLI verbs that touch it: `extract` (writes `staging/.../signals.jsonl` + `raw/...`), `roi-compute --export` (writes `staging/rois/current.geojson`), `load` (reads staging back to upsert into `priority.external_signals`).

---

## `sweep-video` — live (R2)

**Purpose.** Per-sweep camera recordings, the seekable source for the "inspect-the-sweep" feature (jump a map pin to the exact frame that found it).

- **Path:** `sweeps/{sweep_id}/{recording_id}.mp4`
- **Referenced by:** `vision.recordings (storage_bucket, storage_path)` — unique together; `vision.observations.recording_id` + `media_offset_ms` then locate the frame.
- **Default in DDL:** `vision.recordings.storage_bucket default 'sweep-video'`.
- **Access:** see [Access control](#access-control). Reads require the geographic guard and authorization via the broker Worker.

## `observation-thumbnails` — live (R2)

**Purpose.** Small derived previews per observation, generated asynchronously so `vision.observations` stays immutable.

- **Path:** `observations/{observation_id}/thumb.jpg`
- **Referenced by:** `vision.observation_thumbnails (storage_bucket, storage_path)` — unique together.
- **Default in DDL:** `vision.observation_thumbnails.storage_bucket default 'observation-thumbnails'`.
- **Access:** same geographic guard as `sweep-video`, via broker Worker.

## `tenant-tiles` — live (R2)

**Purpose.** Precomputed, geo-clipped vector tiles / map layers per tenant, so the map hot path serves bytes instead of running PostGIS per request.

- **Path:** `{tenant_id}/{boundary_version_id}/{data_version}/…`
- **Referenced by:** `platform.tenant_tile_sets (storage_bucket, storage_prefix, …)` — `storage_prefix` holds `{tenant_id}/{boundary_version_id}/{data_version}/`.
- **Default in DDL:** `platform.tenant_tile_sets.storage_bucket default 'tenant-tiles'`.
- **Access:** membership-based via broker Worker, checked via `platform.is_member(tenant_id, 'viewer')`.

---

## Access control

Every bucket is private; nothing is world-readable. Access is mediated through the **broker Worker** (via the `app_authorize_object` RPC):

### The broker pattern

The SPA (and other clients) request objects via the broker Worker:
```
GET /api/r2/object?bucket=sweep-video&path=sweeps/{sweep_id}/{recording_id}.mp4
```

The broker:
1. Extracts the bucket and path from the query parameters
2. Calls the `public.app_authorize_object(bucket_id, object_path)` RPC to check if the authenticated user can access the object (returns `boolean`)
3. If authorized, fetches the object from R2 via its binding (e.g., `SWEEP_VIDEO`, `OBSERVATION_THUMBNAILS`, `TENANT_TILES`)
4. Streams the object back to the client

Authorization logic lives in the RPC and respects database pointers:

| Bucket | Authorization | Binding in broker |
|---|---|---|
| `sweep-video` | Geographic guard + tenant membership (`platform.can_view_observation`) | `SWEEP_VIDEO` |
| `observation-thumbnails` | Geographic guard + tenant membership (`platform.can_view_observation`) | `OBSERVATION_THUMBNAILS` |
| `tenant-tiles` | Membership-only (`platform.is_member`) | `TENANT_TILES` |
| `external-data` | Not client-facing; accessed server-side via S3 | N/A |

R2 credentials for the broker are configured in `services/broker/wrangler.toml` (the Worker binding secrets).

---

## For agents

When you (or the app's runtime agents) deal with stored objects:

- **Resolve, don't guess.** Find an object through the DB row that owns it (`recordings.storage_path`, `observation_thumbnails.storage_path`, `tenant_tile_sets.storage_prefix`, `external_signals.source_object_ref`). Never hand-build a path you didn't read from a row, and never assume an object exists — check the owning row's `status` (`uploading`/`ready`/`failed`, `pending`/`ready`/`failed`).
- **Never embed bytes in the database.** Store the object, keep only its bucket+path (and a hash/size) in the row. `recordings`, and `thumbnails` are pointers, not blobs.
- **Use the broker for client access.** SPA requests go through `GET /api/r2/object?bucket=…&path=…`. The broker calls `app_authorize_object` to enforce the guard.
- **Honor the path templates exactly** (tables above). The external-data pipeline keys raw lineage on `raw/{source_id}/{stamp}/…`; tile cache keys on `{tenant_id}/{boundary_version_id}/{data_version}/…`. Diverging breaks lineage and cache invalidation.
- **Local vs. R2 is a config switch.** For external-data, set `STORAGE_BACKEND` and the same logical paths work on both.

## For engineers

- **Buckets are R2 IaC.** Create or modify a bucket in `services/broker/wrangler.toml` (the source of truth for R2 buckets), not in SQL. Example:
  ```toml
  [[r2_buckets]]
  binding = "SWEEP_VIDEO"
  bucket_name = "sweep-video"
  ```
  (Buckets are created in the default jurisdiction — `wrangler r2 bucket create
  sweep-video`. Only set `jurisdiction` here if the bucket was created with one;
  a mismatch makes the binding resolve to the wrong/no bucket.)
- **Keep DDL defaults in sync.** Tables carry the bucket id as a column default (`recordings.storage_bucket`, etc.). If you rename a bucket, update the default and write a backfill — the unique `(storage_bucket, storage_path)` constraints assume they match.
- **Broker credentials.** The broker Worker reads R2 credentials from its `wrangler.toml` bindings. The external-data service reads its own `R2_S3_*` keys. Neither secret may reach a client.
- **Path templates are contracts.** Agents rely on exact path layouts for lineage and cache keys. Diverging breaks downstream systems.

---

## Completed & deployed

| Item | Spec | State |
|---|---|---|
| R2 buckets IaC (`services/broker/wrangler.toml`) | §3.A | Done — Task 1 |
| Broker Worker (authz-forward, binding serve, Range support) | §3.B | Done — Task 4 |
| `app_authorize_object` RPC + drop Supabase Storage | §3.C | Done — Tasks 3 & 7 |
| External-data pipeline (S3 backend + container) | §3.D | Done — Tasks 2 & 5 |
| SPA hosting + media/tiles via broker | §3.F | Pending — blocked on `frontend` existing |
| Vision/tile worker (Container, writes via S3) | §3.E | Pending — blocked on `services/worker` code |
