do $$
declare r1 uuid; r2 uuid;
begin
  assert to_regclass('priority.roi_runs') is not null, 'roi_runs missing';
  assert to_regclass('priority.rois') is not null, 'rois missing';
  assert to_regclass('priority.current_rois') is not null, 'current_rois view missing';

  -- supersession behaviour: run2 retires run1's crash ROI only
  insert into priority.roi_runs(dimensions) values (array['crash','crime']) returning id into r1;
  insert into priority.rois(run_id,risk_dimension,geom,centroid,area_m2,risk_score,signal_count,
                            dominant_type,description)
    values (r1,'crash',
            ST_SetSRID(ST_GeomFromText('POLYGON((0 0,0 1,1 1,1 0,0 0))'),4326)::geography,
            ST_SetSRID(ST_MakePoint(0.5,0.5),4326)::geography,1,1,5,'traffic_crash','x'),
           (r1,'crime',
            ST_SetSRID(ST_GeomFromText('POLYGON((0 0,0 1,1 1,1 0,0 0))'),4326)::geography,
            ST_SetSRID(ST_MakePoint(0.5,0.5),4326)::geography,1,1,5,'crime','y');
  assert (select count(*) from priority.current_rois) = 2, 'expected 2 current';

  insert into priority.roi_runs(dimensions) values (array['crash']) returning id into r2;
  insert into priority.rois(run_id,risk_dimension,geom,centroid,area_m2,risk_score,signal_count,
                            dominant_type,description)
    values (r2,'crash',
            ST_SetSRID(ST_GeomFromText('POLYGON((0 0,0 1,1 1,1 0,0 0))'),4326)::geography,
            ST_SetSRID(ST_MakePoint(0.5,0.5),4326)::geography,1,1,6,'traffic_crash','z');
  update priority.rois set valid_to = now(), superseded_by_run_id = r2
   where valid_to is null and run_id <> r2 and risk_dimension = any(array['crash']);

  assert (select count(*) from priority.current_rois) = 2, 'still 2 current (fresh crash + crime)';
  assert (select count(*) from priority.current_rois where risk_dimension='crash') = 1, 'one crash';
  assert (select count(*) from priority.rois) = 3, 'history retained';
end $$;
