do $$
begin
  assert (select count(*) from information_schema.schemata
          where schema_name in ('platform','vision','priority','geo','analysis')) = 5,
    'expected 5 domain schemas';
  assert (select count(*) from pg_extension where extname = 'postgis') = 1, 'postgis missing';
  assert (select count(*) from pg_extension where extname = 'pgmq') = 1, 'pgmq missing';
  assert (select count(*) from pg_extension where extname = 'pg_cron') = 1, 'pg_cron missing';
  assert (select count(*) from pg_extension where extname = 'pg_net') = 1, 'pg_net missing';
end $$;
