-- Confirmation channel between the WhatsApp write API and the non-public inference server.
-- The write API inserts a 'pending' job (the citizen photo's R2 locator); the inference
-- server (subscribed to supabase_realtime) confirms the photo and writes the verdict back.
-- Only on a positive verdict does the write API create the observation. See
-- docs/superpowers/specs/2026-06-21-whatsapp-inference-channel-design.md.
create schema if not exists community;

create table community.inference_jobs (
    id             uuid primary key default gen_random_uuid(),
    r2_url         text not null,
    thinking_mode  text not null check (thinking_mode in ('flash','thinking')),
    status         text not null default 'pending'
                       check (status in ('pending','processing','done','error')),
    response       jsonb,                 -- empty until the server writes the verdict
    error          text,                  -- set when status = 'error'
    observation_id uuid,                  -- pre-generated id the API uses on confirm (no FK: row not yet created)
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);

-- Fast lookup of work for the inference server / the atomic claim.
create index inference_jobs_pending_ix on community.inference_jobs (created_at)
    where status = 'pending';

-- updated_at maintenance.
create or replace function community.touch_updated_at() returns trigger
language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end $$;

create trigger inference_jobs_touch_updated_at
  before update on community.inference_jobs
  for each row execute function community.touch_updated_at();

-- RLS deny-by-default. The trusted backends connect as a BYPASSRLS role (API DB_URL) or
-- the service_role key (Realtime), so they are unaffected; anon/authenticated get nothing.
alter table community.inference_jobs enable row level security;

grant usage on schema community to service_role;
grant select, insert, update on community.inference_jobs to service_role;

-- Realtime: publish row changes so the non-public inference server can subscribe.
-- Guarded so the migration also applies on a DB without the default Supabase publication.
do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    execute 'alter publication supabase_realtime add table community.inference_jobs';
  end if;
end $$;

-- replica identity full so UPDATE payloads carry all columns (status/response) to subscribers.
alter table community.inference_jobs replica identity full;
