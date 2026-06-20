do $$
begin
  assert to_regclass('priority.external_signals') is not null, 'external_signals missing';
  assert (select format_type(atttypid,atttypmod) from pg_attribute
          where attrelid='priority.external_signals'::regclass and attname='geom') like 'geography%',
    'geom must be geography';
  assert exists (select 1 from pg_constraint
    where conrelid='priority.external_signals'::regclass and contype='c'
      and pg_get_constraintdef(oid) ilike '%risk_dimension%'), 'dimension check missing';
end $$;
