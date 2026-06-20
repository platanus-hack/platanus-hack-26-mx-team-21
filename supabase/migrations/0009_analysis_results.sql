create table vision.vision_outbox_events (
    id            uuid primary key default gen_random_uuid(),
    event_kind    text not null,                 -- 'sweep_completed','observation_superseded','observation_resolved'
    entity_id     uuid,
    related_id    uuid,
    occurred_at   timestamptz not null default now(),
    delivery_state text not null default 'pending' check (delivery_state in ('pending','delivered'))
);
create index vision_outbox_pending_ix on vision.vision_outbox_events (occurred_at)
    where delivery_state = 'pending';

create table analysis.analysis_outbox_events (
    id            uuid primary key default gen_random_uuid(),
    aggregate_id  uuid not null,
    event_kind    text not null,
    payload       jsonb not null default '{}'::jsonb,
    created_at    timestamptz not null default now(),
    delivery_state text not null default 'pending' check (delivery_state in ('pending','delivered'))
);
create index analysis_outbox_pending_ix on analysis.analysis_outbox_events (created_at)
    where delivery_state = 'pending';

create table analysis.analysis_attempts (
    id                  uuid primary key default gen_random_uuid(),
    run_id              uuid not null references analysis.analysis_runs(id) on delete cascade,
    attempt_number      int not null,
    provider_request_id text,
    status              text not null default 'running'
                            check (status in ('running','succeeded','failed','cancelled')),
    started_at          timestamptz not null default now(),
    finished_at         timestamptz,
    response_hash       text,
    failure_code        text,
    failure_details     jsonb,
    unique (run_id, attempt_number)
);

create table analysis.analysis_results (
    id                  uuid primary key default gen_random_uuid(),
    run_id              uuid not null unique references analysis.analysis_runs(id) on delete cascade,
    accepted_attempt_id uuid not null references analysis.analysis_attempts(id),
    provider_version    text not null,
    config_version      text not null,
    result_schema_version text not null,
    payload             jsonb not null,
    created_at          timestamptz not null default now()
);

create table analysis.result_metrics (
    id           uuid primary key default gen_random_uuid(),
    result_id    uuid not null references analysis.analysis_results(id) on delete cascade,
    key          text not null,
    label        text,
    unit         text,
    number_value numeric,
    text_value   text
);

create table analysis.result_warnings (
    id        uuid primary key default gen_random_uuid(),
    result_id uuid not null references analysis.analysis_results(id) on delete cascade,
    code      text not null,
    severity  text,
    message   text
);

create table analysis.artifacts (
    id             uuid primary key default gen_random_uuid(),
    result_id      uuid not null references analysis.analysis_results(id) on delete cascade,
    kind           text not null check (kind in ('map_features','ordered_sequence','table','chart','asset_ref')),
    schema_version text not null,
    display_order  int not null default 0,
    title          text,
    payload        jsonb not null default '{}'::jsonb
);

create table analysis.map_features (
    id          uuid primary key default gen_random_uuid(),
    artifact_id uuid not null references analysis.artifacts(id) on delete cascade,
    geometry    geometry(Geometry,4326) not null,
    feature_key text,
    properties  jsonb not null default '{}'::jsonb
);
create index map_features_geom_gix on analysis.map_features using gist (geometry);

create table analysis.artifact_observation_refs (
    id            uuid primary key default gen_random_uuid(),
    artifact_id   uuid not null references analysis.artifacts(id) on delete cascade,
    run_id        uuid not null,
    observation_id uuid not null,
    role          text not null,
    display_order int,
    foreign key (run_id, observation_id)
        references analysis.run_observations (run_id, observation_id)
);

create table analysis.sequence_items (
    id                 uuid primary key default gen_random_uuid(),
    artifact_id        uuid not null references analysis.artifacts(id) on delete cascade,
    position           int not null,
    run_id             uuid,
    observation_id     uuid,
    provider_ref       text,
    label              text,
    foreign key (run_id, observation_id)
        references analysis.run_observations (run_id, observation_id)
);

create table analysis.asset_refs (
    id                uuid primary key default gen_random_uuid(),
    artifact_id       uuid not null references analysis.artifacts(id) on delete cascade,
    provider_asset_id text not null,
    media_type        text,
    integrity_hash    text,
    storage_ref       text
);
