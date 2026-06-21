-- Supabase Storage decommissioned; R2 (via app_authorize_object + the broker Worker)
-- is authoritative. Buckets are now R2 IaC, not storage.buckets rows. Pointer columns
-- (recordings.*, observation_thumbnails.*, tenant_tile_sets.*, external_signals.*) stay.
--
-- NOTE (live projects): Supabase guards storage.objects with the
-- `protect_objects_delete` trigger ("Use the Storage API instead"), so the
-- `delete from storage.objects` below only succeeds when the buckets are already
-- empty (e.g. a fresh `supabase db reset`). To decommission a project that still
-- holds objects, first remove them via the Storage API / S3 / dashboard (which
-- needs a service-role key or the project's S3 keys — NOT available to this
-- migration), then this runs clean. Bypassing the trigger is intentionally NOT
-- done here.
drop policy if exists tenant_tiles_read on storage.objects;

delete from storage.objects
 where bucket_id in ('external-data','sweep-video','observation-thumbnails','tenant-tiles');

delete from storage.buckets
 where id in ('external-data','sweep-video','observation-thumbnails','tenant-tiles');
