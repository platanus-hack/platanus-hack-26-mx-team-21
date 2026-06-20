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
