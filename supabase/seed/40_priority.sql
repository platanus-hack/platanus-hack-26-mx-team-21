set search_path = public, extensions;

insert into priority.priority_models (id, name, version, status) values
  ('b1000000-0000-0000-0000-000000000001','baseline','v1','active')
on conflict do nothing;

insert into priority.priority_batches (id, model_id, trigger_sweep_id, reason, status, created_at, started_at, completed_at) values
  ('ba000000-0000-0000-0000-000000000001','b1000000-0000-0000-0000-000000000001','5e000000-0000-0000-0000-000000000002','new_sweep','completed','2026-06-14 13:30:00+00','2026-06-14 13:31:00+00','2026-06-14 13:40:00+00')
on conflict do nothing;

-- Computed values for current, non-pending observations (deterministic weight 1..99).
insert into priority.priority_values (id, observation_id, model_id, weight, value_state, computed_by_batch_id, created_at)
select
  ('00f10000-0000-4000-8000-'||substr(replace(o.id::text,'-',''),21,12))::uuid,
  o.id, 'b1000000-0000-0000-0000-000000000001',
  1 + (get_byte(decode(md5(o.id::text),'hex'),1) % 99),
  'computed','ba000000-0000-0000-0000-000000000001','2026-06-14 13:40:00+00'
from vision.observations o
where o.superseded_by_observation_id is null and o.resolved_at is null
  and (get_byte(decode(md5(o.id::text),'hex'),0) % 9) <> 0
  and o.id not in ('00b50000-0000-4000-8000-000000009101','00b50000-0000-4000-8000-000000009102',
                   '00b50000-0000-4000-8000-000000009103','00b50000-0000-4000-8000-000000009104')
on conflict do nothing;

-- Predecessor computed values (so successors have something to inherit) — predecessors are not current.
insert into priority.priority_values (id, observation_id, model_id, weight, value_state, computed_by_batch_id, created_at) values
  ('00f10000-0000-4000-8000-000000009001','00b50000-0000-4000-8000-000000009001','b1000000-0000-0000-0000-000000000001',82,'computed','ba000000-0000-0000-0000-000000000001','2026-06-08 09:30:00+00'),
  ('00f10000-0000-4000-8000-000000009002','00b50000-0000-4000-8000-000000009002','b1000000-0000-0000-0000-000000000001',64,'computed','ba000000-0000-0000-0000-000000000001','2026-06-08 09:30:00+00'),
  ('00f10000-0000-4000-8000-000000009003','00b50000-0000-4000-8000-000000009003','b1000000-0000-0000-0000-000000000001',77,'computed','ba000000-0000-0000-0000-000000000001','2026-06-08 09:30:00+00'),
  ('00f10000-0000-4000-8000-000000009004','00b50000-0000-4000-8000-000000009004','b1000000-0000-0000-0000-000000000001',55,'computed','ba000000-0000-0000-0000-000000000001','2026-06-08 09:30:00+00')
on conflict do nothing;

-- Inherited values for the 4 successors (point at predecessor's value, same weight).
insert into priority.priority_values (id, observation_id, model_id, weight, value_state, inherited_from_value_id, created_at) values
  ('00f10000-0000-4000-8000-00000000a101','00b50000-0000-4000-8000-000000009101','b1000000-0000-0000-0000-000000000001',82,'inherited','00f10000-0000-4000-8000-000000009001','2026-06-14 10:00:00+00'),
  ('00f10000-0000-4000-8000-00000000a102','00b50000-0000-4000-8000-000000009102','b1000000-0000-0000-0000-000000000001',64,'inherited','00f10000-0000-4000-8000-000000009002','2026-06-14 10:05:00+00'),
  ('00f10000-0000-4000-8000-00000000a103','00b50000-0000-4000-8000-000000009103','b1000000-0000-0000-0000-000000000001',77,'inherited','00f10000-0000-4000-8000-000000009003','2026-06-14 10:10:00+00'),
  ('00f10000-0000-4000-8000-00000000a104','00b50000-0000-4000-8000-000000009104','b1000000-0000-0000-0000-000000000001',55,'inherited','00f10000-0000-4000-8000-000000009004','2026-06-14 10:15:00+00')
on conflict do nothing;

-- Current pointers: predecessors/resolved/pending excluded.
insert into priority.current_priority_values (observation_id, model_id, priority_value_id, updated_at)
select pv.observation_id, pv.model_id, pv.id, '2026-06-14 13:40:00+00'
from priority.priority_values pv
join vision.observations o on o.id = pv.observation_id
where o.superseded_by_observation_id is null and o.resolved_at is null
on conflict do nothing;
