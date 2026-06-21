-- Supabase Storage decommissioned; R2 (via app_authorize_object + the broker Worker)
-- is authoritative. Buckets are now R2 IaC, not storage.buckets rows. Pointer columns
-- (recordings.*, observation_thumbnails.*, tenant_tile_sets.*, external_signals.*) stay.
--
-- NOTE (live projects): Supabase guards storage.objects with the
-- `protect_objects_delete` trigger ("Use the Storage API instead"), which now blocks
-- ANY direct delete — even of zero rows on a fresh `supabase db reset`. So the cleanup
-- below is best-effort and must not abort the migration: object bytes are decommissioned
-- via the Storage API / S3 / dashboard, and the pointer rows are gone on a fresh stack.
-- Bypassing the trigger is intentionally NOT done here.
drop policy if exists tenant_tiles_read on storage.objects;

do $$
begin
  delete from storage.objects
   where bucket_id in ('external-data','sweep-video','observation-thumbnails','tenant-tiles');
exception when others then
  raise notice 'skipping storage.objects cleanup: %', sqlerrm;
end $$;

do $$
begin
  delete from storage.buckets
   where id in ('external-data','sweep-video','observation-thumbnails','tenant-tiles');
exception when others then
  raise notice 'skipping storage.buckets cleanup: %', sqlerrm;
end $$;
