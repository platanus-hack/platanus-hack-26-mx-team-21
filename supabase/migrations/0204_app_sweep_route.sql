-- 0204_app_sweep_route.sql
-- Public, security-definer read API for the "Ver recorrido" (sweep) view.
--
-- An observation is captured during a vision SWEEP — a single inspection run that
-- covers a contiguous area of the city. vision.sweeps.coverage is that run's covered
-- footprint (a polygon), NOT a GPS breadcrumb track: ordering the detections by their
-- media offset zig-zags across the whole city, so the honest geometry to draw for a
-- sweep is its coverage polygon plus the count of observations it surfaced.
--
-- app_sweep_route(p_observation_id) resolves the sweep behind one observation and
-- returns that sweep's coverage (as GeoJSON), time window, tenant-visible observation
-- count, covered area, and the originating observation's position so the client can
-- frame the view. Tenant-scoped and clipped exactly like the rest of the app_* layer.
create or replace function public.app_sweep_route(p_observation_id uuid)
returns table(
  sweep text,
  started_at timestamptz,
  ended_at timestamptz,
  obs_count int,
  area_km2 double precision,
  coverage_geojson jsonb,
  origin_lat double precision,
  origin_lng double precision)
language sql stable security definer set search_path = extensions, public as $$
  with src as (
    -- the originating observation, only if visible to the caller's tenant
    select o.id, o.sweep_id,
           ST_Y(o.location::geometry) as origin_lat,
           ST_X(o.location::geometry) as origin_lng
    from vision.observations o
    where o.id = p_observation_id
      and exists (
        select 1 from platform.tenant_visible_observations tvo
        where tvo.observation_id = o.id and tvo.tenant_id = public._app_tenant())
  )
  select
    'SWP-' || upper(substr(s.id::text, 1, 4)) as sweep,
    s.started_at,
    s.ended_at,
    (select count(*)::int
       from vision.observations o2
       join platform.tenant_visible_observations tvo2
         on tvo2.observation_id = o2.id and tvo2.tenant_id = public._app_tenant()
      where o2.sweep_id = s.id) as obs_count,
    ST_Area(s.coverage::geography) / 1000000.0 as area_km2,
    ST_AsGeoJSON(s.coverage::geometry)::jsonb as coverage_geojson,
    src.origin_lat,
    src.origin_lng
  from src
  join vision.sweeps s on s.id = src.sweep_id;
$$;

grant execute on function public.app_sweep_route(uuid) to authenticated;
