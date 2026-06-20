insert into vision.sources(slug,name) values ('seed_truck','Seed truck') on conflict do nothing;
insert into vision.observation_types(slug,label,category,merge_radius_m,auto_resolvable)
  values ('pothole','Pothole','road_surface',10,true),
         ('missing_streetlight','Missing streetlight','lighting',15,false)
  on conflict (slug) do nothing;

insert into priority.priority_models(name,version,status)
  values ('baseline','v1','active') on conflict (name,version) do nothing;

insert into platform.tenants(name) values ('Dev Tenant') on conflict do nothing;
insert into geo.geo_editions(source_name,source_release,status)
  values ('seed-inegi','2020','active') on conflict do nothing;

-- A dev boundary covering a CDMX-ish bbox so the inside/outside cache logic is exercisable.
insert into geo.tenant_boundary_versions(tenant_id, edition_id, version_number, status, materialized_geometry)
select t.id, e.id, 1, 'active',
       ST_Multi(ST_GeomFromText('POLYGON((-99.3 19.2,-99.3 19.6,-98.9 19.6,-98.9 19.2,-99.3 19.2))',4326))
  from platform.tenants t, geo.geo_editions e
 where t.name='Dev Tenant' and e.source_name='seed-inegi'
 on conflict (tenant_id, version_number) do nothing;
