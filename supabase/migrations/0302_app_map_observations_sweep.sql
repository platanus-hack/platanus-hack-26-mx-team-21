-- 0302_app_map_observations_sweep.sql
-- Tag each map observation with its inspection sweep so the client can highlight
-- "Ver recorrido" — dimming every pin except the ones captured in the same sweep.
-- Each sweep covers a distinct contiguous region of the city, so the highlighted set
-- reads as one continuous cluster. The label matches app_observation_detail.sweep.
--
-- The RETURNS TABLE signature gains a column, so drop + recreate (Postgres forbids
-- changing a function's return type in place).

drop function if exists public.app_map_observations();

create function public.app_map_observations()
returns table(
  id uuid, slug text,
  lat double precision, lng double precision,
  weight numeric, volume numeric, state text,
  zone text, district_cve text, district_name text,
  source text, thumb_path text, sweep text)
language sql stable security definer set search_path = extensions, public as $$
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
  from platform.tenant_visible_observations tvo
  join vision.observations o on o.id = tvo.observation_id
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
  where tvo.tenant_id = public._app_tenant();
$$;

grant execute on function public.app_map_observations() to authenticated;
