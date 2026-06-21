-- Idempotency key for citizen-report ingest (POST /v1/observations/citizen).
--
-- The WhatsApp controller retries the ingest call (network slow / timeout), and the old
-- create_citizen_observation minted a fresh observation uuid on every call with no dedupe,
-- producing duplicate observations / sweeps / thumbnail rows / R2 objects on each retry.
--
-- This side table keys ingest on the controller-supplied kapso_message_id so a retry with
-- the same message id returns the already-created observation instead of creating a new one.
-- It deliberately does NOT alter the immutable vision.observations contract table (0004):
-- it is a separate additive mapping table, written by the service DB role.
--
-- This migration is additive / backward-compatible: it can (and must) be applied to the live
-- DB BEFORE the new code deploys. The pre-deploy code never reads or writes this table, so an
-- empty table is harmless; the post-deploy code requires it to exist.
--
-- No SECURITY DEFINER / RLS bypass machinery is needed: the only writer is the API's DB role
-- (the same role that already inserts into vision.observations within one transaction).

create table if not exists vision.citizen_report_ingest (
    kapso_message_id text primary key,
    observation_id   uuid not null references vision.observations(id),
    created_at       timestamptz not null default now()
);

-- RLS deny-by-default, mirroring community.inference_jobs (0300). The API connects as a
-- BYPASSRLS role, so it is unaffected; anon/authenticated get nothing.
alter table vision.citizen_report_ingest enable row level security;
