create table platform.tenants (
    id         uuid primary key default gen_random_uuid(),
    name       text not null,
    status     text not null default 'active' check (status in ('active','disabled')),
    created_at timestamptz not null default now()
);

create table platform.oidc_subjects (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null unique references auth.users(id) on delete restrict,
    issuer       text,
    subject      text,
    display_name text,
    status       text not null default 'active' check (status in ('active','disabled')),
    created_at   timestamptz not null default now(),
    unique (issuer, subject)
);

create table platform.tenant_memberships (
    tenant_id  uuid not null references platform.tenants(id) on delete cascade,
    subject_id uuid not null references platform.oidc_subjects(id) on delete cascade,
    role       text not null check (role in ('viewer','analysis_author')),
    created_at timestamptz not null default now(),
    primary key (tenant_id, subject_id)
);
create index tenant_memberships_subject_ix on platform.tenant_memberships (subject_id);

create table platform.audit_events (
    id              uuid primary key default gen_random_uuid(),
    tenant_id       uuid references platform.tenants(id),
    actor_subject_id uuid references platform.oidc_subjects(id),
    module          text not null,
    action          text not null,
    target_type     text,
    target_id       uuid,
    occurred_at     timestamptz not null default now(),
    details         jsonb not null default '{}'::jsonb
);
create index audit_events_tenant_ix on platform.audit_events (tenant_id, occurred_at);

-- RLS helper functions (immutable-search-path security definer)
create or replace function platform.current_subject_id() returns uuid
language sql stable security definer set search_path = '' as $$
    select s.id from platform.oidc_subjects s where s.user_id = auth.uid();
$$;

create or replace function platform.active_tenant_id() returns uuid
language sql stable as $$
    select nullif(current_setting('app.tenant_id', true), '')::uuid;
$$;

create or replace function platform.is_member(p_tenant uuid, p_min_role text default 'viewer')
returns boolean language sql stable security definer set search_path = '' as $$
    select exists (
        select 1
        from platform.tenant_memberships m
        join platform.oidc_subjects s on s.id = m.subject_id
        where s.user_id = auth.uid()
          and m.tenant_id = p_tenant
          and (p_min_role = 'viewer' or m.role = 'analysis_author')
    );
$$;
