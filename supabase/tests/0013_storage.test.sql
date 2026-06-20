do $$
begin
  assert exists (select 1 from storage.buckets where id = 'sweep-video' and public = false), 'sweep-video bucket missing';
  assert exists (select 1 from storage.buckets where id = 'observation-thumbnails' and public = false), 'thumbnails bucket missing';
  assert exists (select 1 from storage.buckets where id = 'tenant-tiles' and public = false), 'tenant-tiles bucket missing';
  assert (select file_size_limit from storage.buckets where id = 'sweep-video') = 5368709120, 'sweep-video limit wrong';
  assert exists (select 1 from pg_policies where schemaname='storage' and tablename='objects'
    and policyname='tenant_tiles_read'), 'tenant_tiles_read policy missing';
end $$;
