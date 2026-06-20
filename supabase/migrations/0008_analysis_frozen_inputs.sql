create table analysis.run_observations (
    run_id              uuid not null references analysis.analysis_runs(id) on delete cascade,
    observation_id      uuid not null references vision.observations(id),
    observation_type_id uuid not null references vision.observation_types(id),
    location            geography(Point,4326) not null,
    observed_at         timestamptz not null,
    recording_id        uuid,
    frame_ref           text,
    lifecycle_version   bigint,
    primary key (run_id, observation_id)
);

create table analysis.run_observation_attributes (
    run_id         uuid not null,
    observation_id uuid not null,
    definition_key text not null,
    value_kind     text not null,
    number_value   numeric,
    text_value     text,
    boolean_value  boolean,
    option_code    text,
    unit           text,
    primary key (run_id, observation_id, definition_key),
    foreign key (run_id, observation_id)
        references analysis.run_observations (run_id, observation_id) on delete cascade
);

create table analysis.run_priority_values (
    run_id         uuid not null,
    observation_id uuid not null,
    weight         numeric not null,
    model_name     text not null,
    model_version  text not null,
    value_state    text not null check (value_state in ('computed','inherited')),
    primary key (run_id, observation_id),
    foreign key (run_id, observation_id)
        references analysis.run_observations (run_id, observation_id) on delete cascade
);

create table analysis.run_observation_exclusions (
    run_id         uuid not null references analysis.analysis_runs(id) on delete cascade,
    observation_id uuid not null references vision.observations(id),
    reason         text not null check (reason in
                     ('unscored','unsupported_type','disabled_type','missing_required_fact')),
    primary key (run_id, observation_id)
);
