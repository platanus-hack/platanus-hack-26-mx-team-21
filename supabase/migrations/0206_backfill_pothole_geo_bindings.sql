-- 0206_backfill_pothole_geo_bindings.sql
-- Backfill alcaldía (AGEM) geo-bindings for pothole observations so the map's region
-- filter works.
--
-- WHY: app_map_observations exposes each observation's district_cve/district_name from
-- geo.observation_geo_bindings (the AGEM area whose polygon contains the point). The
-- 230k seeded potholes — the ONLY enabled issue type — were never bound, so district_cve
-- was always null. That emptied the region popover, made the plan's region filter select
-- zero points, and made the natural-language agent silently drop every alcaldía it parsed
-- (it resolves region NAMES against the populated `regions` list). The other issue types
-- were already bound; only potholes were missing.
--
-- FIX: point-in-polygon every current pothole against the active edition's 7 loaded AGEM
-- polygons (+ the single AGEE state area) and insert the binding. Idempotent — the PK is
-- (observation_id, edition_id), so re-running is a no-op. Potholes outside the 7 loaded
-- alcaldías simply stay unbound (no AGEM polygon contains them) and remain "all regions".

insert into geo.observation_geo_bindings
  (observation_id, edition_id, agee_area_id, agem_area_id, bound_at)
select o.id, ed.id, agee.id, agem.id, now()
from (select id from geo.geo_editions where status = 'active') ed
join geo.geo_areas agee
  on agee.edition_id = ed.id and agee.level = 'AGEE'
join geo.geo_areas agem
  on agem.edition_id = ed.id and agem.level = 'AGEM'
join vision.observations o
  on o.superseded_by_observation_id is null
 and o.resolved_at is null
 and ST_Contains(agem.geometry, o.location::geometry)
join vision.observation_types ot
  on ot.id = o.observation_type_id and ot.slug = 'pothole'
on conflict (observation_id, edition_id) do nothing;
