create table vision.read_model_state (
    only_row     boolean primary key default true check (only_row),
    data_version bigint  not null default 0
);
insert into vision.read_model_state default values;

create or replace function vision.bump_data_version() returns bigint
language sql as $$
    update vision.read_model_state set data_version = data_version + 1
    returning data_version;
$$;

create table platform.tenant_visible_observations (
    tenant_id           uuid   not null references platform.tenants(id) on delete cascade,
    boundary_version_id uuid   not null references geo.tenant_boundary_versions(id),
    observation_id      uuid   not null references vision.observations(id),
    data_version        bigint not null,
    primary key (tenant_id, observation_id)
);
create index tvo_tenant_ix on platform.tenant_visible_observations (tenant_id);

create table platform.tenant_tile_sets (
    id                  uuid primary key default gen_random_uuid(),
    tenant_id           uuid   not null references platform.tenants(id) on delete cascade,
    boundary_version_id uuid   not null references geo.tenant_boundary_versions(id),
    data_version        bigint not null,
    priority_model_id   uuid,
    edition_id          uuid,
    storage_bucket      text   not null default 'tenant-tiles',
    storage_prefix      text   not null,
    status              text   not null check (status in ('building','ready','stale','failed')),
    checksum            text,
    built_at            timestamptz,
    created_at          timestamptz not null default now(),
    unique (tenant_id, boundary_version_id, data_version)
);

-- Full rebuild of a tenant's cached visible set against its active boundary.
create or replace function platform.rebuild_tenant_visible(p_tenant uuid) returns int
language plpgsql security definer set search_path = extensions, public as $$
declare v_bv uuid; v_geom geometry; v_dv bigint; v_count int;
begin
  select id, materialized_geometry into v_bv, v_geom
    from geo.tenant_boundary_versions
    where tenant_id = p_tenant and status = 'active';
  if v_bv is null then return 0; end if;

  select data_version into v_dv from vision.read_model_state;

  delete from platform.tenant_visible_observations where tenant_id = p_tenant;

  insert into platform.tenant_visible_observations (tenant_id, boundary_version_id, observation_id, data_version)
  select p_tenant, v_bv, o.id, v_dv
    from vision.observations o
   where o.superseded_by_observation_id is null
     and o.resolved_at is null
     and ST_Contains(v_geom, o.location::geometry);

  get diagnostics v_count = row_count;
  return v_count;
end $$;

create or replace function platform.can_view_observation(p_observation_id uuid)
returns boolean language sql stable security definer set search_path = extensions, public as $$
    select platform.is_member(platform.active_tenant_id(), 'viewer')
       and exists (
            select 1
            from vision.observations o
            join geo.tenant_boundary_versions b
              on b.tenant_id = platform.active_tenant_id() and b.status = 'active'
            where o.id = p_observation_id
              and ST_Contains(b.materialized_geometry, o.location::geometry)
       );
$$;
