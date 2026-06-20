create table geo.geo_editions (
    id             uuid primary key default gen_random_uuid(),
    source_name    text not null,
    source_release text not null,
    effective_date date,
    checksum       text,
    status         text not null default 'importing'
                        check (status in ('importing','ready','active','failed','retired')),
    imported_at    timestamptz
);
create unique index geo_editions_active_ux on geo.geo_editions ((true)) where status = 'active';

create table geo.geo_areas (
    id             uuid primary key default gen_random_uuid(),
    edition_id     uuid not null references geo.geo_editions(id),
    level          text not null check (level in ('AGEE','AGEM','AGEB')),
    source_cvegeo  text not null,
    cve_ent        text,
    cve_mun        text,
    cve_loc        text,
    cve_ageb       text,
    name           text,
    ageb_kind      text check (ageb_kind in ('urban','rural')),
    parent_area_id uuid references geo.geo_areas(id),
    geometry       geometry(MultiPolygon,4326) not null,
    unique (edition_id, level, source_cvegeo)
);
create index geo_areas_geom_gix on geo.geo_areas using gist (geometry);
create index geo_areas_parent_ix on geo.geo_areas (parent_area_id);

create table geo.tenant_boundary_versions (
    id                   uuid primary key default gen_random_uuid(),
    tenant_id            uuid not null references platform.tenants(id),
    edition_id           uuid not null references geo.geo_editions(id),
    version_number       int  not null,
    status               text not null default 'draft' check (status in ('draft','active','retired')),
    materialized_geometry geometry(MultiPolygon,4326),
    geometry_checksum    text,
    created_at           timestamptz not null default now(),
    activated_at         timestamptz,
    unique (tenant_id, version_number)
);
create unique index tenant_boundary_active_ux
    on geo.tenant_boundary_versions (tenant_id) where status = 'active';
create index tenant_boundary_geom_gix
    on geo.tenant_boundary_versions using gist (materialized_geometry);

create table geo.tenant_boundary_areas (
    boundary_version_id uuid not null references geo.tenant_boundary_versions(id) on delete cascade,
    geo_area_id         uuid not null references geo.geo_areas(id),
    primary key (boundary_version_id, geo_area_id)
);

create table geo.observation_geo_bindings (
    observation_id uuid not null references vision.observations(id),
    edition_id     uuid not null references geo.geo_editions(id),
    agee_area_id   uuid references geo.geo_areas(id),
    agem_area_id   uuid references geo.geo_areas(id),
    ageb_area_id   uuid references geo.geo_areas(id),
    bound_at       timestamptz not null default now(),
    primary key (observation_id, edition_id)
);
