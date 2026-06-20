set search_path = public, extensions;

-- Sources
insert into vision.sources (id, slug, name, status) values
  ('50000000-0000-0000-0000-000000000001','truck_fleet','Trash-truck fleet cam','active'),
  ('50000000-0000-0000-0000-000000000002','adhoc_survey','Ad-hoc survey','active')
on conflict do nothing;

-- Observation types (auto_resolvable=false on missing_signage => app is_latent)
insert into vision.observation_types
  (id, slug, label, category, description, merge_radius_m, auto_resolvable, auto_resolve_miss_threshold, status) values
  ('70000000-0000-0000-0000-000000000001','pothole','Bache','road_surface','Bache en superficie de rodamiento',10,true,4,'active'),
  ('70000000-0000-0000-0000-000000000002','open_drain','Coladera abierta','drainage','Coladera o registro sin tapa',12,true,4,'active'),
  ('70000000-0000-0000-0000-000000000003','broken_light','Luminaria dañada','lighting','Luminaria pública apagada o rota',15,true,5,'active'),
  ('70000000-0000-0000-0000-000000000004','missing_signage','Señalización faltante','signage','Señal de tránsito ausente (latente)',20,false,null,'active'),
  ('70000000-0000-0000-0000-000000000005','damaged_sidewalk','Banqueta dañada','pedestrian','Banqueta fracturada o levantada',10,true,4,'active')
on conflict do nothing;

-- Quantity attribute definitions (one per type) + a shared optional confidence per type
insert into vision.observation_attribute_definitions
  (id, observation_type_id, key, version, label, value_kind, unit, required, minimum_number, maximum_number, status) values
  ('7d000000-0000-0000-0000-000000000001','70000000-0000-0000-0000-000000000001','surface_area_m2',1,'Área (m²)','number','m2',true,0,500,'active'),
  ('7d000000-0000-0000-0000-000000000002','70000000-0000-0000-0000-000000000002','count',1,'Cantidad','number','item',true,0,50,'active'),
  ('7d000000-0000-0000-0000-000000000003','70000000-0000-0000-0000-000000000003','count',1,'Cantidad','number','item',true,0,50,'active'),
  ('7d000000-0000-0000-0000-000000000004','70000000-0000-0000-0000-000000000004','count',1,'Cantidad','number','item',true,0,50,'active'),
  ('7d000000-0000-0000-0000-000000000005','70000000-0000-0000-0000-000000000005','length_m',1,'Longitud (m)','number','m',true,0,300,'active'),
  -- confidence (optional) per type
  ('7dc00000-0000-0000-0000-000000000001','70000000-0000-0000-0000-000000000001','confidence',1,'Confianza','number',null,false,0,1,'active'),
  ('7dc00000-0000-0000-0000-000000000002','70000000-0000-0000-0000-000000000002','confidence',1,'Confianza','number',null,false,0,1,'active'),
  ('7dc00000-0000-0000-0000-000000000003','70000000-0000-0000-0000-000000000003','confidence',1,'Confianza','number',null,false,0,1,'active'),
  ('7dc00000-0000-0000-0000-000000000004','70000000-0000-0000-0000-000000000004','confidence',1,'Confianza','number',null,false,0,1,'active'),
  ('7dc00000-0000-0000-0000-000000000005','70000000-0000-0000-0000-000000000005','confidence',1,'Confianza','number',null,false,0,1,'active')
on conflict do nothing;

-- Sweeps (coverage over CDMX bbox) + recordings + assessed types
insert into vision.sweeps (id, source_id, coverage, started_at, ended_at) values
  ('5e000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001',
     ST_MakeEnvelope(-99.30,19.25,-98.95,19.55,4326)::geography,
     '2026-06-10 08:00:00+00','2026-06-10 14:00:00+00'),
  ('5e000000-0000-0000-0000-000000000002','50000000-0000-0000-0000-000000000002',
     ST_MakeEnvelope(-99.30,19.25,-98.95,19.55,4326)::geography,
     '2026-06-14 08:00:00+00','2026-06-14 13:00:00+00')
on conflict do nothing;

insert into vision.recordings (id, sweep_id, storage_path, status, started_at, ended_at, duration_ms) values
  ('5ec00000-0000-0000-0000-000000000001','5e000000-0000-0000-0000-000000000001','sweeps/5e000000-0000-0000-0000-000000000001/5ec00000-0000-0000-0000-000000000001.mp4','ready','2026-06-10 08:00:00+00','2026-06-10 11:00:00+00',10800000),
  ('5ec00000-0000-0000-0000-000000000002','5e000000-0000-0000-0000-000000000002','sweeps/5e000000-0000-0000-0000-000000000002/5ec00000-0000-0000-0000-000000000002.mp4','ready','2026-06-14 08:00:00+00','2026-06-14 11:00:00+00',10800000)
on conflict do nothing;

insert into vision.sweep_assessed_types (sweep_id, observation_type_id)
select s.id, t.id from vision.sweeps s cross join vision.observation_types t
on conflict do nothing;
