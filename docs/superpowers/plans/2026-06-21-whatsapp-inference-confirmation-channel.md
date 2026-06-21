# WhatsApp Inference Confirmation Channel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Supabase-Realtime channel (`community.inference_jobs`) over which the write API sends a citizen's photo to a non-public inference server for confirmation, and gates observation creation on a positive verdict.

**Architecture:** A new `community.inference_jobs` table is the message bus. The write API (`services/api`, holds DB+R2 creds) uploads the photo, enqueues a job row, and polls it until the inference server (subscribed via the `supabase_realtime` publication, no public ingress) writes a verdict. Only on `confirmed:true` does the API call the existing `create_citizen_observation`. The gate is behind a default-off setting, so the current pipeline is unchanged until enabled.

**Tech Stack:** PostgreSQL (Supabase), `pgmq`-free Realtime publication, Python 3 / FastAPI, `psycopg` (v3), `pydantic-settings`, `pytest` + `fastapi.testclient`.

## Global Constraints

- Migration file lives at `supabase/migrations/0300_community_inference_jobs.sql`; applied to the remote project `joixzhdpnxqhnuscxsoy` via the Supabase MCP `apply_migration`, verified via `execute_sql`. (Convention: `0001-0013` core, `01xx` priority, `02xx` app/r2, **`03xx` community** — this is the first `03xx`.)
- Schema/table style follows the repo: `text` + `CHECK` constraints, **not** PostgreSQL enums.
- `thinking_mode` domain is exactly `('flash','thinking')`. `status` domain is exactly `('pending','processing','done','error')`.
- The `community` schema is **not** exposed to PostgREST. Backends reach the table via direct `psycopg` connections (the API's `DB_URL`, which connects as a role that bypasses RLS) and via the Realtime publication; RLS stays deny-by-default.
- `observation_id` on the job is a plain `uuid` (no FK) — the observation row does not exist until after confirmation.
- The confirmation gate ships **disabled by default** (`INFERENCE_CONFIRMATION_ENABLED=false`).
- All API tests run from `services/api`: `uv run pytest` (or `pytest` inside the venv).

---

### Task 1: Migration — `community.inference_jobs` table, RLS, Realtime, trigger

**Files:**
- Create: `supabase/migrations/0300_community_inference_jobs.sql`

**Interfaces:**
- Produces: table `community.inference_jobs (id uuid, r2_url text, thinking_mode text, status text, response jsonb, error text, observation_id uuid, created_at timestamptz, updated_at timestamptz)`; member of publication `supabase_realtime`; `replica identity full`.

- [ ] **Step 1: Write the migration**

Create `supabase/migrations/0300_community_inference_jobs.sql`:

```sql
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
```

- [ ] **Step 2: Apply the migration to the remote project**

Use the Supabase MCP tool `apply_migration` with `name = "0300_community_inference_jobs"` and `query` = the full SQL above.
Expected: success, no error.

- [ ] **Step 3: Verify schema, constraints, RLS, publication, replica identity**

Run via the Supabase MCP `execute_sql`:

```sql
-- columns present
select column_name, data_type from information_schema.columns
where table_schema = 'community' and table_name = 'inference_jobs' order by ordinal_position;
-- RLS enabled
select relrowsecurity from pg_class where oid = 'community.inference_jobs'::regclass;
-- publication membership
select 1 from pg_publication_tables where pubname = 'supabase_realtime'
  and schemaname = 'community' and tablename = 'inference_jobs';
-- replica identity = 'f' (full)
select relreplident from pg_class where oid = 'community.inference_jobs'::regclass;
```
Expected: 9 columns; `relrowsecurity = true`; one publication row; `relreplident = 'f'`.

- [ ] **Step 4: Verify CHECK constraints and the atomic claim**

Run via `execute_sql`:

```sql
-- bad thinking_mode rejected
do $$ begin
  begin
    insert into community.inference_jobs (r2_url, thinking_mode) values ('s3://b/p', 'turbo');
    raise exception 'expected check violation';
  exception when check_violation then null; end;
end $$;

-- happy insert + atomic claim
insert into community.inference_jobs (id, r2_url, thinking_mode)
values ('00000000-0000-0000-0000-000000000001', 's3://b/p', 'flash');

with claimed as (
  update community.inference_jobs set status = 'processing'
  where id = '00000000-0000-0000-0000-000000000001' and status = 'pending'
  returning id)
select count(*) as won from claimed;          -- expect 1

with claimed as (
  update community.inference_jobs set status = 'processing'
  where id = '00000000-0000-0000-0000-000000000001' and status = 'pending'
  returning id)
select count(*) as won_again from claimed;     -- expect 0 (already claimed)

-- updated_at advanced past created_at after the UPDATE
select updated_at > created_at as bumped from community.inference_jobs
where id = '00000000-0000-0000-0000-000000000001';   -- expect true

delete from community.inference_jobs where id = '00000000-0000-0000-0000-000000000001';
```
Expected: no error; `won = 1`; `won_again = 0`; `bumped = true`.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/0300_community_inference_jobs.sql
git commit -m "feat(db): community.inference_jobs realtime confirmation channel"
```

---

### Task 2: `inference.py` — enqueue/wait store + verdict helper + R2 locator

**Files:**
- Create: `services/api/src/citycrawl_api/modules/observations/inference.py`
- Modify: `services/api/src/citycrawl_api/modules/observations/storage.py` (add `object_locator`)
- Test: `services/api/tests/api/test_inference_channel.py`

**Interfaces:**
- Consumes: `community.inference_jobs` (Task 1); `psycopg` connect via `dsn`.
- Produces:
  - `object_locator(bucket: str, path: str) -> str` → `"s3://{bucket}/{path}"`.
  - `is_confirmed(result: dict) -> bool` (pure).
  - `class PgInferenceJobStore(dsn: str)` with
    `enqueue(*, observation_id: UUID, r2_url: str, thinking_mode: str) -> UUID` and
    `wait_for_result(job_id: UUID, *, timeout_s: float, poll_interval_s: float) -> dict`
    returning `{"status": str, "response": dict | None, "error": str | None}` where
    `status ∈ {'done','error','timeout'}`.

- [ ] **Step 1: Write the failing unit test for `is_confirmed` and `object_locator`**

Create `services/api/tests/api/test_inference_channel.py`:

```python
"""Unit tests for the inference-confirmation channel helpers. Pure logic only — the
PgInferenceJobStore DB path needs Postgres and is covered by the DB-guarded test below."""
import os
import uuid

import pytest

from citycrawl_api.modules.observations.inference import is_confirmed
from citycrawl_api.modules.observations.storage import object_locator


def test_object_locator_builds_s3_uri():
    assert object_locator("observation-thumbnails", "observations/x/report.jpg") == \
        "s3://observation-thumbnails/observations/x/report.jpg"


def test_is_confirmed_true_when_done_and_confirmed():
    assert is_confirmed({"status": "done", "response": {"confirmed": True}}) is True


def test_is_confirmed_false_when_not_done():
    assert is_confirmed({"status": "timeout", "response": None, "error": "x"}) is False


def test_is_confirmed_false_when_verdict_negative():
    assert is_confirmed({"status": "done", "response": {"confirmed": False}}) is False


def test_is_confirmed_false_when_response_missing():
    assert is_confirmed({"status": "done", "response": None}) is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd services/api && uv run pytest tests/api/test_inference_channel.py -v`
Expected: FAIL with `ModuleNotFoundError` / `ImportError` (no `inference` module, no `object_locator`).

- [ ] **Step 3: Add `object_locator` to `storage.py`**

Append to `services/api/src/citycrawl_api/modules/observations/storage.py`:

```python
def object_locator(bucket: str, path: str) -> str:
    """Backend-agnostic locator handed to the inference server (which holds R2 creds).
    The logical bucket name is what the DB records, so 's3://{bucket}/{path}' resolves the
    same object the broker serves."""
    return f"s3://{bucket}/{path}"
```

- [ ] **Step 4: Write the `inference.py` module**

Create `services/api/src/citycrawl_api/modules/observations/inference.py`:

```python
"""Confirmation channel client. Enqueues a photo-confirmation job on
community.inference_jobs and polls for the verdict written by the non-public inference
server. Not unit-tested for the DB path (needs Postgres); exercised against the remote
with DB_URL set. See docs/superpowers/specs/2026-06-21-whatsapp-inference-channel-design.md.
"""
from __future__ import annotations

import time
from uuid import UUID, uuid4


def is_confirmed(result: dict) -> bool:
    """True iff the inference server returned a positive confirmation verdict."""
    if result.get("status") != "done":
        return False
    response = result.get("response") or {}
    return bool(response.get("confirmed"))


class PgInferenceJobStore:
    def __init__(self, dsn: str):
        import psycopg

        self._psycopg = psycopg
        self.dsn = dsn

    def enqueue(self, *, observation_id: UUID, r2_url: str, thinking_mode: str) -> UUID:
        job_id = uuid4()
        with self._psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into community.inference_jobs
                        (id, r2_url, thinking_mode, status, observation_id)
                    values (%s, %s, %s, 'pending', %s)
                    """,
                    (job_id, r2_url, thinking_mode, observation_id),
                )
        return job_id

    def wait_for_result(
        self, job_id: UUID, *, timeout_s: float, poll_interval_s: float
    ) -> dict:
        """Polls the job row until it reaches a terminal state or the timeout elapses.
        Returns {"status": 'done'|'error'|'timeout', "response": dict|None, "error": str|None}.
        Blocking — callers in async handlers must run this via asyncio.to_thread."""
        deadline = time.monotonic() + timeout_s
        while True:
            with self._psycopg.connect(self.dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "select status, response, error "
                        "from community.inference_jobs where id = %s",
                        (job_id,),
                    )
                    row = cur.fetchone()
            if row is None:
                return {"status": "error", "response": None, "error": "job not found"}
            status, response, error = row
            if status in ("done", "error"):
                return {"status": status, "response": response, "error": error}
            if time.monotonic() >= deadline:
                return {"status": "timeout", "response": None, "error": "inference timeout"}
            time.sleep(poll_interval_s)
```

- [ ] **Step 5: Run the unit test to verify it passes**

Run: `cd services/api && uv run pytest tests/api/test_inference_channel.py -v`
Expected: PASS (5 passed).

- [ ] **Step 6: Add the DB-guarded integration test for enqueue/wait**

Append to `services/api/tests/api/test_inference_channel.py`:

```python
@pytest.mark.skipif(not os.getenv("DB_URL"), reason="needs a live Postgres (DB_URL)")
def test_enqueue_then_wait_returns_simulated_verdict():
    """Enqueue a job, simulate the inference server completing it, assert wait returns it.
    Runs only when DB_URL points at the remote (migration 0300 applied)."""
    import psycopg

    from citycrawl_api.modules.observations.inference import PgInferenceJobStore

    dsn = os.environ["DB_URL"]
    store = PgInferenceJobStore(dsn)
    obs_id = uuid.uuid4()
    job_id = store.enqueue(
        observation_id=obs_id, r2_url="s3://observation-thumbnails/t/report.jpg",
        thinking_mode="flash",
    )
    # Act as the inference server: write a positive verdict.
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "update community.inference_jobs set status='done', "
            "response='{\"confirmed\": true}'::jsonb where id = %s",
            (job_id,),
        )
    result = store.wait_for_result(job_id, timeout_s=5, poll_interval_s=0.2)
    assert result["status"] == "done"
    assert result["response"]["confirmed"] is True
    # cleanup
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("delete from community.inference_jobs where id = %s", (job_id,))
```

- [ ] **Step 7: Run the full file (integration test skips without DB_URL)**

Run: `cd services/api && uv run pytest tests/api/test_inference_channel.py -v`
Expected: PASS; the integration test reports `SKIPPED` unless `DB_URL` is set (set it to run it green against the remote).

- [ ] **Step 8: Commit**

```bash
git add services/api/src/citycrawl_api/modules/observations/inference.py \
        services/api/src/citycrawl_api/modules/observations/storage.py \
        services/api/tests/api/test_inference_channel.py
git commit -m "feat(api): inference-confirmation channel client (enqueue/wait/verdict)"
```

---

### Task 3: Wire the confirmation gate into `/v1/observations/citizen` (default off)

**Files:**
- Modify: `services/api/src/citycrawl_api/config.py` (4 settings fields)
- Modify: `services/api/src/citycrawl_api/routers/observations.py` (gate before obs creation)
- Test: `services/api/tests/api/test_observations_gate.py`

**Interfaces:**
- Consumes: `PgInferenceJobStore`, `is_confirmed`, `object_locator` (Task 2); existing `PgObservationStore.create_citizen_observation`, `make_thumbnail_store`, `require_service`.
- Produces: same route `POST /v1/observations/citizen`. With the gate off → unchanged 200. With the gate on → 200 only if confirmed, else `422 {"error":{"code":"not_confirmed"}}`.

- [ ] **Step 1: Write the failing router tests**

Create `services/api/tests/api/test_observations_gate.py`:

```python
"""The citizen route's confirmation gate. Stores are faked (no DB/R2) so we test only the
branching: gate off → create; gate on + confirmed → create; gate on + unconfirmed/timeout → 422."""
import uuid

import pytest

import citycrawl_api.routers.observations as obs_route
from citycrawl_api.config import get_settings


class _FakeThumbStore:
    def write_bytes(self, path, data):  # noqa: D401
        return None


def _fake_make_thumbnail_store(settings):
    return _FakeThumbStore(), "observation-thumbnails"


class _FakeObsStore:
    def __init__(self, dsn):
        pass

    def create_citizen_observation(self, **kw):
        return {
            "observation_id": str(kw["observation_id"]),
            "in_boundary": True,
            "thumbnail_path": kw["thumbnail_path"],
        }


class _FakeJobStore:
    verdict = {"status": "done", "response": {"confirmed": True}, "error": None}

    def __init__(self, dsn):
        pass

    def enqueue(self, **kw):
        return uuid.uuid4()

    def wait_for_result(self, job_id, **kw):
        return type(self).verdict


@pytest.fixture
def gate_env(monkeypatch):
    monkeypatch.setenv("OPERATOR_API_KEY", "secret-op-key")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("DB_URL", "postgresql://fake")
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


@pytest.fixture
def patched_stores(monkeypatch):
    monkeypatch.setattr(obs_route, "make_thumbnail_store", _fake_make_thumbnail_store)
    monkeypatch.setattr(obs_route, "PgObservationStore", _FakeObsStore)
    monkeypatch.setattr(obs_route, "PgInferenceJobStore", _FakeJobStore)
    _FakeJobStore.verdict = {"status": "done", "response": {"confirmed": True}, "error": None}


def _post(raw_client):
    return raw_client.post(
        "/v1/observations/citizen",
        data={
            "lat": "19.4326", "lng": "-99.1332",
            "observed_at": "2026-06-21T00:00:00Z", "observation_type": "pothole",
        },
        files={"image": ("report.jpg", b"\xff\xd8\xff\xd9", "image/jpeg")},
        headers={"X-Operator-Key": "secret-op-key"},
    )


def test_gate_off_creates_observation(raw_client, gate_env, patched_stores):
    gate_env.setenv("INFERENCE_CONFIRMATION_ENABLED", "false")
    get_settings.cache_clear()
    r = _post(raw_client)
    assert r.status_code == 200
    assert r.json()["observationId"]


def test_gate_on_confirmed_creates_observation(raw_client, gate_env, patched_stores):
    gate_env.setenv("INFERENCE_CONFIRMATION_ENABLED", "true")
    get_settings.cache_clear()
    r = _post(raw_client)
    assert r.status_code == 200
    assert r.json()["observationId"]


def test_gate_on_unconfirmed_returns_422(raw_client, gate_env, patched_stores):
    gate_env.setenv("INFERENCE_CONFIRMATION_ENABLED", "true")
    get_settings.cache_clear()
    _FakeJobStore.verdict = {"status": "done", "response": {"confirmed": False}, "error": None}
    r = _post(raw_client)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "not_confirmed"


def test_gate_on_timeout_returns_422(raw_client, gate_env, patched_stores):
    gate_env.setenv("INFERENCE_CONFIRMATION_ENABLED", "true")
    get_settings.cache_clear()
    _FakeJobStore.verdict = {"status": "timeout", "response": None, "error": "inference timeout"}
    r = _post(raw_client)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "not_confirmed"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd services/api && uv run pytest tests/api/test_observations_gate.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'PgInferenceJobStore'` (router doesn't import it yet) and/or the gate-on tests not returning 422.

- [ ] **Step 3: Add the settings fields**

In `services/api/src/citycrawl_api/config.py`, add after the `operator_api_key` field block:

```python
    # --- Citizen-report confirmation gate (non-public inference server) -------
    inference_confirmation_enabled: bool = False
    inference_thinking_mode: str = "flash"     # 'flash' | 'thinking'
    inference_timeout_s: float = 60.0
    inference_poll_interval_s: float = 1.0
```

- [ ] **Step 4: Wire the gate into the router**

In `services/api/src/citycrawl_api/routers/observations.py`:

Add imports near the existing observation imports:

```python
import asyncio

from citycrawl_api.modules.observations.inference import (
    PgInferenceJobStore,
    is_confirmed,
)
from citycrawl_api.modules.observations.storage import make_thumbnail_store, object_locator
```

(The existing `from ...storage import make_thumbnail_store` line becomes the combined import above — keep a single import line for that module.)

Then, in `create_citizen_observation`, insert the gate **after** the `store.write_bytes(...)` block and **before** `pg = PgObservationStore(...)`:

```python
    # Confirmation gate (disabled by default). When enabled, the photo must be confirmed
    # by the non-public inference server before we create the observation.
    if settings.inference_confirmation_enabled:
        jobs = PgInferenceJobStore(settings.db_url)
        job_id = jobs.enqueue(
            observation_id=observation_id,
            r2_url=object_locator(bucket, thumbnail_path),
            thinking_mode=settings.inference_thinking_mode,
        )
        verdict = await asyncio.to_thread(
            jobs.wait_for_result,
            job_id,
            timeout_s=settings.inference_timeout_s,
            poll_interval_s=settings.inference_poll_interval_s,
        )
        if not is_confirmed(verdict):
            log_event(
                logger,
                "citizen_observation_unconfirmed",
                observationId=str(observation_id),
                status=verdict["status"],
            )
            raise ApiError(
                422, "not_confirmed",
                "The photo could not be confirmed as a valid report",
            )
```

- [ ] **Step 5: Run the router tests to verify they pass**

Run: `cd services/api && uv run pytest tests/api/test_observations_gate.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Run the full API test suite (no regressions)**

Run: `cd services/api && uv run pytest -q`
Expected: all pass (existing suite + the two new files); no errors.

- [ ] **Step 7: Commit**

```bash
git add services/api/src/citycrawl_api/config.py \
        services/api/src/citycrawl_api/routers/observations.py \
        services/api/tests/api/test_observations_gate.py
git commit -m "feat(api): gate citizen observation on inference confirmation (default off)"
```

---

## Out of scope (documented for the consuming teams)

- **The inference server itself** (non-public): subscribes to the `supabase_realtime`
  publication for `community.inference_jobs` INSERTs with `status='pending'`, atomically
  claims (`update ... set status='processing' where id=$1 and status='pending' returning *`),
  fetches `r2_url`, runs the model per `thinking_mode`, then `update ... set
  response='{"confirmed":<bool>,...}'::jsonb, status='done'` (or `status='error', error=...`).
- **Controller UX** (`services/whatsapp-controller`): on a `422 not_confirmed` from the
  write API, reply to the citizen that the photo could not be confirmed and to resend.
  (Small TS change in `writeApi.ts`/`conversation.ts`; separate task.)
- Per-observation-type confirmation thresholds; durable multi-instance session/dedupe.

## Self-Review

- **Spec coverage:** table + columns (Task 1) ✓; `thinking_mode`/`status` domains (Task 1) ✓;
  Realtime publication + `replica identity full` (Task 1) ✓; RLS deny-by-default + service_role
  grants (Task 1) ✓; atomic claim (Task 1 Step 4 verifies the SQL the inference server will use) ✓;
  `r2_url` + pre-generated `observation_id`, no FK (Task 1) ✓; waiter polls, gates obs creation,
  reuses existing `create_citizen_observation` (Task 3) ✓; ships disabled (Task 3) ✓;
  no `vision.observations` schema change (none planned) ✓. The inference server and controller
  reply are explicitly out of scope (matches spec §"Out of scope / later").
- **Placeholder scan:** none — every step has concrete SQL/Python/commands.
- **Type consistency:** `PgInferenceJobStore`, `enqueue`, `wait_for_result`, `is_confirmed`,
  `object_locator` names identical across Tasks 2 and 3; verdict dict shape
  (`status`/`response`/`error`) consistent in the module, the integration test, and the router fakes.
