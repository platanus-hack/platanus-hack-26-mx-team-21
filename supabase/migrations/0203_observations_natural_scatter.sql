-- 0203_observations_natural_scatter.sql
-- The 120 bulk seed observations (ids 00b50000-…-<hex(gi)>, gi 1..120) were placed in a
-- golden-angle spiral (seed/30_observations.sql), which rendered as obvious concentric
-- arcs once markers became uniform-size. Re-place them with a deterministic natural
-- scatter (md5(gi) jitter, triangular, denser near the zone center) — matching the
-- updated seed file. Per-axis offset stays within ±0.75*half, so each point remains in
-- its zone's AGEM envelope and its existing geo binding (district/zone) stays valid.
--
-- observations.location is normally append-only (trigger observations_immutable guards
-- provenance). These are synthetic seed coordinates with no real provenance, so the guard
-- is transiently disabled ONLY for this corrective re-placement, then restored.
alter table vision.observations disable trigger observations_immutable;

with zones (zi, clat, clng, half) as (values
  (0, 19.432, -99.133, 0.025),
  (1, 19.357, -99.060, 0.035),
  (2, 19.345, -99.162, 0.028),
  (3, 19.484, -99.110, 0.035),
  (4, 19.360, -99.200, 0.030),
  (5, 19.430, -99.100, 0.022),
  (6, 19.290, -99.170, 0.035)
),
placed as (
  select gi, case when gi % 12 = 0 then 6 else gi % 6 end as zi
  from generate_series(1, 120) as gi
),
pts as (
  select
    ('00b50000-0000-4000-8000-' || lpad(to_hex(p.gi), 12, '0'))::uuid as id,
    z.clat + ((get_byte(decode(md5('lat'||p.gi),'hex'),0) + get_byte(decode(md5('lat'||p.gi),'hex'),1))::numeric/510.0 - 0.5) * 1.5 * z.half as lat,
    z.clng + ((get_byte(decode(md5('lng'||p.gi),'hex'),0) + get_byte(decode(md5('lng'||p.gi),'hex'),1))::numeric/510.0 - 0.5) * 1.5 * z.half as lng
  from placed p
  join zones z on z.zi = p.zi
)
update vision.observations o
   set location = ST_SetSRID(ST_MakePoint(pts.lng, pts.lat), 4326)::geography
  from pts
 where o.id = pts.id;

alter table vision.observations enable trigger observations_immutable;
