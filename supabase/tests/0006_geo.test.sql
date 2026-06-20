do $$
begin
  assert to_regclass('geo.geo_editions') is not null, 'geo_editions missing';
  assert to_regclass('geo.geo_areas') is not null, 'geo_areas missing';
  assert to_regclass('geo.tenant_boundary_versions') is not null, 'tenant_boundary_versions missing';
  assert to_regclass('geo.tenant_boundary_areas') is not null, 'tenant_boundary_areas missing';
  assert to_regclass('geo.observation_geo_bindings') is not null, 'observation_geo_bindings missing';
  -- geo_areas.geometry is a PostGIS geometry
  assert (select format_type(atttypid, atttypmod) from pg_attribute
          where attrelid='geo.geo_areas'::regclass and attname='geometry') like 'geometry%',
    'geo_areas.geometry must be geometry';
  -- one active boundary per tenant
  assert exists (select 1 from pg_indexes where schemaname='geo'
    and indexname='tenant_boundary_active_ux'), 'single-active-boundary index missing';
  -- one active edition globally
  assert exists (select 1 from pg_indexes where schemaname='geo'
    and indexname='geo_editions_active_ux'), 'single-active-edition index missing';
end $$;
