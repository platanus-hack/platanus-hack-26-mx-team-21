do $$
begin
  assert not exists (select 1 from storage.buckets where id='external-data'),
    'external-data supabase bucket should be removed';
  assert exists (select 1 from pg_attribute
    where attrelid='priority.external_signals'::regclass and attname='source_object_ref'),
    'external_signals.source_object_ref must remain';
end $$;
