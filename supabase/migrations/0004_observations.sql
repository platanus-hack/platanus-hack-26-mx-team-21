create table vision.observations (
    id               uuid primary key default gen_random_uuid(),
    schema_version   smallint not null default 1,

    observation_type_id uuid not null references vision.observation_types(id),
    location         geography(Point,4326) not null,
    observed_at      timestamptz not null,

    sweep_id         uuid not null references vision.sweeps(id),
    recording_id     uuid references vision.recordings(id),
    media_offset_ms  integer,
    frame_ref        text,
    image_bbox       jsonb,
    detector_name    text not null,
    detector_version text not null,
    detected_at      timestamptz not null,

    confirmation_count int not null default 1,
    miss_count         int not null default 0,

    superseded_by_observation_id uuid references vision.observations(id),
    resolved_at         timestamptz,
    resolution_source   text check (resolution_source in ('human','auto_miss')),
    reviewed_by_subject_id uuid references platform.oidc_subjects(id),

    valid_from       timestamptz not null,
    valid_to         timestamptz,
    created_at       timestamptz not null default now(),

    check (superseded_by_observation_id is null or resolved_at is null),
    check (id <> superseded_by_observation_id),
    check (media_offset_ms is null or media_offset_ms >= 0)
);
create index observations_current_gix on vision.observations
    using gist (location)
    where superseded_by_observation_id is null and resolved_at is null;
create index observations_type_ix  on vision.observations (observation_type_id);
create index observations_sweep_ix on vision.observations (sweep_id);
create index observations_recording_ix on vision.observations (recording_id);

create table vision.observation_attribute_values (
    observation_id uuid not null references vision.observations(id),
    definition_id  uuid not null references vision.observation_attribute_definitions(id),
    number_value   numeric,
    text_value     text,
    boolean_value  boolean,
    option_id      uuid references vision.observation_attribute_options(id),
    created_at     timestamptz not null default now(),
    primary key (observation_id, definition_id),
    check (num_nonnulls(number_value, text_value, boolean_value, option_id) = 1)
);

create table vision.observation_thumbnails (
    observation_id      uuid primary key references vision.observations(id),
    storage_bucket      text not null default 'observation-thumbnails',
    storage_path        text not null,
    width               int,
    height              int,
    source_recording_id uuid references vision.recordings(id),
    source_offset_ms    int,
    bbox                jsonb,
    status              text not null default 'pending' check (status in ('pending','ready','failed')),
    created_at          timestamptz not null default now(),
    unique (storage_bucket, storage_path)
);
