set search_path = public, extensions;

insert into analysis.analysis_providers (id, slug, name, status, config_ref) values
  ('f0000000-0000-0000-0000-000000000001','in_db_executor','In-DB executor (seed stand-in)','enabled','seed')
on conflict do nothing;

insert into analysis.analysis_definitions (id, kind, label) values
  ('de000000-0000-0000-0000-000000000001','budget.route','Ruta óptima de servicio'),
  ('de000000-0000-0000-0000-000000000002','budget.cluster','Clúster de mayor impacto'),
  ('de000000-0000-0000-0000-000000000003','inspection.latent','Escaneo de inspección (latente)')
on conflict do nothing;

insert into analysis.analysis_definition_versions
  (id, definition_id, provider_id, interface_version, request_schema, result_schema, artifact_kinds, ui_descriptor, status) values
  ('d1000000-0000-0000-0000-000000000001','de000000-0000-0000-0000-000000000001','f0000000-0000-0000-0000-000000000001','v1',
     '{"type":"object"}','{"type":"object"}','["map_features","ordered_sequence"]',
     '{"currency":"MXN","cost_basis":[{"slug":"pothole","unit":"m2","default_unit_cost":28000},{"slug":"open_drain","unit":"item","default_unit_cost":9000},{"slug":"broken_light","unit":"item","default_unit_cost":12000},{"slug":"missing_signage","unit":"item","default_unit_cost":4000},{"slug":"damaged_sidewalk","unit":"m","default_unit_cost":3500}]}','active'),
  ('d1000000-0000-0000-0000-000000000002','de000000-0000-0000-0000-000000000002','f0000000-0000-0000-0000-000000000001','v1',
     '{"type":"object"}','{"type":"object"}','["map_features"]','{"currency":"MXN"}','active'),
  ('d1000000-0000-0000-0000-000000000003','de000000-0000-0000-0000-000000000003','f0000000-0000-0000-0000-000000000001','v1',
     '{"type":"object"}','{"type":"object"}','["map_features"]','{"currency":"MXN"}','active')
on conflict do nothing;

insert into analysis.provider_capability_snapshots (id, definition_version_id, descriptor, config_version) values
  ('5a000000-0000-0000-0000-000000000001','d1000000-0000-0000-0000-000000000001','{"types":["pothole","open_drain","broken_light","missing_signage","damaged_sidewalk"],"currency":"MXN"}','cfg-v1'),
  ('5a000000-0000-0000-0000-000000000002','d1000000-0000-0000-0000-000000000002','{"types":["pothole","open_drain","broken_light","missing_signage","damaged_sidewalk"],"currency":"MXN"}','cfg-v1')
on conflict do nothing;

-- ---- Runs ----
insert into analysis.analysis_runs
  (id, idempotency_key, tenant_id, requested_by_subject_id, definition_version_id, capability_snapshot_id,
   boundary_version_id, edition_id, budget_amount, budget_currency, status, created_at, started_at, finished_at) values
  ('1a000000-0000-0000-0000-000000000001','seed-route-1','a0000000-0000-0000-0000-000000000001','05000000-0000-0000-0000-00000000000a','d1000000-0000-0000-0000-000000000001','5a000000-0000-0000-0000-000000000001','b0000000-0000-0000-0000-000000000001','ed000000-0000-0000-0000-000000000001',3000000.00,'MXN','succeeded','2026-06-15 09:00:00+00','2026-06-15 09:00:05+00','2026-06-15 09:00:20+00'),
  ('1a000000-0000-0000-0000-000000000002','seed-cluster-1','a0000000-0000-0000-0000-000000000001','05000000-0000-0000-0000-00000000000a','d1000000-0000-0000-0000-000000000002','5a000000-0000-0000-0000-000000000002','b0000000-0000-0000-0000-000000000001','ed000000-0000-0000-0000-000000000001',5000000.00,'MXN','succeeded','2026-06-15 09:10:00+00','2026-06-15 09:10:05+00','2026-06-15 09:10:18+00'),
  ('1a000000-0000-0000-0000-000000000003','seed-route-fail','a0000000-0000-0000-0000-000000000001','05000000-0000-0000-0000-00000000000a','d1000000-0000-0000-0000-000000000001','5a000000-0000-0000-0000-000000000001','b0000000-0000-0000-0000-000000000001','ed000000-0000-0000-0000-000000000001',1000000.00,'MXN','failed','2026-06-15 09:20:00+00','2026-06-15 09:20:05+00','2026-06-15 09:20:09+00'),
  ('1a000000-0000-0000-0000-000000000004','seed-route-queued','a0000000-0000-0000-0000-000000000001','05000000-0000-0000-0000-00000000000a','d1000000-0000-0000-0000-000000000001','5a000000-0000-0000-0000-000000000001','b0000000-0000-0000-0000-000000000001','ed000000-0000-0000-0000-000000000001',2000000.00,'MXN','queued','2026-06-15 09:30:00+00',null,null)
