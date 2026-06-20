create table vision.sources (
    id         uuid primary key default gen_random_uuid(),
    slug       text not null unique,
    name       text not null,
    status     text not null default 'active' check (status in ('active','retired')),
    created_at timestamptz not null default now()
);

create table vision.observation_types (
    id                          uuid primary key default gen_random_uuid(),
    slug                        text not null unique,
    label                       text not null,
    category                    text not null,
    description                 text,
    merge_radius_m              real not null default 10,
    auto_resolvable             boolean not null default true,
    auto_resolve_miss_threshold int,
    status                      text not null default 'active' check (status in ('active','retired'))
);

create table vision.observation_attribute_definitions (
    id                  uuid primary key default gen_random_uuid(),
    observation_type_id uuid not null references vision.observation_types(id),
    key                 text not null,
    version             int  not null default 1,
    label               text not null,
    value_kind          text not null check (value_kind in ('number','text','boolean','option')),
    unit                text,
    required            boolean not null default false,
    minimum_number      numeric,
    maximum_number      numeric,
    status              text not null default 'active' check (status in ('active','retired')),
    unique (observation_type_id, key, version)
);
-- at most one active version per (type, key)
create unique index observation_attr_def_active_ux
    on vision.observation_attribute_definitions (observation_type_id, key)
    where status = 'active';

create table vision.observation_attribute_options (
    id            uuid primary key default gen_random_uuid(),
    definition_id uuid not null references vision.observation_attribute_definitions(id),
    code          text not null,
    label         text not null,
    status        text not null default 'active' check (status in ('active','retired')),
    unique (definition_id, code)
);

create table vision.sweeps (
    id         uuid primary key default gen_random_uuid(),
    source_id  uuid not null references vision.sources(id),
    coverage   geography not null,
    started_at timestamptz not null,
    ended_at   timestamptz not null,
    created_at timestamptz not null default now(),
    check (ended_at >= started_at)
);
create index sweeps_coverage_gix on vision.sweeps using gist (coverage);
create index sweeps_source_ix on vision.sweeps (source_id);

create table vision.sweep_assessed_types (
    sweep_id            uuid not null references vision.sweeps(id) on delete cascade,
    observation_type_id uuid not null references vision.observation_types(id),
    primary key (sweep_id, observation_type_id)
);

create table vision.recordings (
    id             uuid primary key default gen_random_uuid(),
    sweep_id       uuid not null references vision.sweeps(id),
    storage_bucket text not null default 'sweep-video',
    storage_path   text not null,
    media_type     text not null default 'video/mp4',
    codec          text,
    width          int,
    height         int,
    fps            real,
    started_at     timestamptz not null,
    ended_at       timestamptz not null,
    duration_ms    integer,
    byte_size      bigint,
    checksum       text,
    status         text not null default 'uploading' check (status in ('uploading','ready','failed')),
    created_at     timestamptz not null default now(),
    unique (storage_bucket, storage_path),
    check (ended_at >= started_at)
);
create index recordings_sweep_ix on vision.recordings (sweep_id);
