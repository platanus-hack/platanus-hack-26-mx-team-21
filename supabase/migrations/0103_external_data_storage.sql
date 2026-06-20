-- Private bucket for raw + staging external-data objects referenced by ROIs.
insert into storage.buckets (id, name, public, file_size_limit) values
    ('external-data', 'external-data', false, 5368709120)
on conflict (id) do update set file_size_limit = excluded.file_size_limit;
