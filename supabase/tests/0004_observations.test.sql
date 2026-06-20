do $$
begin
  assert to_regclass('vision.observations') is not null, 'vision.observations missing';
  assert to_regclass('vision.observation_attribute_values') is not null, 'attr values missing';
  assert to_regclass('vision.observation_thumbnails') is not null, 'thumbnails missing';
  -- NO attributes column
  assert not exists (select 1 from pg_attribute
    where attrelid='vision.observations'::regclass and attname='attributes' and not attisdropped),
    'observations must NOT have an attributes column';
  -- recording_id is a real FK to vision.recordings
  assert exists (select 1 from pg_constraint c
    where c.conrelid='vision.observations'::regclass and c.contype='f'
      and c.confrelid='vision.recordings'::regclass), 'recording_id FK missing';
  -- media_offset_ms exists
  assert exists (select 1 from pg_attribute
    where attrelid='vision.observations'::regclass and attname='media_offset_ms'),
    'media_offset_ms missing';
end $$;
