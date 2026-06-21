-- 0305_demo_georeference_sweep.sql
-- Load one real inspection sweep produced by the georeference vision model: a 14s walked
-- run down a CDMX street (final_demo_georeference.mp4, 1280x824 h264 @5fps) whose pipeline
-- output (anomalies.json) georeferenced 3 real potholes by interpolating GPS along the
-- route. This is the first sweep with attached FOOTAGE — the .mp4 lives in R2 at
-- sweep-video/sweeps/{sweep_id}/{recording_id}.mp4 (uploaded out-of-band via wrangler), and
-- app_sweep_route (0304) hands its pointer to the "Ver recorrido" player.
--
-- Fixed UUIDs + ON CONFLICT make this idempotent. The 3 potholes are priority-scored so
-- they survive the app_map_observations 1000-row cap (0303) and render as clickable pins —
-- the entry point to the route preview. Times are CDMX local (America/Mexico_City, -06).

do $$
declare
  v_tenant    constant uuid := 'a0000000-0000-0000-0000-000000000001'; -- Vialia CDMX
  v_boundary  constant uuid := 'b0000000-0000-0000-0000-000000000001'; -- its active boundary
  v_source    constant uuid := '50000000-0000-0000-0000-000000000002'; -- adhoc_survey
  v_type      constant uuid := '70000000-0000-0000-0000-000000000001'; -- pothole
  v_model     constant uuid := 'b1000000-0000-0000-0000-000000000001'; -- active priority model
  v_def_area  constant uuid := '7d000000-0000-0000-0000-000000000001'; -- surface_area_m2
  v_def_conf  constant uuid := '7dc00000-0000-0000-0000-000000000001'; -- confidence
  v_sweep     constant uuid := 'd0000000-0000-0000-0000-000000000001';
  v_rec       constant uuid := 'd0000000-0000-0000-0000-0000000000a1';
  v_batch     constant uuid := 'd0000000-0000-0000-0000-0000000000b1';
  v_started   constant timestamptz := '2026-06-20 12:09:33-06';
  v_ended     constant timestamptz := '2026-06-20 12:09:47-06';
  v_path      constant text := 'sweeps/d0000000-0000-0000-0000-000000000001/d0000000-0000-0000-0000-0000000000a1.mp4';
  v_dv        bigint;
