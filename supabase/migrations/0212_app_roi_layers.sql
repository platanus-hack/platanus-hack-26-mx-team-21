-- 0212_app_roi_layers.sql
-- Per-dimension risk-zone layers: dimension-filtered/limited ROI reads + per-dimension counts.
-- Replaces the zero-arg app_current_rois() with a filtered/limited variant; adds
-- app_roi_dimension_counts() for the Layers panel. Follows 0200 conventions.

-- Drop the old zero-arg overload so a no-arg call resolves unambiguously to the new one.
drop function if exists public.app_current_rois();

create or replace function public.app_current_rois(
  p_dimensions text[] default null,
  p_limit int default 250
)
returns table(
  id uuid, risk_dimension text,
  centroid_lat double precision, centroid_lng double precision,
  risk_score real, dominant_type text, description text,
  signal_count int,
  geom_geojson jsonb)
language sql stable security definer set search_path = extensions, public as $$
  select
    r.id, r.risk_dimension,
    ST_Y(r.centroid::geometry) as centroid_lat,
    ST_X(r.centroid::geometry) as centroid_lng,
    r.risk_score, r.dominant_type, r.description,
    r.signal_count,
    ST_AsGeoJSON(r.geom::geometry)::jsonb as geom_geojson
  from priority.current_rois r
  join geo.tenant_boundary_versions b
    on b.tenant_id = public._app_tenant() and b.status = 'active'
  where ST_Contains(b.materialized_geometry, r.centroid::geometry)
    and (
      p_dimensions is null
      or array_length(p_dimensions, 1) is null
      or r.risk_dimension = any(p_dimensions)
    )
  order by r.risk_score desc
  limit greatest(1, least(coalesce(p_limit, 250), 2000));
$$;

create or replace function public.app_roi_dimension_counts()
returns table(risk_dimension text, roi_count int, max_risk real)
language sql stable security definer set search_path = extensions, public as $$
  select r.risk_dimension, count(*)::int as roi_count, max(r.risk_score) as max_risk
  from priority.current_rois r
  join geo.tenant_boundary_versions b
    on b.tenant_id = public._app_tenant() and b.status = 'active'
  where ST_Contains(b.materialized_geometry, r.centroid::geometry)
  group by r.risk_dimension
  order by r.risk_dimension;
$$;

grant execute on function public.app_current_rois(text[], int) to authenticated;
grant execute on function public.app_roi_dimension_counts() to authenticated;
