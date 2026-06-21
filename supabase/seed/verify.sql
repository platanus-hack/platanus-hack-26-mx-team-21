-- Seed verification — DoD #3 gate. Run AFTER the seed is applied:
--   psql "$DBURL" -v ON_ERROR_STOP=1 -f supabase/seed/verify.sql
--   (or via Supabase MCP execute_sql against the remote project)
-- Any failed assertion raises and aborts with a non-zero exit / error.
--
-- NOTE on the access checks: the browser/app NEVER touches the custom schemas directly
-- (the `authenticated` role has no USAGE on `vision`/`priority`/`geo`/`analysis` by design —
-- it reaches data only through the `public` security-definer API layer, migrations 0200/0201).
-- So we verify the access path the API actually uses: the SECURITY DEFINER helpers
-- `platform.current_subject_id()` / `platform.is_member()` + the `tenant_visible_observations`
-- cache, NOT a direct `set role authenticated; select from vision.observations` (which is
-- correctly permission-denied). Extend this file to call app_* once 0200/0201 land.
set search_path = public, extensions;

-- ---- Contract coverage (runs as the seeding role) ----
do $$
declare n int; scored int; pending int;
begin
  select count(*) into n from vision.observation_types;
  assert n = 5, format('expected 5 observation_types, got %s', n);
  assert exists (select 1 from vision.observation_types where slug='missing_signage' and auto_resolvable=false),
    'missing_signage must be latent (auto_resolvable=false)';

  select count(*) into n from vision.observations;
  assert n >= 120, format('expected >=120 observations, got %s', n);
  assert (select count(*) from vision.observations where superseded_by_observation_id is not null) >= 1, 'need >=1 superseded';
  assert (select count(*) from vision.observations where resolved_at is not null) >= 1, 'need >=1 resolved';

  select count(*) into scored from vision.observations o
    join priority.current_priority_values v on v.observation_id=o.id
    where o.superseded_by_observation_id is null and o.resolved_at is null;
  select count(*) into pending from vision.observations o
    where o.superseded_by_observation_id is null and o.resolved_at is null
      and not exists (select 1 from priority.current_priority_values v where v.observation_id=o.id);
  assert scored >= 90, format('expected >=90 scored, got %s', scored);
  assert pending >= 1, format('expected >=1 pending, got %s', pending);
  assert (select count(*) from priority.priority_models where status='active') = 1, 'exactly one active priority model';

  assert (select count(*) from geo.geo_editions where status='active') = 1, 'one active edition';
  assert (select count(*) from geo.tenant_boundary_versions where tenant_id='a0000000-0000-0000-0000-000000000001' and status='active') = 1, 'one active boundary';
  assert (select count(*) from vision.observations o where not exists (select 1 from geo.observation_geo_bindings b where b.observation_id=o.id)) = 0,
    'all observations must be geo-bound';

  assert (select count(*) from analysis.analysis_definition_versions where status='active') = 3, 'three active definition versions';
  assert exists (
    select 1 from analysis.analysis_runs r
    join analysis.analysis_results res on res.run_id=r.id
    join analysis.artifacts a on a.result_id=res.id
    join analysis.map_features mf on mf.artifact_id=a.id
    where r.status='succeeded' and ST_GeometryType(mf.geometry)='ST_LineString'),
    'need a succeeded route with a LineString artifact';

  assert (select count(*) from priority.current_rois) >= 1, 'need >=1 current ROI';

  raise notice 'CONTRACT OK: % observations, % scored, % pending', (select count(*) from vision.observations), scored, pending;
end $$;

-- ---- Access path (the SECURITY DEFINER helpers the public API uses) ----
do $$
declare
  a_subj uuid; a_view bool; a_auth bool; app_visible int; tlalpan_visible int;
  v_view bool; v_auth bool; n_subj uuid; n_view bool;
begin
  -- author.a (member): subject, roles, and the member's visible set (= tenant_visible cache ∩ membership)
  perform set_config('request.jwt.claims', json_build_object('sub','c0000000-0000-0000-0000-00000000000a')::text, true);
  a_subj := platform.current_subject_id();
  a_view := platform.is_member('a0000000-0000-0000-0000-000000000001','viewer');
  a_auth := platform.is_member('a0000000-0000-0000-0000-000000000001','analysis_author');
  select count(*) into app_visible
    from platform.tenant_visible_observations v
    where v.tenant_id='a0000000-0000-0000-0000-000000000001'
      and platform.is_member('a0000000-0000-0000-0000-000000000001','viewer');
  -- the visible cache must exclude out-of-boundary (Tlalpan) observations
  select count(*) into tlalpan_visible
    from platform.tenant_visible_observations v
    join vision.observations o on o.id = v.observation_id
    join geo.geo_areas a on a.id='9e000000-0000-0000-0000-000000000012' and ST_Contains(a.geometry, o.location::geometry)
    where v.tenant_id='a0000000-0000-0000-0000-000000000001';

  -- viewer.a (member, viewer only)
  perform set_config('request.jwt.claims', json_build_object('sub','c0000000-0000-0000-0000-00000000000b')::text, true);
  v_view := platform.is_member('a0000000-0000-0000-0000-000000000001','viewer');
  v_auth := platform.is_member('a0000000-0000-0000-0000-000000000001','analysis_author');

  -- nomember (no membership)
  perform set_config('request.jwt.claims', json_build_object('sub','c0000000-0000-0000-0000-00000000000c')::text, true);
  n_subj := platform.current_subject_id();
  n_view := platform.is_member('a0000000-0000-0000-0000-000000000001','viewer');

  assert a_subj = '05000000-0000-0000-0000-00000000000a', 'author.a subject mismatch';
  assert a_view and a_auth, 'author.a should be viewer+author';
  assert v_view and not v_auth, 'viewer.a should be viewer only';
  assert n_subj = '05000000-0000-0000-0000-00000000000c', 'nomember subject should resolve';
  assert not n_view, 'nomember must NOT be a member';
  assert app_visible >= 90, format('member visible set should be ~114, got %s', app_visible);
  assert tlalpan_visible = 0, format('out-of-boundary (Tlalpan) observations must be hidden, saw %s', tlalpan_visible);

  raise notice 'ACCESS OK: author(view=% auth=%) viewer(view=% auth=%) nomember(view=%) visible=% tlalpan=%',
    a_view, a_auth, v_view, v_auth, n_view, app_visible, tlalpan_visible;
end $$;
