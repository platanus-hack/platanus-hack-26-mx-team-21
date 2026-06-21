-- 0303_app_map_observations_limit.sql
-- Bound the map observations payload. A bulk CDMX pothole import (~183k rows for the
-- demo tenant) made the unbounded app_map_observations() return tens of MB / ~10s; the
-- browser never finished loading it, so the map hung on its loading spinner ("crash").
-- A naive `order by … limit N` does NOT help: the sort still has to read all 183k tenant
-- rows, which blows past the authenticated role's statement_timeout (PostgREST → 57014).
--
-- A city PRIORITY map only needs the most relevant pins, so we cap the result to 1000 ids
-- (matching PostgREST's db-max-rows) chosen WITHOUT a global sort, in two cheap stages:
--
--   meaningful  — the always-keep set, reached purely through indexes:
--                   1. every priority-scored observation (the actual "priority" rows)
--                   2. every citizen photo report (ready thumbnail → renders as a marker)
--                   3. every non-pothole type (keeps each layer populated; tens of rows)
--                 then intersected with the tenant via an EXISTS probe per id.
--   fill        — any of the tenant's observations, unordered `limit 1000` → the index-only
--                 scan early-stops, so the 183k flood is never fully read.
--
-- ranked unions the two (meaningful first, so it survives the cap) and limits to 4000.
-- Result: ~0.9s server-side instead of ~10s, ~1MB payload instead of ~50MB. The client
-- doesn't depend on row order (MapCanvas derives its own colour scale), so dropping the
-- global ordering is safe. Signature is unchanged from 0302 → create-or-replace.

create or replace function public.app_map_observations()
returns table(
  id uuid, slug text,
  lat double precision, lng double precision,
  weight numeric, volume numeric, state text,
  zone text, district_cve text, district_name text,
  source text, thumb_path text, sweep text)
language sql stable security definer set search_path = extensions, public as $$
  -- Each "always-keep" source is a MATERIALIZED CTE: an optimization fence. Without it the
  -- planner folds the non-pothole lookup into the tenant join and reads observations in pk
  -- order (full 230k-row scan); fenced, np_obs runs standalone via the observation_type_id
  -- index (~tens of rows, ~26 pages). (Stale stats after a bulk import can also trigger the
  -- full scan — keep table stats fresh; this fix holds regardless.)
  with np_obs as materialized (
    -- every non-pothole type (keeps each layer populated; tens of rows)
    select o.id
    from vision.observations o
    where o.observation_type_id = any (array(
      select id from vision.observation_types where slug <> 'pothole'))
  ),
  scored as materialized (
    -- priority-scored observations (the actual "priority" rows)
    select cpv.observation_id as id
    from priority.current_priority_values cpv
    where cpv.model_id = (select id from priority.priority_models where status = 'active')
  ),
  photos as materialized (
    -- citizen photo reports (ready thumbnail → renders as a marker)
    select th.observation_id as id
    from vision.observation_thumbnails th
    where th.storage_bucket = 'observation-thumbnails' and th.status = 'ready'
  ),
  meaningful_tenant as (
    select m.id
    from (select id from np_obs union select id from scored union select id from photos) m
    where exists (
      select 1 from platform.tenant_visible_observations tvo
      where tvo.tenant_id = public._app_tenant() and tvo.observation_id = m.id)
  ),
  fill as (
    select tvo.observation_id as id
    from platform.tenant_visible_observations tvo
    where tvo.tenant_id = public._app_tenant()
    limit 1000
  ),
  ranked as (
    -- Cap at 1000 to match PostgREST's db-max-rows: returning more is wasted work the API
    -- truncates anyway. `ord` (0 = meaningful, 1 = fill) is carried out so the final SELECT
    -- can keep the always-keep set ahead of the pothole fill — otherwise the API's row cut
    -- could silently drop scored/non-pothole/photo rows that sorted past the cap.
    select id, min(ord) as ord
    from (
      select id, 0 as ord from meaningful_tenant
      union all
      select id, 1 as ord from fill
    ) u
    group by id
    order by min(ord)
    limit 1000
  )
  select
    o.id, ot.slug,
    ST_Y(o.location::geometry) as lat,
    ST_X(o.location::geometry) as lng,
    pv.weight,
    q.qty as volume,
    case when pv.weight is null then 'pending' else 'scored' end as state,
    coalesce(nullif(ageb.name, ''), agem.name) as zone,
    agem.cve_mun as district_cve,
    agem.name as district_name,
    o.detector_name as source,
    th.storage_path as thumb_path,
    'SWP-' || upper(substr(o.sweep_id::text, 1, 4)) as sweep
  from ranked r
  join vision.observations o on o.id = r.id
  join vision.observation_types ot on ot.id = o.observation_type_id
  left join priority.current_priority_values cpv
    on cpv.observation_id = o.id
   and cpv.model_id = (select id from priority.priority_models where status = 'active')
  left join priority.priority_values pv on pv.id = cpv.priority_value_id
  left join geo.observation_geo_bindings b
    on b.observation_id = o.id
   and b.edition_id = (select id from geo.geo_editions where status = 'active')
  left join geo.geo_areas agem on agem.id = b.agem_area_id
  left join geo.geo_areas ageb on ageb.id = b.ageb_area_id
  left join lateral (
    select av.number_value as qty
    from vision.observation_attribute_values av
    join vision.observation_attribute_definitions d on d.id = av.definition_id
    where av.observation_id = o.id and av.number_value is not null and d.unit is not null
    order by d.key
    limit 1
  ) q on true
  left join vision.observation_thumbnails th
    on th.observation_id = o.id
   and th.storage_bucket = 'observation-thumbnails'
   and th.status = 'ready'
  order by r.ord; -- meaningful set first, so the API row cap never drops it
$$;

grant execute on function public.app_map_observations() to authenticated;
