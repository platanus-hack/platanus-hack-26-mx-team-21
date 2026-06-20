create table analysis.analysis_providers (
    id         uuid primary key default gen_random_uuid(),
    slug       text not null unique,
    name       text not null,
    status     text not null default 'enabled' check (status in ('enabled','disabled')),
    config_ref text,
    created_at timestamptz not null default now()
);

create table analysis.analysis_definitions (
    id         uuid primary key default gen_random_uuid(),
    kind       text not null unique,           -- e.g. 'budget.route'
    label      text not null,
    created_at timestamptz not null default now()
);

create table analysis.analysis_definition_versions (
    id                uuid primary key default gen_random_uuid(),
    definition_id     uuid not null references analysis.analysis_definitions(id),
    provider_id       uuid not null references analysis.analysis_providers(id),
    interface_version text not null,
    request_schema    jsonb not null,
    result_schema     jsonb not null,
    artifact_kinds    jsonb not null default '[]'::jsonb,
    ui_descriptor     jsonb not null default '{}'::jsonb,
    status            text not null default 'draft' check (status in ('draft','active','retired')),
    created_at        timestamptz not null default now(),
    unique (definition_id, interface_version)
);

create table analysis.provider_capability_snapshots (
    id                    uuid primary key default gen_random_uuid(),
    definition_version_id uuid not null references analysis.analysis_definition_versions(id),
    descriptor            jsonb not null,
    config_version        text not null,
    created_at            timestamptz not null default now()
);

create table analysis.analysis_runs (
    id                    uuid primary key default gen_random_uuid(),
    idempotency_key       text not null,
    tenant_id             uuid not null references platform.tenants(id),
    requested_by_subject_id uuid not null references platform.oidc_subjects(id),
    definition_version_id uuid not null references analysis.analysis_definition_versions(id),
    capability_snapshot_id uuid not null references analysis.provider_capability_snapshots(id),
    boundary_version_id   uuid not null references geo.tenant_boundary_versions(id),
    edition_id            uuid not null references geo.geo_editions(id),
    budget_amount         numeric(14,2) not null check (budget_amount >= 0),
    budget_currency       text not null,
    status                text not null default 'queued'
                              check (status in ('queued','running','succeeded','failed','cancelled')),
    created_at            timestamptz not null default now(),
    started_at           timestamptz,
    finished_at          timestamptz,
    cancel_requested_at  timestamptz,
    cancel_requested_by_subject_id uuid references platform.oidc_subjects(id),
    unique (tenant_id, idempotency_key)
);
create index analysis_runs_tenant_ix on analysis.analysis_runs (tenant_id, created_at);

create table analysis.run_scope_areas (
    run_id      uuid not null references analysis.analysis_runs(id) on delete cascade,
    geo_area_id uuid not null references geo.geo_areas(id),
    primary key (run_id, geo_area_id)
);

create table analysis.run_scope_geometry (
    run_id   uuid primary key references analysis.analysis_runs(id) on delete cascade,
    geometry geometry(Geometry,4326) not null
);

create table analysis.run_type_settings (
    run_id              uuid not null references analysis.analysis_runs(id) on delete cascade,
    observation_type_id uuid not null references vision.observation_types(id),
    enabled             boolean not null default true,
    cost_basis_id       text,
    unit                text,
    unit_rate           numeric(14,2) check (unit_rate is null or unit_rate >= 0),
    primary key (run_id, observation_type_id)
);
