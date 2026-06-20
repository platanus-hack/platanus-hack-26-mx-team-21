do $$
declare v_user uuid; v_tenant uuid;
begin
  assert to_regprocedure('public.app_authorize_object(text,text)') is not null,
    'app_authorize_object missing';

  -- resolve the seeded dev user + tenant
  select s.user_id, m.tenant_id into v_user, v_tenant
  from platform.tenant_memberships m
  join platform.oidc_subjects s on s.id = m.subject_id
  limit 1;
  assert v_user is not null and v_tenant is not null, 'seed membership missing';

  -- simulate the caller's JWT (auth.uid() reads this GUC)
  perform set_config('request.jwt.claims', json_build_object('sub', v_user)::text, true);

  -- tenant-tiles: member of the path's tenant -> allowed
  assert public.app_authorize_object('tenant-tiles', v_tenant::text || '/bv/1/0-0.pbf') = true,
    'member should be allowed on own tenant tiles';
  -- tenant-tiles: a random tenant -> denied
  assert public.app_authorize_object('tenant-tiles', gen_random_uuid()::text || '/bv/1/0-0.pbf') = false,
    'non-member tenant must be denied';
  -- external-data is never client-facing
  assert public.app_authorize_object('external-data', 'raw/x/y.csv') = false,
    'external-data must be denied';
  -- malformed paths -> denied, never error
  assert public.app_authorize_object('sweep-video', 'sweeps/x/not-a-uuid.mp4') = false,
    'malformed sweep path must be denied';
  assert public.app_authorize_object('tenant-tiles', '') = false, 'empty path must be denied';
end $$;
