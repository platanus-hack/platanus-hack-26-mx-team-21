# WhatsApp → Inference Confirmation Channel — Design

**Date:** 2026-06-21
**Status:** Approved, pending implementation plan
**Component:** Confirmation gate between WhatsApp citizen reports and the non-public inference server

## Problem

Citizens send a **photo + location pin** over WhatsApp (handled by the existing
`services/whatsapp-controller` → `services/api` write API). Before a report becomes an
observation on the map, the photo must be **confirmed by an inference server that is not
publicly exposed**. We use **Supabase Realtime** as the message bus: the inference server
holds only an outbound websocket to Supabase — no public ingress.

**End goal:** ask the citizen for a picture + location → send the picture to the inference
server for **confirmation** via Supabase → **only on positive confirmation, create the
observation**.

Inference therefore runs *before* the observation exists and **gates** its creation. This
is not async enrichment, and it replaces the write API's current "create immediately"
behavior for citizen reports.

## Reconciliation with existing pipeline

The citizen-reports pipeline already exists (see
`2026-06-20-whatsapp-citizen-reports-design.md`):

- `services/whatsapp-controller` (Kapso adapter, **no DB/R2 creds**) collects photo + pin
  and POSTs multipart to the write API `POST /v1/observations/citizen`.
- `services/api` `modules/observations/store.py` already creates the observation in one
  transaction via a **synthetic sweep** + a `vision.sources` row (slug `whatsapp-citizen`)
  + thumbnail + `observation_inserted` outbox event + `rebuild_tenant_visible`. It accepts
  a caller-supplied `observation_id`.

Consequences for this design:

- **No `vision.observations` schema change.** The synthetic-sweep path keeps `sweep_id`
  `NOT NULL`; provenance is already modeled. The earlier "Part-4" prep (nullable
  `sweep_id` + `source_id`) is **dropped**.
- **Source slug stays `whatsapp-citizen`** (existing code; the channel creates no source).
- **The write API is the "handler" that waits.** It owns R2 + DB creds, so it uploads the
  photo, enqueues the inference job, waits for confirmation, and only then calls the
  existing `create_citizen_observation`.

## Architecture & data flow

```
WhatsApp user ──photo+pin──▶ controller ──multipart──▶ WRITE API (services/api)
                                                          1. obs_id := new uuid
                                                          2. upload photo → R2
                                                               observations/{obs_id}/report.jpg
                                                          3. INSERT inference_jobs
                                                               {r2_url, thinking_mode,
                                                                status='pending', observation_id=obs_id}
                                                                        │
                                            Realtime INSERT (filter status=pending)
                                                                        ▼
                                                      Inference server (NOT public)
                                                          4. UPDATE status='processing' (atomic claim)
                                                          5. fetch r2_url, run model per thinking_mode
                                                          6. UPDATE response={confirmed,…},
                                                               status='done'  (or error+status='error')
                                                                        │
                                            Realtime UPDATE (filter id=this job)
                                                                        ▼
                                                      WRITE API resumes (waiter)
                                                          7. if response.confirmed:
                                                               create_citizen_observation(obs_id, …)  ← existing path
                                                             else: skip; report not confirmed
                                                          8. return result to controller
controller ──reply──▶ citizen ("confirmado / no se pudo confirmar, intenta otra foto")
```

The photo is uploaded once, to the **final** thumbnail path keyed on a pre-generated
`obs_id`, so on confirmation the existing `store.py` reuses that same id and path — no
copy/move, no second upload.

## The table — `community.inference_jobs`

New `community` schema (signals the new source, keeps the table out of `public`). Follows
the repo's `text + CHECK` convention rather than PostgreSQL enums.

| column | type | notes |
|---|---|---|
| `id` | `uuid primary key default gen_random_uuid()` | job/correlation id |
| `r2_url` | `text not null` | the photo the inference server fetches (`observations/{obs_id}/report.jpg`) |
| `thinking_mode` | `text not null check (thinking_mode in ('flash','thinking'))` | the two modes |
| `status` | `text not null default 'pending' check (status in ('pending','processing','done','error'))` | lifecycle |
| `response` | `jsonb` | empty until the server writes the confirmation verdict (e.g. `{confirmed: bool, type?, notes?}`) |
| `error` | `text` | failure reason, set when `status = 'error'` |
| `observation_id` | `uuid` | the **pre-generated** id the write API will use on confirm; not yet an FK target at insert time, so plain uuid (no FK — the obs row does not exist until step 7) |
| `created_at` | `timestamptz not null default now()` | |
| `updated_at` | `timestamptz not null default now()` | bumped by trigger on update |

`observation_id` is intentionally **not** a foreign key: the row it names is created only
after confirmation, so an FK would reject the insert. It is provenance/correlation only.

### Realtime wiring
- `alter publication supabase_realtime add table community.inference_jobs;`
- `alter table community.inference_jobs replica identity full;` — so UPDATE events carry
  changed columns and clients can filter on them.

### Access / RLS
- `alter table community.inference_jobs enable row level security;` with **no**
  anon/authenticated policies → only service-role reaches it. Both backends (write API,
  inference server) are service-role and bypass RLS.
- Expose the `community` schema to PostgREST (`db-schemas`) so `supabase-py` service-role
  clients can read/write it; RLS keeps it private from anon/authenticated.
- `grant usage on schema community to service_role;` + table privileges to `service_role`
  (a brand-new schema is not covered by existing default privileges).

### updated_at trigger
A small `before update` trigger sets `updated_at = now()`.

## The waiter (write API)

The write API blocks one HTTP request on the confirmation. Primary mechanism: a Realtime
UPDATE subscription filtered on the job id with a **timeout** (e.g. 30–60s; longer for
`thinking`). Fallback if Realtime-in-a-sync-handler is awkward: poll
`select status, response from community.inference_jobs where id = $1` on a short interval
until `status in ('done','error')` or timeout. On timeout → status stays `processing`;
the API returns a "pending confirmation" result and the citizen is asked to wait/retry.
(Decide Realtime-vs-poll in the plan; both satisfy the contract.)

## Concurrency

Single inference worker → trivial. To stay correct with two workers, step 4 is an atomic
claim:

```sql
update community.inference_jobs
   set status = 'processing', updated_at = now()
 where id = $1 and status = 'pending'
returning *;
```

Only one worker wins the row. Realtime is the *notification*; this conditional UPDATE is
the *lock*.

## Testing

- Migration applies cleanly on the remote project.
- Insert a `pending` job → row visible; `replica identity full` set; table is a member of
  the `supabase_realtime` publication.
- Atomic-claim UPDATE: a second `where status='pending'` claim on an already-claimed row
  returns zero rows.
- `thinking_mode` / `status` CHECK constraints reject out-of-domain values.
- anon/authenticated roles cannot select/insert (RLS); service-role can.
- End-to-end (against remote, behind a flag): insert job → simulate inference UPDATE
  (`status='done'`, `response={"confirmed":true}`) → write API creates the observation
  with the pre-generated `obs_id` and it renders on the map; `confirmed:false` → no
  observation created.

## Out of scope / later

- The inference server implementation and its confirmation model.
- The write API endpoint changes that wire in the waiter (separate task; reuses the
  existing `create_citizen_observation`).
- Optional follow-up: durable session/dedupe for multi-instance; per-type confirmation
  thresholds.
