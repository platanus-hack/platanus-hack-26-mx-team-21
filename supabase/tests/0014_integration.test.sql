do $$
declare v_tenant uuid; v_count int;
begin
  -- seed produced an active model and an active boundary
  assert exists (select 1 from priority.priority_models where status='active'), 'no active priority model';
  select id into v_tenant from platform.tenants where name='Dev Tenant';
  assert v_tenant is not null, 'dev tenant missing';
  assert exists (select 1 from geo.tenant_boundary_versions where tenant_id=v_tenant and status='active'),
    'dev tenant has no active boundary';

  -- full pipeline smoke: bump version, rebuild cache, no error
  perform vision.bump_data_version();
  select platform.rebuild_tenant_visible(v_tenant) into v_count;  -- 0 obs seeded is fine
  assert v_count >= 0, 'rebuild failed';
end $$;
