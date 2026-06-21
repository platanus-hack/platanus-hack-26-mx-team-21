-- 0205_app_map_observations_thumbnail.sql
-- Surface each map observation's provenance + thumbnail locator so the frontend can
-- render the real photo for citizen reports (WhatsApp) instead of a plain dot.
--
-- WHY: WhatsApp citizen reports (detector_name = 'whatsapp-citizen') store the reporter's
-- photo as a `ready` vision.observation_thumbnails row (bucket 'observation-thumbnails',
-- path 'observations/{id}/report.jpg'). The map payload didn't expose it, so pins were
-- always dots. We add `source` (the detector/provenance) and `thumb_path` (the ready
-- thumbnail's storage path, or null) — the browser builds a broker URL from path+bucket
-- and authorizes via public.app_authorize_object. Only `ready` thumbnails are returned.
--
-- The RETURNS TABLE signature gains columns, so `create or replace` cannot be used
-- (Postgres forbids changing a function's return type in place); drop + recreate.

drop function if exists public.app_map_observations();

create function public.app_map_observations()
returns table(
  id uuid, slug text,
  lat double precision, lng double precision,
  weight numeric, volume numeric, state text,
  zone text, district_cve text, district_name text,
  source text, thumb_path text)
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
    th.storage_path as thumb_path
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
