-- Broker authorization hardening for R2-served objects.
--
-- Fixes two authorization findings against the 0210 access API:
--
--   H5  tenant-tiles authorized by membership only, not object ownership.
--       The 0210 tenant-tiles branch returned is_member(<first-path-segment>, 'viewer')
--       without verifying the requested key is an actual current tile object for that
--       tenant. A viewer of tenant A could fetch ANY key under the "A/..." prefix
--       (retired/draft editions, arbitrary objects), unlike the observation-thumbnails
--       and sweep-video branches which require an existence match in
--       vision.observation_thumbnails / vision.recordings. Fix: additionally require an
--       existence match against platform.tenant_tile_sets (tenant_id = first-segment uuid,
--       storage_bucket = 'tenant-tiles', p_path under storage_prefix, status = 'ready').
--
--   Low active-tenant check. platform.is_member did not require the tenant to be active,
--        so members of a disabled tenant still authorized objects.
--
-- Both functions are re-creatable via CREATE OR REPLACE, so this migration is idempotent.

-- ---------------------------------------------------------------------------
-- Low: active-tenant check, fixed at the source in platform.is_member.
--
-- Rationale for fixing is_member rather than each app_authorize_object branch:
-- every current caller of is_member wants disabled tenants to be denied, and none
-- would break by adding the active-status requirement. Callers (grep 'is_member('):
--   * platform.can_view_observation (0011) -- read-model authorization
--   * tvo_read / obs_read / runs_read / runs_write RLS policies (0012)
--   * storage.objects tenant_tiles_read policy (0013, now superseded by the broker)
--   * public.app_authorize_object tenant-tiles branch (0210 / this migration)
-- Centralizing the check here closes the gap for all of them at once. The signature,
-- security-definer flag and empty search_path are preserved verbatim from 0002.
create or replace function platform.is_member(p_tenant uuid, p_min_role text default 'viewer')
returns boolean language sql stable security definer set search_path = '' as $$
    select exists (
        select 1
        from platform.tenant_memberships m
        join platform.oidc_subjects s on s.id = m.subject_id
        join platform.tenants t on t.id = m.tenant_id
        where s.user_id = auth.uid()
          and m.tenant_id = p_tenant
          and t.status = 'active'
          and (p_min_role = 'viewer' or m.role = 'analysis_author')
    );
$$;

-- ---------------------------------------------------------------------------
-- H5: tenant-tiles branch now requires both membership AND an existence/ownership
-- match against platform.tenant_tile_sets. Every other branch is preserved exactly
-- as authored in 0210 (observation-thumbnails existence + can_view_observation,
-- sweep-video existence + in-boundary member observation, external-data/unknown deny),
-- as is the GUC bridge, the security-definer flag, the empty search_path and the
-- exact signature public.app_authorize_object(p_bucket text, p_path text) returns boolean.
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
    v_id := v_part::uuid;
    -- Membership AND ownership: the path must resolve to a real, ready tile set for
    -- this tenant. Prefix match (p_path LIKE storage_prefix || '%') prevents a member
    -- of tenant A from reading retired/draft/arbitrary keys under the "A/..." prefix.
    if not exists (
      select 1 from platform.tenant_tile_sets ts
      where ts.tenant_id = v_id
        and ts.storage_bucket = 'tenant-tiles'
        and ts.status = 'ready'
        and p_path like ts.storage_prefix || '%'
    ) then
      return false;
    end if;
    return platform.is_member(v_id, 'viewer');

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

-- Re-grant execute to the same roles 0210 granted (public revoked, authenticated allowed).
revoke all on function public.app_authorize_object(text, text) from public;
grant execute on function public.app_authorize_object(text, text) to authenticated;
