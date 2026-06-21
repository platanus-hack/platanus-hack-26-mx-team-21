# WhatsApp → Inference Realtime Channel — Design

**Date:** 2026-06-21
**Status:** Approved, pending implementation plan

## Problem

The WhatsApp handler must hand an incoming image to an **inference server that is not
publicly exposed**, then wait for the model's response. We use **Supabase Realtime** as
the message bus: the inference server holds only an outbound websocket to Supabase and
never accepts public ingress. Incoming images are also community-sourced **events**, so
the handler will (later) create a `vision.observation` from each one — distinguished from
sweep-sourced observations as a `whatsapp` source.

## Scope

In scope:
- A `community.inference_jobs` table that carries one inference request/response over
  Supabase Realtime.
- Lifecycle status + error channel.
- Schema-prep on `vision.observations` so the handler can create a community-sourced
  observation later without a further migration.

Out of scope (deferred, handler-side, later work):
- The WhatsApp webhook handler code and the inference server code.
- Deriving the observation's lat/lng (location source TBD).
- Actually creating the `vision.observation` + thumbnail + attributes + outbox event.

## Architecture & data flow

Two trusted backends, both authenticating to Supabase with the **service-role** key
(both bypass RLS). The inference server never gets a public ingress — it only holds an
outbound Realtime websocket.

```
WhatsApp webhook ──► Handler (FastAPI / Fly)
                       1. upload image → R2
                       2. INSERT job {r2_url, thinking_mode, status='pending'}
                                          │
                    Realtime INSERT (filter status=pending)
                                          ▼
                            Inference server (not public)
                       3. UPDATE status='processing'   (atomic claim)
                       4. fetch r2_url, run model per thinking_mode
                       5. UPDATE response=…, status='done'   (or error+status='error')
                                          │
                    Realtime UPDATE (filter id=this job)
                                          ▼
                            Handler resumes
                       6. reply on WhatsApp
                       7. (later) create community vision.observation
```

## The table — `community.inference_jobs`

New `community` schema (signals the new source, keeps the table out of `public`).
Follows the repo convention of `text + CHECK` rather than PostgreSQL enums.

| column | type | notes |
|---|---|---|
| `id` | `uuid primary key default gen_random_uuid()` | correlation id |
| `r2_url` | `text not null` | object URL the inference server fetches |
| `thinking_mode` | `text not null check (thinking_mode in ('flash','thinking'))` | the two modes |
| `status` | `text not null default 'pending' check (status in ('pending','processing','done','error'))` | lifecycle |
| `response` | `jsonb` | empty until the server writes the result (jsonb so it can carry classification + attributes) |
| `error` | `text` | failure reason, set when `status = 'error'` |
| `location` | `geography(Point,4326)` (nullable) | forward-hook for the deferred lat/lng, so no later migration is needed |
| `observation_id` | `uuid references vision.observations(id)` (nullable) | filled when the handler creates the observation |
| `created_at` | `timestamptz not null default now()` | |
| `updated_at` | `timestamptz not null default now()` | bumped by trigger on update |

### Realtime wiring
- `alter publication supabase_realtime add table community.inference_jobs;`
- `alter table community.inference_jobs replica identity full;` — so UPDATE events carry
  the changed columns and clients can filter on them.

### Access / RLS
- `alter table community.inference_jobs enable row level security;` with **no**
  anon/authenticated policies → only service-role reaches it. Both backends are
  service-role, which bypasses RLS.
- Expose the `community` schema to PostgREST (add to `db-schemas`) so `supabase-py`
  service-role clients can read/write it; RLS keeps it private from anon/authenticated.
- `grant usage on schema community to service_role;` and table privileges to
  `service_role` (a brand-new schema is not covered by existing default privileges).

### updated_at trigger
A small `before update` trigger sets `updated_at = now()`.

## Concurrency

A single inference worker makes this trivial. To stay correct if two ever run, step 3 is
an **atomic claim**:

```sql
update community.inference_jobs
   set status = 'processing', updated_at = now()
 where id = $1 and status = 'pending'
returning *;
```

Only one worker wins the row. Realtime is the *notification*; this conditional UPDATE is
the *lock*. (pgmq is the alternative transport, but Realtime is the chosen mechanism, so
this conditional update is the lightweight guard.)

## Community-observation schema-prep

`vision.observations.sweep_id` is currently `NOT NULL`, so a community observation cannot
exist without a sweep. Minimal prep so the handler is unblocked later:

- `alter table vision.observations alter column sweep_id drop not null;`
- `alter table vision.observations add column source_id uuid references vision.sources(id);`
- add check `(sweep_id is not null or source_id is not null)` — every observation keeps a
  provenance.
- seed a `vision.sources` row with `slug = 'whatsapp'` — the handle the frontend/priority
  queries filter on to distinguish community-sourced observations.

Visibility is purely geographic (`platform.can_view_observation` / the
`tenant_visible_observations` read-model clip by boundary). So once the handler inserts a
community observation that falls inside the tenant boundary and emits an
`observation_inserted` outbox event (the existing path), it surfaces on the map. **No**
changes to `can_view_observation` or the R2 broker are required.

## Testing

- Migration applies cleanly on the remote project (idempotent where the repo's migrations
  are).
- Insert a `pending` job → row visible; `replica identity full` set; table is a member of
  the `supabase_realtime` publication.
- Atomic-claim UPDATE: a second `where status='pending'` claim on an already-claimed row
  returns zero rows.
- `thinking_mode` / `status` CHECK constraints reject out-of-domain values.
- anon/authenticated roles cannot select/insert (RLS); service-role can.
- A `vision.observation` with `sweep_id is null` and `source_id` = the `whatsapp` source
  inserts successfully and is rejected when both `sweep_id` and `source_id` are null.

## Open / deferred decisions

- Location derivation for the observation (WhatsApp pin vs inference-returned vs both).
- Observation type mapping from the inference response.
- The handler and inference-server implementations themselves.
