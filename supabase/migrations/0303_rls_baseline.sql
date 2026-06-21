-- Deny-by-default Row-Level Security across every table in the application's custom
-- schemas (platform / vision / priority / geo / analysis).
--
-- WHY: until now only 4 tables had RLS (0012, 0300, 0302). The other ~50 relied solely on
-- the ABSENCE of schema-usage grants to anon/authenticated. That is a single layer — one
-- stray `grant usage on schema vision to authenticated` (or pointing PostgREST at these
-- schemas) would expose every row with no backstop. This migration adds that backstop.
--
-- HOW IT STAYS SAFE / A NO-OP FOR THE APP:
--   * Browser reads go through `public.app_*` SECURITY DEFINER functions. A definer function
--     runs as its owner (the migration/superuser role), which BYPASSES RLS (we do NOT use
--     FORCE ROW LEVEL SECURITY), so those functions return exactly what they do today. This
--     is already proven in prod: vision.observations + platform.tenant_visible_observations
--     have had RLS since 0012 and app_map_observations still serves the map.
--   * The API and workers connect as the postgres/service_role role (superuser / BYPASSRLS),
--     so direct writes (citizen ingest, dataset load, materialization, drain_outbox) are
--     unaffected.
--   * anon/authenticated have no grants on these schemas, so for them RLS-enabled-with-no-policy
--     means deny-all — which is the intended hardening: if a grant is ever added by mistake,
--     access is still denied by default.
--
-- Enabling RLS with no policy is the deny-by-default. We intentionally add NO policies here;
-- access continues exclusively through the curated definer API and bypassing roles.
--
-- Idempotent and complete: the loop enables RLS on every base table in these schemas that
-- doesn't already have it (skipping the 4 already enabled), so it can be re-run safely.
-- NOTE: tables created by FUTURE migrations must enable their own RLS — this baseline runs once.

do $$
declare r record;
begin
  for r in
    select n.nspname, c.relname
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where c.relkind = 'r'
      and n.nspname in ('platform', 'vision', 'priority', 'geo', 'analysis')
      and not c.relrowsecurity
    order by n.nspname, c.relname
  loop
    execute format('alter table %I.%I enable row level security', r.nspname, r.relname);
    raise notice 'RLS enabled: %.%', r.nspname, r.relname;
  end loop;
end $$;
