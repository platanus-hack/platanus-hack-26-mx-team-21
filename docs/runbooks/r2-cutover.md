# R2 Cutover Runbook (regenerate path)

**Status:** storage migrated to Cloudflare R2. Object I/O is on R2; Supabase
Postgres/Auth/RLS remain the system of record.

**Decision (2026-06-20):** the only data in Supabase Storage was **4 objects
(~30 MB) in the `external-data` bucket** — regenerable pipeline artifacts. The
other three buckets (`sweep-video`, `observation-thumbnails`, `tenant-tiles`)
were **empty**. We chose **regenerate, not copy**: abandon the old Supabase
objects and let the R2-capable pipeline repopulate R2. No Supabase S3 keys
needed.

> If you ever need lineage-preserving migration instead (so existing
> `priority.external_signals.source_object_ref` keep pointing at the same bytes),
> use the copy path: `rclone copy supabase:external-data r2:external-data
> --checksum` with a Supabase **Storage → S3 Access Key**, then `rclone check`.
> Not used here.

---

## What is already done

| Step | State |
|---|---|
| Four R2 buckets (`external-data`, `sweep-video`, `observation-thumbnails`, `tenant-tiles`) | ✅ created (`wrangler r2 bucket list`) |
| Pipeline `r2` storage backend (`STORAGE_BACKEND=r2`) | ✅ shipped + unit-tested |
| Container image (`external-data:r2`) writes to R2 | ✅ verified: live round-trip + a real `extract` of `sacmex_encharcamientos` wrote a 52 MB CSV + manifest to `r2:external-data/raw/…` |
| `public.app_authorize_object` RPC | ✅ deployed to remote, RED→GREEN |
| Broker Worker (`r2-access-broker.alamst.workers.dev`) | ✅ deployed, 5/5 integration (member→404, non-member→403, no-bearer→401, bad-bucket→400) |

## Regenerate (repopulate R2) — production run

The regenerate is a normal pipeline run with `STORAGE_BACKEND=r2`. It needs the
R2 creds (already in the Container env) plus **`DB_URL`** for the `load` step,
which refreshes the DB pointers to the new R2 paths.

```bash
# in the Container (or any host with the external-data:r2 image), env:
#   STORAGE_BACKEND=r2  R2_S3_ENDPOINT  R2_ACCESS_KEY  R2_SECRET
#   EXTERNAL_DATA_BUCKET=external-data  DB_URL=<supabase postgres connection string>
external-data extract --all                 # raw/{source}/{stamp}/… + staging/{source}/signals.jsonl -> R2
external-data roi-compute --all --export     # staging/rois/current.geojson -> R2
external-data load                           # upsert priority.external_signals / rois; sets source_object_ref to R2 paths
```

This is what the **Cron-triggered Container** (`services/external-data/cron/`)
runs on schedule; the first run is the regeneration. Until `load` runs,
`external_signals.source_object_ref` still names the abandoned Supabase paths —
that is expected for the regenerate path and is resolved by the first `load`.

### Known pre-existing data issue (NOT a migration bug)

A demonstration `extract --source sacmex_encharcamientos` returned **0 signals**:
the registry's `column_map` for that CKAN resource is stale (the file header has
drifted). `registry/sources.yaml` already flags that per-resource headers must be
confirmed at first live run (`datastore_search?limit=1`). Fix the column map
before relying on that source's signals; storage/migration are unaffected (the
raw CSV + manifest still landed in R2).

## Cutover & rollback

- **Readers:** the SPA fetches protected media/tiles from the broker
  (`GET https://r2-access-broker.alamst.workers.dev/api/r2/object?bucket=&path=`)
  instead of Supabase signed URLs (SPA wiring is a follow-on; the broker
  contract is live now).
- **Writers:** the pipeline/Container writes to R2 (`STORAGE_BACKEND=r2`).
- **Rollback:** Supabase Storage objects remain intact until **Task 7
  (decommission)**. To revert, set `STORAGE_BACKEND=supabase` and point readers
  back — no data is destroyed before decommission.
- **Decommission (Task 7):** after a production regenerate validates, apply
  `0211_drop_supabase_storage.sql` to drop the Supabase `storage.buckets` rows +
  the `tenant_tiles_read` policy. DB pointer columns are untouched.
