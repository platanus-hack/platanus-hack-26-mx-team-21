# Supabase → Cloudflare Migration (Storage + SPA + Workers) — Design

**Date:** 2026-06-20
**Status:** Approved (design) — pending implementation
**Component:** Object storage, SPA hosting, and worker runtime
**Scope:** Move object storage to **Cloudflare R2**, host the SPA on **Cloudflare Workers
Static Assets**, and run all workers on **Cloudflare** (thin Python Workers + Containers
for heavy batch). **Supabase Postgres, Auth, and RLS stay as the system of record.**

Companion docs: [`STORAGE.md`](../../../supabase/STORAGE.md) (current bucket contract, to be
rewritten for R2), [`SCHEMA.md`](../../../supabase/SCHEMA.md) (pointer columns that survive
the migration), and the external-data pipeline design
([`2026-06-20-external-data-pipeline-design.md`](./2026-06-20-external-data-pipeline-design.md)).

---

## 1. Goal & scope

Supabase is capping us on object storage (project-global Storage limit, 50 MB by default;
video/tiles need GiB-scale buckets). Rather than pay to raise that cap, we move the **bytes**
to Cloudflare R2 (generous free tier, **no egress fees**), host the SPA on Cloudflare, and
consolidate the worker runtime on Cloudflare.

**In scope:**
- Object storage (all four buckets) → R2.
- SPA (`apps/web`) hosting → Cloudflare Workers Static Assets.
- Workers (`services/external-data` heavy batch; the greenfield vision/tile worker) → Cloudflare
  (Containers for heavy batch, thin Python Workers for request/cron-shaped logic).
- A new client-facing **R2 access-broker** Worker that preserves tenant isolation without
  Postgres Storage-RLS.
- One-time **bulk data copy** of existing objects + verification, then phased cutover.

**Out of scope (explicit YAGNI):**
- Migrating Postgres, Auth, or RLS off Supabase. The DB remains the system of record; the
  browser still uses supabase-js + the `public` API layer for everything except media/tile bytes.
- Rewriting the geospatial pipeline's algorithms. The numpy/pyproj/ROI code is **lifted as-is**
  into a Container.
- Public buckets. All buckets stay private; access is always mediated.
- A new CDN / image-resizing / transform layer.

## 2. The core problem & the central design move

Supabase Storage access today is **Postgres-coupled**:

- `sweep-video`, `observation-thumbnails`: signed URLs minted by a **service-role** caller
  *after* `platform.can_view_observation()`.
- `tenant-tiles`: a **path-prefix Storage-RLS policy** (`tenant_tiles_read`) keyed on the
  tenant id in the first path segment, gated by `platform.is_member(...)`.
- `external-data`: server-side **S3 access keys**, not client-facing.

R2 has **no Postgres RLS** and **no Supabase Storage signed-URL flow**. The central design move:

> **Keep the authorization decision in Postgres, move the bytes to R2, and put a thin
> Cloudflare Worker in between.** The Worker asks Postgres "may this user see this object?"
> (reusing the *existing* `can_view_observation` / `is_member` helpers) and only then serves
> the object from R2.

This means **no authorization logic is reimplemented or duplicated** in the edge layer —
Postgres stays the single source of truth, and we avoid policy drift.

### What does NOT change

- DB **pointer columns**: `recordings.storage_bucket` / `recordings.storage_path`,
  `observation_thumbnails.storage_path`, `tenant_tile_sets.storage_prefix`,
  `priority.external_signals.source_object_ref`, `priority.rois.source_object_refs`.
- The `(storage_bucket, storage_path)` **unique constraints**.
- The **bucket ids** (`external-data`, `sweep-video`, `observation-thumbnails`,
  `tenant-tiles`) — they simply become R2 bucket names instead of Supabase Storage buckets.
- The **path templates** (`raw/{source_id}/{stamp}/…`, `sweeps/{sweep_id}/…`,
  `observations/{observation_id}/…`, `{tenant_id}/{boundary_version_id}/{data_version}/…`).

## 3. Components

### A. R2 buckets (Infrastructure-as-Code, not SQL)

Four **private** R2 buckets, ids identical to the current `storage_bucket` column defaults,
declared in `wrangler` config (and/or Terraform) — **not** created via SQL migrations:

| R2 bucket | Replaces (Supabase) | Written by | Read by |
|---|---|---|---|
| `external-data` | live `external-data` bucket (`0103`) | external-data Container (S3) | external-data Container; lineage lookups |
| `sweep-video` | pending `sweep-video` | vision Container (S3) | app users via broker Worker |
| `observation-thumbnails` | pending `observation-thumbnails` | vision Container (S3) | app users via broker Worker |
| `tenant-tiles` | pending `tenant-tiles` | tile Container (S3) | app users via broker Worker |

