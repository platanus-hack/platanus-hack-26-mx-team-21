do $$
declare v_src uuid; v_type uuid; v_sweep uuid; v_rec1 uuid; v_rec2 uuid; v_obs uuid; v_threw boolean;
begin
  -- policies present
  assert exists (select 1 from pg_policies where schemaname='vision' and tablename='observations'),
    'observations RLS policy missing';
  assert (select relrowsecurity from pg_class where oid='vision.observations'::regclass),
    'RLS not enabled on observations';
  assert exists (select 1 from pg_trigger where tgrelid='vision.observations'::regclass
    and tgname='observations_immutable'), 'immutability trigger missing';

  -- immutability: changing a fact column must raise
  insert into vision.sources(slug,name) values ('s2','s2') returning id into v_src;
  insert into vision.observation_types(slug,label,category) values ('t2','T2','c') returning id into v_type;
  insert into vision.sweeps(source_id,coverage,started_at,ended_at)
    values (v_src, ST_GeogFromText('POLYGON((0 0,0 1,1 1,1 0,0 0))'), now(), now())
    returning id into v_sweep;
  insert into vision.recordings(sweep_id,storage_path,started_at,ended_at)
    values (v_sweep,'a.mp4', now(), now()) returning id into v_rec1;
  insert into vision.recordings(sweep_id,storage_path,started_at,ended_at)
    values (v_sweep,'b.mp4', now(), now()) returning id into v_rec2;
  insert into vision.observations(observation_type_id,location,observed_at,sweep_id,
        detector_name,detector_version,detected_at,valid_from)
    values (v_type, ST_GeogFromText('POINT(0.5 0.5)'), now(), v_sweep, 'd','1', now(), now())
    returning id into v_obs;

  -- mutating detector_name must throw
  v_threw := false;
  begin
    update vision.observations set detector_name = 'changed' where id = v_obs;
  exception when others then v_threw := true; end;
  assert v_threw, 'mutating a fact column should raise';

  -- set-once recording_id: first set ok, rewrite raises
  update vision.observations set recording_id = v_rec1 where id = v_obs;     -- null -> value OK
  v_threw := false;
  begin
    update vision.observations set recording_id = v_rec2 where id = v_obs;   -- rewrite -> raise
  exception when others then v_threw := true; end;
  assert v_threw, 'rewriting set-once recording_id should raise';

  -- lifecycle column may change
  update vision.observations set miss_count = miss_count + 1 where id = v_obs;  -- allowed
end $$;
