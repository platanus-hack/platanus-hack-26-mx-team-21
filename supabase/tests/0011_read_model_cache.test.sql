do $$
declare
  v_tenant uuid; v_edition uuid; v_bv uuid; v_src uuid; v_type uuid; v_sweep uuid;
  v_in uuid; v_out uuid; v_count int;
begin
  assert to_regclass('vision.read_model_state') is not null, 'read_model_state missing';
  assert to_regclass('platform.tenant_visible_observations') is not null, 'tenant_visible_observations missing';
  assert to_regclass('platform.tenant_tile_sets') is not null, 'tenant_tile_sets missing';
  assert to_regprocedure('platform.rebuild_tenant_visible(uuid)') is not null, 'rebuild fn missing';
  assert to_regprocedure('platform.can_view_observation(uuid)') is not null, 'can_view fn missing';

  -- Seed a tiny scenario: a 0..10 / 0..10 boundary; one point inside, one outside.
  insert into platform.tenants(name) values ('t') returning id into v_tenant;
  insert into geo.geo_editions(source_name,source_release,status)
    values ('test','r1','active') returning id into v_edition;
  insert into geo.tenant_boundary_versions(tenant_id,edition_id,version_number,status,materialized_geometry)
    values (v_tenant, v_edition, 1, 'active',
            ST_Multi(ST_GeomFromText('POLYGON((0 0,0 10,10 10,10 0,0 0))',4326)))
    returning id into v_bv;
  insert into vision.sources(slug,name) values ('s','s') returning id into v_src;
  insert into vision.observation_types(slug,label,category) values ('pothole','P','road')
    returning id into v_type;
  insert into vision.sweeps(source_id,coverage,started_at,ended_at)
    values (v_src, ST_GeogFromText('POLYGON((0 0,0 10,10 10,10 0,0 0))'), now(), now())
    returning id into v_sweep;
  insert into vision.observations(observation_type_id,location,observed_at,sweep_id,
        detector_name,detector_version,detected_at,valid_from)
    values (v_type, ST_GeogFromText('POINT(5 5)'), now(), v_sweep, 'd','1', now(), now())
    returning id into v_in;
  insert into vision.observations(observation_type_id,location,observed_at,sweep_id,
        detector_name,detector_version,detected_at,valid_from)
    values (v_type, ST_GeogFromText('POINT(20 20)'), now(), v_sweep, 'd','1', now(), now())
    returning id into v_out;

  perform platform.rebuild_tenant_visible(v_tenant);

  select count(*) into v_count from platform.tenant_visible_observations
    where tenant_id = v_tenant;
  assert v_count = 1, 'cache should contain exactly the inside observation';
  assert exists (select 1 from platform.tenant_visible_observations
    where tenant_id = v_tenant and observation_id = v_in), 'inside obs should be cached';
  assert not exists (select 1 from platform.tenant_visible_observations
    where tenant_id = v_tenant and observation_id = v_out), 'outside obs must not be cached';
end $$;
