set search_path = public, extensions;

select vision.bump_data_version();
select platform.rebuild_tenant_visible('a0000000-0000-0000-0000-000000000001');

insert into platform.audit_events (id, tenant_id, actor_subject_id, module, action, target_type, target_id, occurred_at, details) values
  ('aed10000-0000-0000-0000-000000000001','a0000000-0000-0000-0000-000000000001','05000000-0000-0000-0000-00000000000a','geo','tenant_boundary_activated','tenant_boundary_version','b0000000-0000-0000-0000-000000000001','2026-06-01 00:00:00+00','{}'),
  ('aed10000-0000-0000-0000-000000000002','a0000000-0000-0000-0000-000000000001','05000000-0000-0000-0000-00000000000a','analysis','analysis_submitted','analysis_run','1a000000-0000-0000-0000-000000000001','2026-06-15 09:00:00+00','{"kind":"budget.route"}')
on conflict do nothing;