on conflict do nothing;

-- Frozen inputs for the succeeded route + cluster: 12 top-weight current scored observations, for BOTH runs.
with picked as (
  select o.id as obs_id, o.observation_type_id, o.location, o.observed_at, o.recording_id, o.frame_ref, v.weight,
         row_number() over (order by v.weight desc, o.id) as rn
  from vision.observations o
  join priority.current_priority_values cpv on cpv.observation_id=o.id
  join priority.priority_values v on v.id=cpv.priority_value_id
  where o.superseded_by_observation_id is null and o.resolved_at is null
  order by v.weight desc, o.id
  limit 12
)
insert into analysis.run_observations (run_id, observation_id, observation_type_id, location, observed_at, recording_id, frame_ref, lifecycle_version)
select r.run_id, p.obs_id, p.observation_type_id, p.location, p.observed_at, p.recording_id, p.frame_ref, 1
from picked p cross join (values ('1a000000-0000-0000-0000-000000000001'::uuid),('1a000000-0000-0000-0000-000000000002'::uuid)) r(run_id)
on conflict do nothing;

insert into analysis.run_priority_values (run_id, observation_id, weight, model_name, model_version, value_state)
select ro.run_id, ro.observation_id, v.weight, 'baseline','v1', v.value_state
from analysis.run_observations ro
join priority.current_priority_values cpv on cpv.observation_id=ro.observation_id
join priority.priority_values v on v.id=cpv.priority_value_id
where ro.run_id in ('1a000000-0000-0000-0000-000000000001','1a000000-0000-0000-0000-000000000002')
on conflict do nothing;

insert into analysis.run_observation_attributes (run_id, observation_id, definition_key, value_kind, number_value, unit)
select ro.run_id, ro.observation_id, d.key, 'number', av.number_value, d.unit
from analysis.run_observations ro
join vision.observation_attribute_values av on av.observation_id=ro.observation_id
join vision.observation_attribute_definitions d on d.id=av.definition_id and d.key in ('surface_area_m2','length_m','count')
where ro.run_id in ('1a000000-0000-0000-0000-000000000001','1a000000-0000-0000-0000-000000000002')
on conflict do nothing;

insert into analysis.run_observation_exclusions (run_id, observation_id, reason)
select '1a000000-0000-0000-0000-000000000001', o.id, 'unscored'
from vision.observations o
where o.superseded_by_observation_id is null and o.resolved_at is null
  and not exists (select 1 from priority.current_priority_values v where v.observation_id=o.id)
limit 10
on conflict do nothing;

insert into analysis.analysis_attempts (id, run_id, attempt_number, provider_request_id, status, started_at, finished_at, failure_code, failure_details) values
  ('a77e0000-0000-0000-0000-000000000001','1a000000-0000-0000-0000-000000000001',1,'req-route-1','succeeded','2026-06-15 09:00:05+00','2026-06-15 09:00:20+00',null,'{}'),
  ('a77e0000-0000-0000-0000-000000000002','1a000000-0000-0000-0000-000000000002',1,'req-cluster-1','succeeded','2026-06-15 09:10:05+00','2026-06-15 09:10:18+00',null,'{}'),
  ('a77e0000-0000-0000-0000-000000000003','1a000000-0000-0000-0000-000000000003',1,'req-route-fail','failed','2026-06-15 09:20:05+00','2026-06-15 09:20:09+00','budget_too_low','{"message":"no eligible observations under budget"}')
on conflict do nothing;

insert into analysis.analysis_results (id, run_id, accepted_attempt_id, provider_version, config_version, result_schema_version, payload) values
  ('5e5a0000-0000-0000-0000-000000000001','1a000000-0000-0000-0000-000000000001','a77e0000-0000-0000-0000-000000000001','v1','cfg-v1','1',
    jsonb_build_object('run_id','1a000000-0000-0000-0000-000000000001','kind','route','budget',3000000,
      'stats', jsonb_build_array(
        jsonb_build_object('key','spent','label','Gasto','value',2840000),
        jsonb_build_object('key','count','label','Atendidos','value',9),
        jsonb_build_object('key','riskRed','label','Riesgo reducido','value',62),
        jsonb_build_object('key','distKm','label','Distancia','value',7.4)),
      'items', '[]'::jsonb)),
  ('5e5a0000-0000-0000-0000-000000000002','1a000000-0000-0000-0000-000000000002','a77e0000-0000-0000-0000-000000000002','v1','cfg-v1','1',
    jsonb_build_object('run_id','1a000000-0000-0000-0000-000000000002','kind','cluster','budget',5000000,
      'stats', jsonb_build_array(
        jsonb_build_object('key','spent','label','Gasto','value',4720000),
        jsonb_build_object('key','count','label','Atendidos','value',12),
        jsonb_build_object('key','riskRed','label','Riesgo reducido','value',71)),
      'items','[]'::jsonb))
