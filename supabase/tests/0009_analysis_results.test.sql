do $$
begin
  assert to_regclass('vision.vision_outbox_events') is not null, 'vision_outbox_events missing';
  assert to_regclass('analysis.analysis_outbox_events') is not null, 'analysis_outbox_events missing';
  assert to_regclass('analysis.analysis_attempts') is not null, 'analysis_attempts missing';
  assert to_regclass('analysis.analysis_results') is not null, 'analysis_results missing';
  assert to_regclass('analysis.result_metrics') is not null, 'result_metrics missing';
  assert to_regclass('analysis.result_warnings') is not null, 'result_warnings missing';
  assert to_regclass('analysis.artifacts') is not null, 'artifacts missing';
  assert to_regclass('analysis.map_features') is not null, 'map_features missing';
  assert to_regclass('analysis.artifact_observation_refs') is not null, 'artifact_observation_refs missing';
  assert to_regclass('analysis.sequence_items') is not null, 'sequence_items missing';
  assert to_regclass('analysis.asset_refs') is not null, 'asset_refs missing';
  -- one result per run
  assert exists (select 1 from pg_constraint
    where conrelid='analysis.analysis_results'::regclass and contype='u'
      and pg_get_constraintdef(oid) ilike '%run_id%'), 'one-result-per-run unique missing';
  -- attempt number unique within run
  assert exists (select 1 from pg_constraint
    where conrelid='analysis.analysis_attempts'::regclass and contype='u'
      and pg_get_constraintdef(oid) ilike '%attempt_number%'), 'attempt uniqueness missing';
end $$;