begin
  -- sweep: coverage is the route corridor (start->end line buffered 20m), an honest
  -- "area covered" footprint rather than a GPS breadcrumb (see 0204).
  insert into vision.sweeps (id, source_id, coverage, started_at, ended_at)
  values (v_sweep, v_source,
          ST_Buffer(
            ST_MakeLine(ST_SetSRID(ST_MakePoint(-99.1650187, 19.4025973), 4326),
                        ST_SetSRID(ST_MakePoint(-99.1652173, 19.4033954), 4326))::geography,
            20)::geography,
          v_started, v_ended)
  on conflict (id) do update
    set coverage = excluded.coverage, started_at = excluded.started_at, ended_at = excluded.ended_at;

  insert into vision.sweep_assessed_types (sweep_id, observation_type_id)
  values (v_sweep, v_type) on conflict do nothing;

  -- recording: pointer to the R2 object (no bytes in the DB). status 'ready' so 0304 surfaces it.
  insert into vision.recordings (id, sweep_id, storage_bucket, storage_path, media_type, codec,
                                 width, height, fps, started_at, ended_at, duration_ms, byte_size, status)
  values (v_rec, v_sweep, 'sweep-video', v_path, 'video/mp4', 'h264',
          1280, 824, 5.0, v_started, v_ended, 14000, 10482624, 'ready')
  on conflict (id) do update
    set storage_path = excluded.storage_path, duration_ms = excluded.duration_ms,
        byte_size = excluded.byte_size, status = excluded.status;

  -- three georeferenced potholes (events E1-E3; the E4-E6 "anomalies" were shadows with no
  -- location, so they are not observations). frame_ref/media_offset_ms point back into the clip.
  insert into vision.observations
    (id, observation_type_id, location, observed_at, sweep_id, recording_id, media_offset_ms,
     frame_ref, detector_name, detector_version, detected_at, valid_from)
  values
    ('d0000000-0000-0000-0000-0000000000e1', v_type,
     ST_SetSRID(ST_MakePoint(-99.1650754, 19.4028253), 4326), '2026-06-20 12:09:37-06',
     v_sweep, v_rec, 4000,  'frame:20', 'vision-georef', 'v1', '2026-06-20 12:09:37-06', '2026-06-20 12:09:37-06'),
    ('d0000000-0000-0000-0000-0000000000e2', v_type,
     ST_SetSRID(ST_MakePoint(-99.1651322, 19.4030534), 4326), '2026-06-20 12:09:41-06',
     v_sweep, v_rec, 8000,  'frame:40', 'vision-georef', 'v1', '2026-06-20 12:09:41-06', '2026-06-20 12:09:41-06'),
    ('d0000000-0000-0000-0000-0000000000e3', v_type,
     ST_SetSRID(ST_MakePoint(-99.1651634, 19.4031788), 4326), '2026-06-20 12:09:43.2-06',
     v_sweep, v_rec, 10200, 'frame:51', 'vision-georef', 'v1', '2026-06-20 12:09:43.2-06', '2026-06-20 12:09:43.2-06')
  on conflict (id) do update
    set location = excluded.location, recording_id = excluded.recording_id,
        media_offset_ms = excluded.media_offset_ms, frame_ref = excluded.frame_ref;

  -- attributes: surface_area_m2 (required, drives map "volume") + confidence.
  insert into vision.observation_attribute_values (observation_id, definition_id, number_value)
  values
    ('d0000000-0000-0000-0000-0000000000e1', v_def_area, 0.8),
    ('d0000000-0000-0000-0000-0000000000e2', v_def_area, 1.4),
    ('d0000000-0000-0000-0000-0000000000e3', v_def_area, 0.4),
    ('d0000000-0000-0000-0000-0000000000e1', v_def_conf, 0.90),
    ('d0000000-0000-0000-0000-0000000000e2', v_def_conf, 0.85),
    ('d0000000-0000-0000-0000-0000000000e3', v_def_conf, 0.70)
  on conflict (observation_id, definition_id) do update set number_value = excluded.number_value;

  -- priority scores: keeps the pins in the always-keep set (0303) and colours them by weight.
  insert into priority.priority_batches (id, model_id, trigger_sweep_id, reason, status, completed_at)
  values (v_batch, v_model, v_sweep, 'manual', 'completed', now())
  on conflict (id) do nothing;

  insert into priority.priority_values (id, observation_id, model_id, weight, value_state, computed_by_batch_id)
  values
    ('d0000000-0000-0000-0000-0000000000f1', 'd0000000-0000-0000-0000-0000000000e1', v_model, 88, 'computed', v_batch),
    ('d0000000-0000-0000-0000-0000000000f2', 'd0000000-0000-0000-0000-0000000000e2', v_model, 95, 'computed', v_batch),
    ('d0000000-0000-0000-0000-0000000000f3', 'd0000000-0000-0000-0000-0000000000e3', v_model, 72, 'computed', v_batch)
  on conflict (id) do nothing;

  insert into priority.current_priority_values (observation_id, model_id, priority_value_id)
  values
    ('d0000000-0000-0000-0000-0000000000e1', v_model, 'd0000000-0000-0000-0000-0000000000f1'),
    ('d0000000-0000-0000-0000-0000000000e2', v_model, 'd0000000-0000-0000-0000-0000000000f2'),
    ('d0000000-0000-0000-0000-0000000000e3', v_model, 'd0000000-0000-0000-0000-0000000000f3')
  on conflict (observation_id, model_id) do update set priority_value_id = excluded.priority_value_id;

  -- make the 3 observations visible to the tenant (their points are inside the boundary).
  v_dv := vision.bump_data_version();
  insert into platform.tenant_visible_observations (tenant_id, boundary_version_id, observation_id, data_version)
  select v_tenant, v_boundary, oid, v_dv
  from unnest(array['d0000000-0000-0000-0000-0000000000e1',
                    'd0000000-0000-0000-0000-0000000000e2',
                    'd0000000-0000-0000-0000-0000000000e3']::uuid[]) oid
  on conflict (tenant_id, observation_id) do nothing;
end $$;
