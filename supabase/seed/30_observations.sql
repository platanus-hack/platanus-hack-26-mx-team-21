set search_path = public, extensions;

-- ---- Bulk procedural observations (current) ----
with zones (zi, zone, clat, clng, half, in_b) as (values
  (0,'cuauhtemoc',19.432,-99.133,0.025,true),
  (1,'iztapalapa',19.357,-99.060,0.035,true),
  (2,'coyoacan',19.345,-99.162,0.028,true),
  (3,'gam',19.484,-99.110,0.035,true),
  (4,'alvaro_obregon',19.360,-99.200,0.030,true),
  (5,'venustiano_carranza',19.430,-99.100,0.022,true),
  (6,'tlalpan',19.290,-99.170,0.035,false)  -- OUT of boundary
),
g as (select generate_series(1,120) as gi),
placed as (
  select
    gi,
    -- ~80% in 6 in-boundary zones; ~every 12th goes to tlalpan (out of boundary)
    case when gi % 12 = 0 then 6 else gi % 6 end as zi
  from g
),
pts as (
  select
    p.gi,
    z.zone, z.in_b,
    -- Natural deterministic scatter (md5(gi) jitter), NOT a synthetic spiral. Each axis
    -- uses the mean of two md5 bytes -> triangular spread, denser near the zone center
    -- like a real hotspot. Per-axis offset stays within ±0.75*half, so every point
    -- remains inside the zone's AGEM envelope (clat/clng ± half) and geo binding holds.
    z.clat + ((get_byte(decode(md5('lat'||p.gi),'hex'),0) + get_byte(decode(md5('lat'||p.gi),'hex'),1))::numeric/510.0 - 0.5) * 1.5 * z.half as lat,
    z.clng + ((get_byte(decode(md5('lng'||p.gi),'hex'),0) + get_byte(decode(md5('lng'||p.gi),'hex'),1))::numeric/510.0 - 0.5) * 1.5 * z.half as lng,
    1 + (p.gi % 5) as type_ix  -- 1..5
  from placed p join zones z on z.zi = p.zi
)
insert into vision.observations
  (id, observation_type_id, location, observed_at, sweep_id, recording_id, media_offset_ms,
   frame_ref, image_bbox, detector_name, detector_version, detected_at, confirmation_count, miss_count, valid_from, created_at)
select
  ('00b50000-0000-4000-8000-'||lpad(to_hex(gi),12,'0'))::uuid,
  ('70000000-0000-0000-0000-00000000000'||type_ix)::uuid,
  ST_SetSRID(ST_MakePoint(lng,lat),4326)::geography,
  '2026-06-15 12:00:00+00'::timestamptz - ((gi % 30) * interval '1 day'),
  '5e000000-0000-0000-0000-000000000002',
  '5ec00000-0000-0000-0000-000000000002',
  (gi*937) % 9000000,
  'f'||(gi*13),
  jsonb_build_object('x',0.30,'y',0.30,'w',0.18,'h',0.18),
  'yolo-infra','v1.3',
  '2026-06-15 12:00:00+00'::timestamptz - ((gi % 30) * interval '1 day'),
  1 + (gi % 4), (gi % 7),
  '2026-06-15 12:00:00+00'::timestamptz - ((gi % 30) * interval '1 day'),
  now()
from pts
on conflict do nothing;

-- ---- Superseded pairs (successor inserted first, then predecessor pointing at it) ----
insert into vision.observations
  (id, observation_type_id, location, observed_at, sweep_id, recording_id, media_offset_ms,
   frame_ref, image_bbox, detector_name, detector_version, detected_at, confirmation_count, miss_count, valid_from, created_at)
