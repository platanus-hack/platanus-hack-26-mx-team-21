set search_path = public, extensions;

insert into platform.tenants (id, name, status) values
  ('a0000000-0000-0000-0000-000000000001','Vialia CDMX','active')
on conflict do nothing;

insert into geo.geo_editions (id, source_name, source_release, effective_date, status, imported_at) values
  ('ed000000-0000-0000-0000-000000000001','INEGI MGN (synthetic fixture)','2020','2020-03-15','active','2026-06-01 00:00:00+00')
on conflict do nothing;

-- AGEE (state of CDMX)
insert into geo.geo_areas (id, edition_id, level, source_cvegeo, cve_ent, name, geometry) values
  ('9e000000-0000-0000-0000-000000000009','ed000000-0000-0000-0000-000000000001','AGEE','09','09','Ciudad de México',
     ST_Multi(ST_MakeEnvelope(-99.30,19.25,-98.95,19.55,4326)))
on conflict do nothing;

-- AGEM alcaldías (boxes around zone centers). parent = AGEE.
insert into geo.geo_areas (id, edition_id, level, source_cvegeo, cve_ent, cve_mun, name, parent_area_id, geometry) values
  ('9e000000-0000-0000-0000-000000000015','ed000000-0000-0000-0000-000000000001','AGEM','09015','09','015','Cuauhtémoc','9e000000-0000-0000-0000-000000000009',          ST_Multi(ST_MakeEnvelope(-99.158,19.407,-99.108,19.457,4326))),
  ('9e000000-0000-0000-0000-000000000007','ed000000-0000-0000-0000-000000000001','AGEM','09007','09','007','Iztapalapa','9e000000-0000-0000-0000-000000000009',          ST_Multi(ST_MakeEnvelope(-99.095,19.322,-99.025,19.392,4326))),
  ('9e000000-0000-0000-0000-000000000003','ed000000-0000-0000-0000-000000000001','AGEM','09003','09','003','Coyoacán','9e000000-0000-0000-0000-000000000009',            ST_Multi(ST_MakeEnvelope(-99.190,19.317,-99.134,19.373,4326))),
  ('9e000000-0000-0000-0000-000000000005','ed000000-0000-0000-0000-000000000001','AGEM','09005','09','005','Gustavo A. Madero','9e000000-0000-0000-0000-000000000009',   ST_Multi(ST_MakeEnvelope(-99.145,19.449,-99.075,19.519,4326))),
  ('9e000000-0000-0000-0000-000000000010','ed000000-0000-0000-0000-000000000001','AGEM','09010','09','010','Álvaro Obregón','9e000000-0000-0000-0000-000000000009',      ST_Multi(ST_MakeEnvelope(-99.230,19.330,-99.170,19.390,4326))),
  ('9e000000-0000-0000-0000-000000000017','ed000000-0000-0000-0000-000000000001','AGEM','09017','09','017','Venustiano Carranza','9e000000-0000-0000-0000-000000000009', ST_Multi(ST_MakeEnvelope(-99.122,19.408,-99.078,19.452,4326))),
  ('9e000000-0000-0000-0000-000000000012','ed000000-0000-0000-0000-000000000001','AGEM','09012','09','012','Tlalpan','9e000000-0000-0000-0000-000000000009',            ST_Multi(ST_MakeEnvelope(-99.205,19.255,-99.135,19.325,4326)))
on conflict do nothing;

-- Active boundary = union of the 6 IN-boundary AGEMs (excludes Tlalpan 012)
insert into geo.tenant_boundary_versions
  (id, tenant_id, edition_id, version_number, status, materialized_geometry, geometry_checksum, created_at, activated_at)
select
  'b0000000-0000-0000-0000-000000000001','a0000000-0000-0000-0000-000000000001','ed000000-0000-0000-0000-000000000001',1,'active',
  ST_Multi(ST_Union(a.geometry)), 'seed-boundary-v1','2026-06-01 00:00:00+00','2026-06-01 00:00:00+00'
from geo.geo_areas a
where a.edition_id='ed000000-0000-0000-0000-000000000001' and a.level='AGEM'
  and a.id <> '9e000000-0000-0000-0000-000000000012'
on conflict do nothing;

insert into geo.tenant_boundary_areas (boundary_version_id, geo_area_id)
select 'b0000000-0000-0000-0000-000000000001', a.id
from geo.geo_areas a
where a.edition_id='ed000000-0000-0000-0000-000000000001' and a.level='AGEM'
  and a.id <> '9e000000-0000-0000-0000-000000000012'
on conflict do nothing;
