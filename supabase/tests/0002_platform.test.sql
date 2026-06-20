do $$
begin
  assert to_regclass('platform.tenants') is not null, 'platform.tenants missing';
  assert to_regclass('platform.oidc_subjects') is not null, 'platform.oidc_subjects missing';
  assert to_regclass('platform.tenant_memberships') is not null, 'platform.tenant_memberships missing';
  assert to_regclass('platform.audit_events') is not null, 'platform.audit_events missing';
  -- unique (issuer, subject)
  assert exists (select 1 from pg_constraint
    where conrelid = 'platform.oidc_subjects'::regclass and contype = 'u'
      and conkey @> array[
        (select attnum from pg_attribute where attrelid='platform.oidc_subjects'::regclass and attname='issuer'),
        (select attnum from pg_attribute where attrelid='platform.oidc_subjects'::regclass and attname='subject')
      ]::smallint[]), 'unique(issuer,subject) missing';
  -- helper functions exist
  assert to_regprocedure('platform.is_member(uuid,text)') is not null, 'is_member missing';
  assert to_regprocedure('platform.active_tenant_id()') is not null, 'active_tenant_id missing';
  assert to_regprocedure('platform.current_subject_id()') is not null, 'current_subject_id missing';
end $$;
