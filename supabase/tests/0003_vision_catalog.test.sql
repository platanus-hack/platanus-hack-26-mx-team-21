do $$
begin
  assert to_regclass('vision.sources') is not null, 'vision.sources missing';
  assert to_regclass('vision.observation_types') is not null, 'vision.observation_types missing';
  assert to_regclass('vision.observation_attribute_definitions') is not null, 'attr defs missing';
  assert to_regclass('vision.observation_attribute_options') is not null, 'attr options missing';
  assert to_regclass('vision.sweeps') is not null, 'vision.sweeps missing';
  assert to_regclass('vision.sweep_assessed_types') is not null, 'sweep_assessed_types missing';
  assert to_regclass('vision.recordings') is not null, 'vision.recordings missing';
  -- coverage is geography
  assert (select format_type(atttypid, atttypmod) from pg_attribute
          where attrelid='vision.sweeps'::regclass and attname='coverage') like 'geography%',
    'sweeps.coverage must be geography';
  -- value_kind constraint present
  assert exists (select 1 from pg_constraint
    where conrelid='vision.observation_attribute_definitions'::regclass and contype='c'
      and pg_get_constraintdef(oid) ilike '%value_kind%'), 'value_kind check missing';
end $$;