on conflict do nothing;

insert into analysis.result_metrics (id, result_id, key, label, unit, number_value) values
  ('5e3a0000-0000-0000-0000-000000000001','5e5a0000-0000-0000-0000-000000000001','spent','Gasto','MXN',2840000),
  ('5e3a0000-0000-0000-0000-000000000002','5e5a0000-0000-0000-0000-000000000001','count','Atendidos','item',9),
  ('5e3a0000-0000-0000-0000-000000000003','5e5a0000-0000-0000-0000-000000000001','distKm','Distancia','km',7.4),
  ('5e3a0000-0000-0000-0000-000000000004','5e5a0000-0000-0000-0000-000000000002','spent','Gasto','MXN',4720000),
  ('5e3a0000-0000-0000-0000-000000000005','5e5a0000-0000-0000-0000-000000000002','count','Atendidos','item',12)
on conflict do nothing;

insert into analysis.artifacts (id, result_id, kind, schema_version, display_order, title, payload) values
  ('a47a0000-0000-0000-0000-000000000001','5e5a0000-0000-0000-0000-000000000001','map_features',1,0,'Ruta','{}'),
  ('a47a0000-0000-0000-0000-000000000002','5e5a0000-0000-0000-0000-000000000001','ordered_sequence',1,1,'Paradas','{}'),
  ('a47a0000-0000-0000-0000-000000000003','5e5a0000-0000-0000-0000-000000000002','map_features',1,0,'Clúster','{}')
on conflict do nothing;

insert into analysis.map_features (id, artifact_id, geometry, feature_key, properties)
select 'a47f0000-0000-0000-0000-000000000001','a47a0000-0000-0000-0000-000000000001',
       ST_SetSRID(ST_MakeLine(g.geom order by g.weight desc), 4326),'route-line','{"kind":"route"}'
from (
  select ro.location::geometry as geom, v.weight
  from analysis.run_observations ro
  join analysis.run_priority_values v on v.run_id=ro.run_id and v.observation_id=ro.observation_id
  where ro.run_id='1a000000-0000-0000-0000-000000000001'
) g
on conflict do nothing;

insert into analysis.map_features (id, artifact_id, geometry, feature_key, properties)
select 'a47f0000-0000-0000-0000-000000000002','a47a0000-0000-0000-0000-000000000003',
       ST_SetSRID(ST_ConvexHull(ST_Collect(ro.location::geometry)),4326),'cluster-poly','{"kind":"cluster"}'
from analysis.run_observations ro
where ro.run_id='1a000000-0000-0000-0000-000000000002'
on conflict do nothing;

insert into analysis.sequence_items (id, artifact_id, position, run_id, observation_id, label)
select ('a4510000-0000-4000-8000-'||lpad(to_hex(row_number() over (order by v.weight desc)),12,'0'))::uuid,
       'a47a0000-0000-0000-0000-000000000002',
       row_number() over (order by v.weight desc),
       ro.run_id, ro.observation_id, 'Parada'
from analysis.run_observations ro
join analysis.run_priority_values v on v.run_id=ro.run_id and v.observation_id=ro.observation_id
where ro.run_id='1a000000-0000-0000-0000-000000000001'
on conflict do nothing;

insert into analysis.artifact_observation_refs (id, artifact_id, run_id, observation_id, role, display_order)
select ('a4520000-0000-4000-8000-'||lpad(to_hex(row_number() over (order by v.weight desc)),12,'0'))::uuid,
       'a47a0000-0000-0000-0000-000000000001', ro.run_id, ro.observation_id, 'stop',
       (row_number() over (order by v.weight desc))::int
from analysis.run_observations ro
join analysis.run_priority_values v on v.run_id=ro.run_id and v.observation_id=ro.observation_id
where ro.run_id='1a000000-0000-0000-0000-000000000001'
on conflict do nothing;

insert into analysis.artifact_observation_refs (id, artifact_id, run_id, observation_id, role, display_order)
select ('a4530000-0000-4000-8000-'||lpad(to_hex(row_number() over (order by ro.observation_id)),12,'0'))::uuid,
       'a47a0000-0000-0000-0000-000000000003', ro.run_id, ro.observation_id, 'member',
       (row_number() over (order by ro.observation_id))::int
from analysis.run_observations ro
where ro.run_id='1a000000-0000-0000-0000-000000000002'
on conflict do nothing;
