do $$
begin
  -- Supabase Storage decommissioned (R2 is authoritative); buckets + policy must be gone.
  assert not exists (select 1 from storage.buckets
    where id in ('sweep-video','observation-thumbnails','tenant-tiles')),
    'supabase storage buckets should be removed';
  assert not exists (select 1 from pg_policies where schemaname='storage' and tablename='objects'
    and policyname='tenant_tiles_read'), 'tenant_tiles_read should be removed';
  -- pointer columns still exist (R2 paths live here)
  assert exists (select 1 from pg_attribute
    where attrelid='vision.recordings'::regclass and attname='storage_path'),
    'recordings.storage_path must remain';
end $$;
