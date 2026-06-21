-- 0200_app_read_api.sql
-- Public, security-definer read API for the Vialia map web client.
--
-- WHY THIS LAYER EXISTS: the browser authenticates as the `authenticated` role,
-- which has NO usage/select on the custom schemas (vision/priority/geo/analysis/platform)
-- by design. Every browser read therefore goes through these `public.app_*` functions,
-- which run as the function owner (security definer), resolve the caller's tenant from
-- their JWT, and return UI-shaped rows already clipped to the tenant boundary.
--
-- The functions resolve tenant from the membership behind auth.uid() (no app.tenant_id
-- GUC needed over PostgREST) and join the cached geo-clip platform.tenant_visible_observations.

-- ---------------------------------------------------------------------------
-- Internal: resolve the caller's active tenant from their JWT subject.
-- Prefers an analysis_author membership, then any viewer membership.
-- ---------------------------------------------------------------------------
create or replace function public._app_tenant()
returns uuid
language sql stable security definer set search_path = '' as $$
  select m.tenant_id
  from platform.tenant_memberships m
  join platform.oidc_subjects s on s.id = m.subject_id
  join platform.tenants t on t.id = m.tenant_id
  where s.user_id = auth.uid()
    and t.status = 'active'
  order by case when m.role = 'analysis_author' then 0 else 1 end, t.created_at
  limit 1;
$$;

-- ---------------------------------------------------------------------------
-- app_active_tenant() — caller's resolved tenant + UI accent. Errors if none.
-- ---------------------------------------------------------------------------
create or replace function public.app_active_tenant()
returns table(tenant_id uuid, tenant_name text, accent text)
language plpgsql stable security definer set search_path = '' as $$
declare v_tenant uuid := public._app_tenant();
begin
  if v_tenant is null then
    raise exception 'no active tenant for caller' using errcode = '42501';
  end if;
  return query
    select t.id, t.name, '#2f64e6'::text
    from platform.tenants t
    where t.id = v_tenant;
end $$;

-- ---------------------------------------------------------------------------
-- app_observation_types_counts() — type catalog + current in-boundary counts.
-- is_latent = not auto_resolvable (matches the reference LATENT styling).
-- ---------------------------------------------------------------------------
create or replace function public.app_observation_types_counts()
returns table(slug text, label text, category text, is_latent boolean, current_count int)
language sql stable security definer set search_path = '' as $$
  select ot.slug, ot.label, ot.category, (not ot.auto_resolvable) as is_latent,
         count(o.id)::int as current_count
  from vision.observation_types ot
  left join vision.observations o
    on o.observation_type_id = ot.id
   and exists (
        select 1 from platform.tenant_visible_observations tvo
        where tvo.observation_id = o.id and tvo.tenant_id = public._app_tenant())
  where ot.status = 'active'
  group by ot.id, ot.slug, ot.label, ot.category, ot.auto_resolvable
  order by ot.label;
$$;

-- ---------------------------------------------------------------------------
-- app_map_observations() — current, in-boundary observations with priority
-- weight (active model), pending/scored state, and district/zone names.
-- ---------------------------------------------------------------------------
create or replace function public.app_map_observations()
returns table(
  id uuid, slug text,
  lat double precision, lng double precision,
  weight numeric, state text,
  zone text, district_cve text, district_name text)
language sql stable security definer set search_path = extensions, public as $$
  select
    o.id, ot.slug,
    ST_Y(o.location::geometry) as lat,
    ST_X(o.location::geometry) as lng,
    pv.weight,
    case when pv.weight is null then 'pending' else 'scored' end as state,
    coalesce(nullif(ageb.name, ''), agem.name) as zone,
    agem.cve_mun as district_cve,
    agem.name as district_name
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
  where tvo.tenant_id = public._app_tenant();
$$;

-- ---------------------------------------------------------------------------
-- app_observation_detail(p_id) — everything the ObservationCard renders.
-- Returns no rows if the observation is not visible to the caller's tenant.
-- ---------------------------------------------------------------------------
create or replace function public.app_observation_detail(p_id uuid)
returns table(
  id uuid, slug text, label text,
  lat double precision, lng double precision,
  weight numeric, state text,
  qty numeric, unit text,
  confirmations int, misses int, conf real,
  observed_at timestamptz,
  sweep text, recording_id text, frame_ref text,
  image_bbox jsonb, detector text,
  district_name text, zone text)
