create table priority.priority_models (
    id         uuid primary key default gen_random_uuid(),
    name       text not null,
    version    text not null,
    status     text not null default 'active' check (status in ('active','retired')),
    created_at timestamptz not null default now(),
    unique (name, version)
);
create unique index priority_models_active_ux on priority.priority_models ((true)) where status = 'active';

create table priority.priority_batches (
    id               uuid primary key default gen_random_uuid(),
    model_id         uuid not null references priority.priority_models(id),
    trigger_sweep_id uuid references vision.sweeps(id),
    reason           text not null check (reason in ('new_sweep','model_refresh','manual')),
    status           text not null default 'queued'
                          check (status in ('queued','running','completed','completed_with_errors','failed')),
    created_at       timestamptz not null default now(),
    started_at       timestamptz,
    completed_at     timestamptz
);

create table priority.priority_batch_items (
    batch_id       uuid not null references priority.priority_batches(id) on delete cascade,
    observation_id uuid not null references vision.observations(id),
    status         text not null default 'pending' check (status in ('pending','running','completed','failed')),
    failure_code   text,
    updated_at     timestamptz not null default now(),
    primary key (batch_id, observation_id)
);

create table priority.priority_values (
    id                      uuid primary key default gen_random_uuid(),
    observation_id          uuid not null references vision.observations(id),
    model_id                uuid not null references priority.priority_models(id),
    weight                  numeric not null,
    value_state             text not null check (value_state in ('computed','inherited')),
    inherited_from_value_id uuid references priority.priority_values(id),
    computed_by_batch_id    uuid references priority.priority_batches(id),
    created_at              timestamptz not null default now(),
    check ((value_state = 'inherited' and inherited_from_value_id is not null)
        or (value_state = 'computed'  and computed_by_batch_id is not null))
);
create index priority_values_obs_model_ix on priority.priority_values (observation_id, model_id);

create table priority.current_priority_values (
    observation_id    uuid not null references vision.observations(id),
    model_id          uuid not null references priority.priority_models(id),
    priority_value_id uuid not null references priority.priority_values(id),
    updated_at        timestamptz not null default now(),
    primary key (observation_id, model_id)
);