The old Supabase `storage.buckets` rows and Storage-RLS policies (migrations `0103`,
`fea2888`, the `tenant_tiles_read` policy) become **obsolete**. A new migration drops/supersedes
them (§C) and `STORAGE.md` is rewritten for R2, so nothing implies Supabase Storage is still
authoritative.

> **Buckets are accessed two ways on the same object set:** Containers (full Linux) use the
> **S3 API** to R2; the broker Worker uses the **R2 binding**. Both are first-class on R2.

### B. R2 access-broker → Python Cloudflare Worker (client-facing)

The new path the browser uses to fetch protected media/tiles.

**Route:** `GET /api/r2/object?bucket=<id>&path=<object-path>` with the user's Supabase
`Authorization: Bearer <access token>`.

**Flow:**
1. Worker forwards the **user's JWT** to a Supabase RPC `public.app_authorize_object(p_bucket,
   p_path)`, called as that user (`apikey: <anon>`, `Authorization: Bearer <user JWT>`), so
   `auth.uid()` + RLS + `can_view_observation`/`is_member` all evaluate naturally. **Authz
   stays in Postgres.**
2. On `allow = true`, the Worker serves the bytes via the **R2 binding** (`env.<BUCKET>.get(path)`)
   — streaming pass-through, with **`Range`** support (video seeking) and appropriate
   `Cache-Control` / `Content-Type`. On `false`, return `403`.
3. R2 credentials never leave the Worker; the browser never receives a raw bucket URL.

**Decision — binding-proxy over S3 presigned URLs** (override point): presigning inside a
Pyodide Python Worker is awkward (no native botocore signing), R2 egress is free, and a
binding proxy gives us `Range` + the Cache API cleanly. Presigned URLs remain the documented
fallback if we later want to offload bandwidth from the Worker. The broker abstracts the
serving mechanism so this can change without touching the SPA.

**SPA change:** media/tile fetches switch from Supabase signed URLs to same-origin
`/api/r2/object?...`. Everything else in the SPA (auth, `public` API layer reads/RPCs) is
unchanged.

### C. New Supabase migration `02xx_r2_access_api.sql`

- Adds `public.app_authorize_object(p_bucket text, p_path text) returns boolean`
  (`security definer`, `set search_path = ''`): maps `(bucket, path)` → the owning row and
  reuses the existing helpers —
  - `sweep-video` / `observation-thumbnails` → resolve `path` to its `recording_id` /
    `observation_id` and call `platform.can_view_observation(...)`;
  - `tenant-tiles` → `platform.is_member(((path-first-segment)::uuid), 'viewer')`;
  - `external-data` → not client-facing; the RPC denies it (served only server-side).
- Drops the now-inert Supabase Storage `storage.buckets` rows + Storage-RLS policies
  (`tenant_tiles_read`, the `external-data` bucket row).
- Keeps all pointer columns and `(storage_bucket, storage_path)` unique constraints.

Numbering slots alongside the planned app-API migrations (`0200_app_read_api.sql`,
`0201_app_analysis_api.sql`); exact number assigned at implementation time after re-reading
the current migration head.

### D. external-data pipeline → Cloudflare Container

The heavy batch job (numpy / pyproj / fsspec / geospatial ROI clustering) is **lifted as-is**
into a containerized Python image and triggered by a **Cron Trigger** Worker (and/or a
**Queues** producer → Container consumer).

Two small code changes only:
- `services/external-data/core/storage.py` `make_store()` gains an **`r2`** backend: an fsspec
  `s3` filesystem pointed at the R2 S3 endpoint with R2 credentials — a branch mirroring the
  existing `supabase` one.
- `Settings.storage_backend` accepts `r2` in addition to `local` / `supabase`.

DB writes (`load` → `priority.external_signals` / `rois`) are **unchanged** — the Container
connects directly to Supabase Postgres. The Container reaches R2 via the **S3 API** (boto3 /
fsspec works in a full Linux container).

### E. Vision / tile worker (greenfield — specced CF-native)

Currently only `services/worker/.env.example` exists; there is **nothing to migrate**. We
spec it Cloudflare-native from the start:
- **Heavy side** (recording/thumbnail ingest, thumbnail generation, tenant-tile building):
  a **Container** job writing to R2 via S3 (`sweep-video`, `observation-thumbnails`,
  `tenant-tiles`), updating the owning DB rows' `status` (`uploading`→`ready`).
- **Serving side**: routes on the broker Worker from §B (no separate signing service).

### F. SPA hosting → Cloudflare Workers Static Assets

**Decision — Workers Static Assets over Pages** (override point): current Cloudflare
recommendation, and it co-locates with our Worker. `apps/web/dist` is served as static assets;
`/api/r2/*` on the **same origin** routes to the broker Worker (one combined Worker project, or
an assets Worker + broker Worker bound by route — decided at implementation). The SPA continues
to use supabase-js + the `public` API layer; only media/tile byte-fetches change.

Build-time env unchanged: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`. The broker is reached
at a same-origin relative path, so no new public base URL is needed.

## 4. Data migration (real data exists → copy + verify, phased strangler)

1. **Stand up** R2 buckets + R2 S3 credentials + the R2 bindings/secrets for Workers/Containers.
2. **Bulk copy** (one-time): `rclone` / `aws s3 sync` from the Supabase S3 endpoint
   (`https://<ref>.storage.supabase.co/storage/v1/s3`) → the R2 S3 endpoint, per bucket, using
   checksum comparison. **Verify**: object counts + sha256 match; reconcile against
   `external_signals.source_object_ref` / `rois.source_object_refs` so no DB pointer is orphaned.
3. **Cut over** readers/writers: set `STORAGE_BACKEND=r2` for the pipeline, deploy the broker +
   SPA, point SPA media/tile fetches at `/api/r2/object`.
4. **Verify in place** (broker serves, pipeline writes, lineage resolves), **then decommission**
   Supabase Storage (apply the drop migration from §C; revoke Supabase S3 keys).

This is a **strangler** sequence — old and new coexist until verified — chosen over a big-bang
cutover for rollback safety.

## 5. Configuration & secrets

| Where | New / changed | Notes |
|---|---|---|
| `services/external-data/.env.example` | `STORAGE_BACKEND=r2`; `R2_S3_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` | mirrors existing `SUPABASE_S3_*` block; server-side only |
| Broker Worker (`wrangler.toml`) | R2 bucket **bindings**; secrets `SUPABASE_URL`, `SUPABASE_ANON_KEY` | anon key only — authz runs as the user via forwarded JWT; no service-role key at the edge |
| Container images | R2 S3 creds; Supabase Postgres connection string | for batch write + DB load |
| `apps/web/.env.example` | unchanged (`VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`) | broker is same-origin |

**No service-role key and no R2 secret ever reaches a client.** The broker holds R2 bindings
(not S3 secrets) and only the Supabase **anon** key.

## 6. Key trade-offs already decided (override points)

| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Authz source | Postgres via JWT-forwarding RPC | Re-verify JWT + reimplement authz in Worker | Single source of truth; no policy drift |
| Serving mechanism | R2-binding proxy | S3 presigned URLs | Python-Worker-simple; `Range` + Cache API; free egress |
| Sequencing | Phased strangler | Big-bang cutover | Rollback safety with real data |
| SPA host | Workers Static Assets | Cloudflare Pages | CF recommendation; co-locates with broker |
| Heavy batch runtime | Cloudflare Containers (Cron/Queues) | Rewrite pipeline Worker-native | Lift-as-is; avoids touching geospatial algorithms |

## 7. Risks & mitigations

- **Cloudflare Python Workers & Containers are beta.** Mitigation: keep the Worker logic thin
  (auth-forward + binding proxy); keep heavy compute in Containers (full Linux, no Pyodide
  limits). If Python Workers prove too constrained for the broker, the broker is small enough
  to port to a TS Worker without design change (the contract is the HTTP route + the Postgres RPC).
- **Beta surface for Containers.** Mitigation: the Container image is an ordinary Python app;
  if Containers are unavailable, the same image runs as a scheduled CI/job runner writing to R2
  + Supabase — the only coupling to Cloudflare is the trigger, not the code.
- **Pointer/lineage orphaning during copy.** Mitigation: verification pass in §4.2 reconciles
  every `source_object_ref` before cutover; strangler keeps Supabase Storage readable until then.
- **Large video through a Worker.** Mitigation: binding `.get()` returns a stream piped through
  (not buffered); `Range` honored. If Worker duration becomes an issue for very large files,
  switch that route to presigned URLs (the documented fallback) without SPA changes.

## 8. Definition of done

Per the project's standing bar: not done until (1) schema-compatible with
`supabase/migrations/*` + `SCHEMA.md` (pointer columns + constraints intact, authz RPC merged),
(2) the SPA fetches protected media/tiles through the broker and renders correctly against the
reference, and (3) integration tests actually run and pass — a round-trip test that writes an
object to R2 (Container path), authorizes via `app_authorize_object`, and serves it through the
broker for an in-boundary tenant member while a non-member gets `403`.
