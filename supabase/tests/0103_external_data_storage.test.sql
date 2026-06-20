do $$
begin
  assert exists (select 1 from storage.buckets where id='external-data' and public=false),
    'external-data bucket missing';
end $$;
