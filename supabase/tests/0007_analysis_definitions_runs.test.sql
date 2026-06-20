do $$
begin
  assert to_regclass('analysis.analysis_providers') is not null, 'analysis_providers missing';
  assert to_regclass('analysis.analysis_definitions') is not null, 'analysis_definitions missing';
  assert to_regclass('analysis.analysis_definition_versions') is not null, 'definition_versions missing';
  assert to_regclass('analysis.provider_capability_snapshots') is not null, 'capability_snapshots missing';
  assert to_regclass('analysis.analysis_runs') is not null, 'analysis_runs missing';
  assert to_regclass('analysis.run_scope_areas') is not null, 'run_scope_areas missing';
  assert to_regclass('analysis.run_scope_geometry') is not null, 'run_scope_geometry missing';
  assert to_regclass('analysis.run_type_settings') is not null, 'run_type_settings missing';
  -- idempotency unique within tenant
  assert exists (select 1 from pg_constraint
    where conrelid='analysis.analysis_runs'::regclass and contype='u'
      and pg_get_constraintdef(oid) ilike '%idempotency_key%'), 'idempotency unique missing';
end $$;