language sql stable security definer set search_path = extensions, public as $$
  select
    o.id, ot.slug, ot.label,
    ST_Y(o.location::geometry) as lat,
    ST_X(o.location::geometry) as lng,
    pv.weight,
    case when pv.weight is null then 'pending' else 'scored' end as state,
    q.qty, q.unit,
    o.confirmation_count, o.miss_count, cf.conf,
    o.observed_at,
    'SWP-' || upper(substr(o.sweep_id::text, 1, 4)) as sweep,
    case when o.recording_id is null then null
         else 'rec_' || substr(o.recording_id::text, 1, 8) end as recording_id,
    o.frame_ref,
    o.image_bbox,
    o.detector_name || ' ' || o.detector_version as detector,
    agem.name as district_name,
    coalesce(nullif(ageb.name, ''), agem.name) as zone
  from vision.observations o
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
    select av.number_value as qty, d.unit
    from vision.observation_attribute_values av
    join vision.observation_attribute_definitions d on d.id = av.definition_id
    where av.observation_id = o.id and av.number_value is not null and d.unit is not null
    order by d.key
    limit 1
  ) q on true
  left join lateral (
    select av.number_value::real as conf
    from vision.observation_attribute_values av
    join vision.observation_attribute_definitions d on d.id = av.definition_id
    where av.observation_id = o.id and d.key = 'confidence'
    limit 1
  ) cf on true
  where o.id = p_id
    and exists (
      select 1 from platform.tenant_visible_observations tvo
      where tvo.observation_id = o.id and tvo.tenant_id = public._app_tenant());
$$;

-- ---------------------------------------------------------------------------
-- app_current_rois() — current ROIs whose centroid falls in the tenant boundary.
-- ---------------------------------------------------------------------------
create or replace function public.app_current_rois()
returns table(
  id uuid, risk_dimension text,
  centroid_lat double precision, centroid_lng double precision,
  risk_score real, dominant_type text, description text,
  geom_geojson jsonb)
language sql stable security definer set search_path = extensions, public as $$
  select
    r.id, r.risk_dimension,
    ST_Y(r.centroid::geometry) as centroid_lat,
    ST_X(r.centroid::geometry) as centroid_lng,
    r.risk_score, r.dominant_type, r.description,
    ST_AsGeoJSON(r.geom::geometry)::jsonb as geom_geojson
  from priority.current_rois r
  join geo.tenant_boundary_versions b
    on b.tenant_id = public._app_tenant() and b.status = 'active'
  where ST_Contains(b.materialized_geometry, r.centroid::geometry);
$$;

-- ---------------------------------------------------------------------------
-- app_tenant_boundary() — active boundary geometry as GeoJSON (the CDMX outline).
-- ---------------------------------------------------------------------------
create or replace function public.app_tenant_boundary()
returns jsonb
language sql stable security definer set search_path = extensions, public as $$
  select ST_AsGeoJSON(b.materialized_geometry)::jsonb
  from geo.tenant_boundary_versions b
  where b.tenant_id = public._app_tenant() and b.status = 'active';
$$;

-- ---------------------------------------------------------------------------
-- app_list_runs() — analysis run history (newest first), tenant-scoped.
-- ---------------------------------------------------------------------------
create or replace function public.app_list_runs()
returns table(
  id uuid, kind text, budget numeric, status text,
  created_at timestamptz, is_latent boolean)
language sql stable security definer set search_path = '' as $$
  select r.id, d.kind, r.budget_amount, r.status, r.created_at,
         (d.kind like 'inspection%' or d.kind like '%latent%') as is_latent
  from analysis.analysis_runs r
  join analysis.analysis_definition_versions dv on dv.id = r.definition_version_id
  join analysis.analysis_definitions d on d.id = dv.definition_id
  where r.tenant_id = public._app_tenant()
  order by r.created_at desc;
$$;

-- ---------------------------------------------------------------------------
-- app_get_run(p_id) — re-hydrate a past run's result payload for the dock.
-- ---------------------------------------------------------------------------
create or replace function public.app_get_run(p_id uuid)
returns jsonb
language sql stable security definer set search_path = '' as $$
  select coalesce(res.payload, '{}'::jsonb)
         || jsonb_build_object(
              'run_id', r.id,
              'kind', d.kind,
              'budget', r.budget_amount,
              'status', r.status,
              'is_latent', (d.kind like 'inspection%' or d.kind like '%latent%'))
  from analysis.analysis_runs r
  join analysis.analysis_definition_versions dv on dv.id = r.definition_version_id
  join analysis.analysis_definitions d on d.id = dv.definition_id
  left join analysis.analysis_results res on res.run_id = r.id
  where r.id = p_id and r.tenant_id = public._app_tenant();
$$;

-- ---------------------------------------------------------------------------
-- Grants: only authenticated users may call the API. Internal helper too
-- (it is invoked inside the definer functions but grant for completeness).
-- ---------------------------------------------------------------------------
grant execute on function public._app_tenant() to authenticated;
grant execute on function public.app_active_tenant() to authenticated;
grant execute on function public.app_observation_types_counts() to authenticated;
grant execute on function public.app_map_observations() to authenticated;
grant execute on function public.app_observation_detail(uuid) to authenticated;
grant execute on function public.app_current_rois() to authenticated;
grant execute on function public.app_tenant_boundary() to authenticated;
grant execute on function public.app_list_runs() to authenticated;
grant execute on function public.app_get_run(uuid) to authenticated;
