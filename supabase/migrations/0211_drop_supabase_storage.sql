-- Supabase Storage decommissioned; R2 (via app_authorize_object + the broker Worker)
-- is authoritative. Buckets are now R2 IaC, not storage.buckets rows. Pointer columns
-- (recordings.*, observation_thumbnails.*, tenant_tile_sets.*, external_signals.*) stay.
drop policy if exists tenant_tiles_read on storage.objects;

delete from storage.objects
 where bucket_id in ('external-data','sweep-video','observation-thumbnails','tenant-tiles');

delete from storage.buckets
 where id in ('external-data','sweep-video','observation-thumbnails','tenant-tiles');