values
  ('00b50000-0000-4000-8000-000000009101','70000000-0000-0000-0000-000000000001',ST_SetSRID(ST_MakePoint(-99.130,19.430),4326)::geography,'2026-06-14 10:00:00+00','5e000000-0000-0000-0000-000000000002','5ec00000-0000-0000-0000-000000000002',101000,'f9101',jsonb_build_object('x',0.3,'y',0.3,'w',0.2,'h',0.2),'yolo-infra','v1.3','2026-06-14 10:00:00+00',2,0,'2026-06-14 10:00:00+00',now()),
  ('00b50000-0000-4000-8000-000000009102','70000000-0000-0000-0000-000000000003',ST_SetSRID(ST_MakePoint(-99.060,19.357),4326)::geography,'2026-06-14 10:05:00+00','5e000000-0000-0000-0000-000000000002','5ec00000-0000-0000-0000-000000000002',102000,'f9102',jsonb_build_object('x',0.3,'y',0.3,'w',0.2,'h',0.2),'yolo-infra','v1.3','2026-06-14 10:05:00+00',2,0,'2026-06-14 10:05:00+00',now()),
  ('00b50000-0000-4000-8000-000000009103','70000000-0000-0000-0000-000000000002',ST_SetSRID(ST_MakePoint(-99.162,19.345),4326)::geography,'2026-06-14 10:10:00+00','5e000000-0000-0000-0000-000000000002','5ec00000-0000-0000-0000-000000000002',103000,'f9103',jsonb_build_object('x',0.3,'y',0.3,'w',0.2,'h',0.2),'yolo-infra','v1.3','2026-06-14 10:10:00+00',2,0,'2026-06-14 10:10:00+00',now()),
  ('00b50000-0000-4000-8000-000000009104','70000000-0000-0000-0000-000000000005',ST_SetSRID(ST_MakePoint(-99.110,19.484),4326)::geography,'2026-06-14 10:15:00+00','5e000000-0000-0000-0000-000000000002','5ec00000-0000-0000-0000-000000000002',104000,'f9104',jsonb_build_object('x',0.3,'y',0.3,'w',0.2,'h',0.2),'yolo-infra','v1.3','2026-06-14 10:15:00+00',2,0,'2026-06-14 10:15:00+00',now())
on conflict do nothing;

insert into vision.observations
  (id, observation_type_id, location, observed_at, sweep_id, recording_id, media_offset_ms,
   frame_ref, image_bbox, detector_name, detector_version, detected_at, confirmation_count, miss_count,
   superseded_by_observation_id, valid_from, valid_to, created_at)
values
  ('00b50000-0000-4000-8000-000000009001','70000000-0000-0000-0000-000000000001',ST_SetSRID(ST_MakePoint(-99.1301,19.4301),4326)::geography,'2026-06-08 09:00:00+00','5e000000-0000-0000-0000-000000000001','5ec00000-0000-0000-0000-000000000001',9001,'f9001',jsonb_build_object('x',0.3,'y',0.3,'w',0.2,'h',0.2),'yolo-infra','v1.2','2026-06-08 09:00:00+00',1,1,'00b50000-0000-4000-8000-000000009101','2026-06-08 09:00:00+00','2026-06-14 10:00:00+00',now()),
  ('00b50000-0000-4000-8000-000000009002','70000000-0000-0000-0000-000000000003',ST_SetSRID(ST_MakePoint(-99.0601,19.3571),4326)::geography,'2026-06-08 09:05:00+00','5e000000-0000-0000-0000-000000000001','5ec00000-0000-0000-0000-000000000001',9002,'f9002',jsonb_build_object('x',0.3,'y',0.3,'w',0.2,'h',0.2),'yolo-infra','v1.2','2026-06-08 09:05:00+00',1,1,'00b50000-0000-4000-8000-000000009102','2026-06-08 09:05:00+00','2026-06-14 10:05:00+00',now()),
  ('00b50000-0000-4000-8000-000000009003','70000000-0000-0000-0000-000000000002',ST_SetSRID(ST_MakePoint(-99.1621,19.3451),4326)::geography,'2026-06-08 09:10:00+00','5e000000-0000-0000-0000-000000000001','5ec00000-0000-0000-0000-000000000001',9003,'f9003',jsonb_build_object('x',0.3,'y',0.3,'w',0.2,'h',0.2),'yolo-infra','v1.2','2026-06-08 09:10:00+00',1,2,'00b50000-0000-4000-8000-000000009103','2026-06-08 09:10:00+00','2026-06-14 10:10:00+00',now()),
  ('00b50000-0000-4000-8000-000000009004','70000000-0000-0000-0000-000000000005',ST_SetSRID(ST_MakePoint(-99.1101,19.4841),4326)::geography,'2026-06-08 09:15:00+00','5e000000-0000-0000-0000-000000000001','5ec00000-0000-0000-0000-000000000001',9004,'f9004',jsonb_build_object('x',0.3,'y',0.3,'w',0.2,'h',0.2),'yolo-infra','v1.2','2026-06-08 09:15:00+00',1,1,'00b50000-0000-4000-8000-000000009104','2026-06-08 09:15:00+00','2026-06-14 10:15:00+00',now())
on conflict do nothing;

-- ---- Resolved observations (2 human, 2 auto_miss) ----
insert into vision.observations
  (id, observation_type_id, location, observed_at, sweep_id, recording_id, media_offset_ms,
   frame_ref, image_bbox, detector_name, detector_version, detected_at, confirmation_count, miss_count,
   resolved_at, resolution_source, reviewed_by_subject_id, valid_from, valid_to, created_at)
