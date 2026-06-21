-- 0202_real_cdmx_boundary.sql
-- Replace the coarse seed boundary (a 25-point, 3-rectangle MultiPolygon that rendered
-- as "3 gray boxes") for the CDMX tenant with a real Ciudad de México outline
-- (entidad 09). Source: angelnmara/geojson (simplified, ~35 pts), SRID 4326. Stored as
-- MultiPolygon to match the prior geometry type.
--
-- Safety (verified before applying):
--   * app_tenant_boundary() returns this geometry verbatim.
--   * app_current_rois() clips ROIs to it via ST_Contains — all 5 current ROIs remain inside.
--   * app_map_observations() is tenant-scoped (tenant_visible_observations), NOT
--     boundary-clipped, so observations are unaffected.
do $$
declare
  v_geom geometry;
begin
  v_geom := ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(
    '{"type":"Polygon","coordinates":[[[-98.8652,19.0714],[-98.9033,19.0724],[-98.997,19.0438],[-99.0333,19.0743],[-99.0584,19.0695],[-99.1168,19.0284],[-99.1637,19.0729],[-99.2168,19.0637],[-99.2361,19.0864],[-99.2825,19.1607],[-99.2951,19.1902],[-99.3217,19.2299],[-99.3255,19.267],[-99.3038,19.2946],[-99.255,19.3298],[-99.2265,19.3434],[-99.199,19.3714],[-99.1768,19.4463],[-99.1255,19.4984],[-99.1043,19.5293],[-99.0743,19.526],[-99.0763,19.4859],[-99.0424,19.4588],[-99.0134,19.4129],[-98.9941,19.3545],[-98.9816,19.3366],[-98.9245,19.3013],[-98.9086,19.2864],[-98.9057,19.2448],[-98.8772,19.2448],[-98.868,19.226],[-98.854,19.1661],[-98.8555,19.1303],[-98.8729,19.1028],[-98.8652,19.0714]]]}'
  ), 4326));

  update geo.tenant_boundary_versions
     set materialized_geometry = v_geom,
         geometry_checksum = md5(ST_AsBinary(v_geom))
   where tenant_id = 'a0000000-0000-0000-0000-000000000001'
     and status = 'active';
end $$;
