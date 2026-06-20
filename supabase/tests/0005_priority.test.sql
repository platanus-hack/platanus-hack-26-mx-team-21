do $$
begin
  assert to_regclass('priority.priority_models') is not null, 'priority_models missing';
  assert to_regclass('priority.priority_batches') is not null, 'priority_batches missing';
  assert to_regclass('priority.priority_batch_items') is not null, 'priority_batch_items missing';
  assert to_regclass('priority.priority_values') is not null, 'priority_values missing';
  assert to_regclass('priority.current_priority_values') is not null, 'current_priority_values missing';
  -- only one active model allowed (partial unique index)
  assert exists (select 1 from pg_indexes where schemaname='priority'
    and indexname='priority_models_active_ux'), 'single-active-model index missing';
end $$;