values
  ('00b50000-0000-4000-8000-000000009201','70000000-0000-0000-0000-000000000001',ST_SetSRID(ST_MakePoint(-99.140,19.420),4326)::geography,'2026-06-02 09:00:00+00','5e000000-0000-0000-0000-000000000001','5ec00000-0000-0000-0000-000000000001',9201,'f9201',jsonb_build_object('x',0.3,'y',0.3,'w',0.2,'h',0.2),'yolo-infra','v1.2','2026-06-02 09:00:00+00',3,0,'2026-06-12 16:00:00+00','human','05000000-0000-0000-0000-00000000000a','2026-06-02 09:00:00+00','2026-06-12 16:00:00+00',now()),
  ('00b50000-0000-4000-8000-000000009202','70000000-0000-0000-0000-000000000005',ST_SetSRID(ST_MakePoint(-99.165,19.350),4326)::geography,'2026-06-02 09:05:00+00','5e000000-0000-0000-0000-000000000001','5ec00000-0000-0000-0000-000000000001',9202,'f9202',jsonb_build_object('x',0.3,'y',0.3,'w',0.2,'h',0.2),'yolo-infra','v1.2','2026-06-02 09:05:00+00',2,0,'2026-06-12 16:05:00+00','human','05000000-0000-0000-0000-00000000000a','2026-06-02 09:05:00+00','2026-06-12 16:05:00+00',now()),
  ('00b50000-0000-4000-8000-000000009203','70000000-0000-0000-0000-000000000003',ST_SetSRID(ST_MakePoint(-99.115,19.480),4326)::geography,'2026-06-01 09:10:00+00','5e000000-0000-0000-0000-000000000001','5ec00000-0000-0000-0000-000000000001',9203,'f9203',jsonb_build_object('x',0.3,'y',0.3,'w',0.2,'h',0.2),'yolo-infra','v1.2','2026-06-01 09:10:00+00',1,5,'2026-06-13 03:00:00+00','auto_miss',null,'2026-06-01 09:10:00+00','2026-06-13 03:00:00+00',now()),
  ('00b50000-0000-4000-8000-000000009204','70000000-0000-0000-0000-000000000002',ST_SetSRID(ST_MakePoint(-99.075,19.360),4326)::geography,'2026-06-01 09:15:00+00','5e000000-0000-0000-0000-000000000001','5ec00000-0000-0000-0000-000000000001',9204,'f9204',jsonb_build_object('x',0.3,'y',0.3,'w',0.2,'h',0.2),'yolo-infra','v1.2','2026-06-01 09:15:00+00',1,4,'2026-06-13 03:05:00+00','auto_miss',null,'2026-06-01 09:15:00+00','2026-06-13 03:05:00+00',now())
on conflict do nothing;

-- ---- One quantity attribute value per observation (matches its type's quantity def) ----
insert into vision.observation_attribute_values (observation_id, definition_id, number_value)
select o.id,
       d.id,
       case d.key when 'surface_area_m2' then 1 + (get_byte(decode(md5(o.id::text),'hex'),2) % 40)
                  when 'length_m'        then 2 + (get_byte(decode(md5(o.id::text),'hex'),2) % 60)
                  else 1 + (get_byte(decode(md5(o.id::text),'hex'),2) % 8) end
from vision.observations o
join vision.observation_attribute_definitions d
  on d.observation_type_id = o.observation_type_id and d.key in ('surface_area_m2','length_m','count')
on conflict do nothing;

-- ---- Confidence value per observation ----
insert into vision.observation_attribute_values (observation_id, definition_id, number_value)
select o.id, d.id,
       round((0.55 + (get_byte(decode(md5(o.id::text),'hex'),3) % 45)::numeric/100.0)::numeric, 2)
from vision.observations o
join vision.observation_attribute_definitions d
  on d.observation_type_id = o.observation_type_id and d.key = 'confidence'
on conflict do nothing;

-- ---- Geo bindings (spatial containment binds each point to its AGEM box + the AGEE) ----
insert into geo.observation_geo_bindings (observation_id, edition_id, agee_area_id, agem_area_id, bound_at)
select o.id, 'ed000000-0000-0000-0000-000000000001','9e000000-0000-0000-0000-000000000009', a.id, now()
from vision.observations o
join geo.geo_areas a
  on a.edition_id='ed000000-0000-0000-0000-000000000001' and a.level='AGEM'
 and ST_Contains(a.geometry, o.location::geometry)
on conflict do nothing;
