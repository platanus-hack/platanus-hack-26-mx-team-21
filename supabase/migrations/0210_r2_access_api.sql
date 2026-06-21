-- Postgres-mediated authorization for R2-served objects. The broker Worker forwards
-- the user's JWT to this RPC; it reuses platform.can_view_observation / is_member.
-- Boolean only — no bytes. external-data is server-side and always denied here.
create or replace function public.app_authorize_object(p_bucket text, p_path text)
returns boolean
language plpgsql
volatile  -- sets the app.tenant_id GUC (transaction-local) before delegating
security definer
set search_path = ''
as $$
declare
  v_part text;
  v_id   uuid;
  uuid_re constant text := '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';
begin
  if coalesce(p_path, '') = '' then
    return false;
  end if;

  -- PostgREST sets request.jwt.claims (so auth.uid() works) but NOT the app.tenant_id
  -- GUC that platform.active_tenant_id()/can_view_observation depend on. Bridge it from
  -- the caller's membership (analysis_author preferred, else viewer), transaction-local,
  -- so the observation-thumbnails/sweep-video branches authorize legitimate members.
  perform set_config('app.tenant_id', coalesce((
    select m.tenant_id::text
    from platform.tenant_memberships m
    join platform.oidc_subjects s on s.id = m.subject_id
    where s.user_id = auth.uid()
    order by case when m.role = 'analysis_author' then 0 else 1 end
    limit 1
  ), ''), true);

  if p_bucket = 'tenant-tiles' then
    -- {tenant_id}/{boundary_version_id}/{data_version}/...
    v_part := split_part(p_path, '/', 1);
    if v_part !~* uuid_re then return false; end if;
    return platform.is_member(v_part::uuid, 'viewer');

  elsif p_bucket = 'observation-thumbnails' then
    -- observations/{observation_id}/...
    if split_part(p_path, '/', 1) <> 'observations' then return false; end if;
    v_part := split_part(p_path, '/', 2);
    if v_part !~* uuid_re then return false; end if;
    v_id := v_part::uuid;
    if not exists (
      select 1 from vision.observation_thumbnails t
      where t.observation_id = v_id
        and t.storage_bucket = 'observation-thumbnails'
        and t.storage_path = p_path
    ) then
      return false;
    end if;
    return platform.can_view_observation(v_id);

  elsif p_bucket = 'sweep-video' then
    -- sweeps/{sweep_id}/{recording_id}.mp4
    if split_part(p_path, '/', 1) <> 'sweeps' then return false; end if;
    v_part := split_part(split_part(p_path, '/', 3), '.', 1);  -- strip extension
    if v_part !~* uuid_re then return false; end if;
    v_id := v_part::uuid;
    if not exists (
      select 1 from vision.recordings r
      where r.id = v_id
        and r.storage_bucket = 'sweep-video'
        and r.storage_path = p_path
    ) then
      return false;
    end if;
    -- parity with the documented signed-URL flow: viewable iff some in-boundary,
    -- tenant-member observation references this recording.
    return exists (
      select 1 from vision.observations o
      where o.recording_id = v_id
        and platform.can_view_observation(o.id)
    );

  else
    return false;  -- external-data and anything unrecognized
  end if;
end;
$$;

revoke all on function public.app_authorize_object(text, text) from public;
grant execute on function public.app_authorize_object(text, text) to authenticated;
