do $$
begin
  assert to_regclass('analysis.run_observations') is not null, 'run_observations missing';
  assert to_regclass('analysis.run_observation_attributes') is not null, 'run_observation_attributes missing';
  assert to_regclass('analysis.run_priority_values') is not null, 'run_priority_values missing';
  assert to_regclass('analysis.run_observation_exclusions') is not null, 'run_observation_exclusions missing';
  -- composite PK (run_id, observation_id) on run_observations (target of later artifact refs)
  assert (select count(*) from pg_constraint
    where conrelid='analysis.run_observations'::regclass and contype='p') = 1, 'run_observations PK missing';
  -- exclusion reason constraint
  assert exists (select 1 from pg_constraint
    where conrelid='analysis.run_observation_exclusions'::regclass and contype='c'
      and pg_get_constraintdef(oid) ilike '%unscored%'), 'exclusion reason check missing';
end $$;
