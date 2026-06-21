-- 0304_app_sweep_route_video.sql
-- Surface the sweep's recorded video in the "Ver recorrido" overlay.
--
-- A sweep can carry a vision.recordings row (the inspection footage in R2's sweep-video
-- bucket). app_sweep_route already returns the coverage footprint + metadata; here we add
-- the video pointer (bucket + path) plus duration/fps so the client can stream the clip
-- through the R2 broker while the coverage overlay is up. We pick the sweep's most recent
-- READY recording (a sweep usually has one); null columns when there's no footage, so the
-- player simply doesn't render.
--
-- The RETURNS TABLE signature gains columns, so drop + recreate (Postgres forbids changing
-- a function's return type in place). Body is otherwise identical to 0204.

drop function if exists public.app_sweep_route(uuid);

create function public.app_sweep_route(p_observation_id uuid)
returns table(
  sweep text,
  started_at timestamptz,
  ended_at timestamptz,
  obs_count int,
  area_km2 double precision,
  coverage_geojson jsonb,
  origin_lat double precision,
  origin_lng double precision,
  video_bucket text,
  video_path text,
  video_duration_ms int,
  video_fps real)
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
    src.origin_lng,
    rec.storage_bucket as video_bucket,
    rec.storage_path   as video_path,
    rec.duration_ms    as video_duration_ms,
    rec.fps            as video_fps
  from src
  join vision.sweeps s on s.id = src.sweep_id
  left join lateral (
    select r.storage_bucket, r.storage_path, r.duration_ms, r.fps
    from vision.recordings r
    where r.sweep_id = s.id and r.status = 'ready'
    order by r.started_at desc
    limit 1
  ) rec on true;
$$;

grant execute on function public.app_sweep_route(uuid) to authenticated;
