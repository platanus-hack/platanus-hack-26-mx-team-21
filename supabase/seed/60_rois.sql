-- ROIs — LOCAL-RESET FALLBACK FIXTURE.
-- On the deployed remote project the external-data pipeline already produced REAL ROIs
-- (priority.roi_runs / rois from priority.external_signals), and the app plan §4.5 prefers
-- those over synthetic cells, so this file is NOT applied to remote. It exists so a fresh
-- LOCAL `supabase db reset` (which has no pipeline data) still has in-boundary ROIs for the
-- latent layer. Idempotent; safe to leave in the seed set.
set search_path = public, extensions;

insert into priority.roi_runs (id, dimensions, params, signal_window, started_at, completed_at, roi_count) values
  ('40e00000-0000-0000-0000-000000000001', array['crash','crime','flooding'], '{"eps_m":350,"min_samples":5}',
     tstzrange('2026-01-01 00:00:00+00','2026-06-15 00:00:00+00'), '2026-06-15 06:00:00+00','2026-06-15 06:05:00+00',5)
on conflict do nothing;

insert into priority.rois
  (id, run_id, risk_dimension, geom, centroid, area_m2, risk_score, signal_count, dominant_type,
   risk_breakdown, recency_score, description, valid_from, created_at)
values
  ('401a0000-0000-0000-0000-000000000001','40e00000-0000-0000-0000-000000000001','crash',
     ST_MakeEnvelope(-99.075,19.350,-99.065,19.360,4326)::geography, ST_SetSRID(ST_MakePoint(-99.070,19.355),4326)::geography,
     1100000,0.86,42,'collision','{"crash":0.86}',0.7,'Alta siniestralidad vial en Iztapalapa','2026-06-15 06:00:00+00',now()),
  ('401a0000-0000-0000-0000-000000000002','40e00000-0000-0000-0000-000000000001','crime',
     ST_MakeEnvelope(-99.120,19.460,-99.110,19.470,4326)::geography, ST_SetSRID(ST_MakePoint(-99.115,19.465),4326)::geography,
     1100000,0.78,55,'robbery','{"crime":0.78}',0.6,'Concentración de incidentes en GAM','2026-06-15 06:00:00+00',now()),
  ('401a0000-0000-0000-0000-000000000003','40e00000-0000-0000-0000-000000000001','flooding',
     ST_MakeEnvelope(-99.085,19.330,-99.075,19.340,4326)::geography, ST_SetSRID(ST_MakePoint(-99.080,19.335),4326)::geography,
     1100000,0.69,18,'urban_flood','{"flooding":0.69}',0.5,'Encharcamientos recurrentes','2026-06-15 06:00:00+00',now()),
  ('401a0000-0000-0000-0000-000000000004','40e00000-0000-0000-0000-000000000001','crash',
     ST_MakeEnvelope(-99.205,19.355,-99.195,19.365,4326)::geography, ST_SetSRID(ST_MakePoint(-99.200,19.360),4326)::geography,
     1100000,0.74,33,'collision','{"crash":0.74}',0.65,'Cruces conflictivos en Álvaro Obregón','2026-06-15 06:00:00+00',now()),
  ('401a0000-0000-0000-0000-000000000005','40e00000-0000-0000-0000-000000000001','crime',
     ST_MakeEnvelope(-99.140,19.425,-99.130,19.435,4326)::geography, ST_SetSRID(ST_MakePoint(-99.135,19.430),4326)::geography,
     1100000,0.81,47,'robbery','{"crime":0.81}',0.72,'Zona de atención prioritaria en Cuauhtémoc','2026-06-15 06:00:00+00',now())
on conflict do nothing;
