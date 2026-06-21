# Cloudflare Storage + Access-Broker Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move object storage to Cloudflare R2 with Postgres-mediated access, run the external-data pipeline from a Cloudflare Container writing to R2, copy existing objects over with verification, and decommission Supabase Storage — without touching Supabase Postgres/Auth/RLS.

**Architecture:** The authorization decision stays in Postgres: a new `public.app_authorize_object(bucket, path)` RPC reuses the existing `platform.can_view_observation` / `platform.is_member` guards. A thin Python Cloudflare Worker (the **broker**) forwards the user's JWT to that RPC and, on allow, streams bytes from R2 via an R2 binding. The heavy numpy/pyproj pipeline is lifted as-is into a Container; its only code change is a new `r2` fsspec backend. Cutover is a strangler sequence: stand up R2 → copy + verify → flip readers/writers → drop Supabase Storage last.

**Tech Stack:** Cloudflare R2, Cloudflare Workers (Python / Pyodide, `python_workers` flag), Cloudflare Containers (beta) + Cron Triggers, `wrangler`, `rclone`; Supabase Postgres (plpgsql, PostgREST RPC); Python 3.12, fsspec + s3fs, pytest; SQL `do $$ … assert … $$` tests.

## Global Constraints

[Every task's requirements implicitly include this section. Values copied verbatim from `docs/superpowers/specs/2026-06-20-cloudflare-migration-design.md`.]

- **DB stays authoritative.** No migration of Postgres, Auth, or RLS. The browser keeps using supabase-js + the `public` API layer for everything except media/tile bytes.
- **Pointer columns + constraints are untouched:** `recordings.storage_bucket/storage_path`, `observation_thumbnails.storage_bucket/storage_path`, `tenant_tile_sets.storage_bucket/storage_prefix`, `priority.external_signals.source_object_ref`, `priority.rois.source_object_refs`, and every `(storage_bucket, storage_path)` unique constraint.
- **Bucket ids are unchanged** (`external-data`, `sweep-video`, `observation-thumbnails`, `tenant-tiles`) — they become R2 bucket names.
- **Path templates are unchanged:** `raw/{source_id}/{stamp}/…`, `sweeps/{sweep_id}/{recording_id}.mp4`, `observations/{observation_id}/…`, `{tenant_id}/{boundary_version_id}/{data_version}/…`.
- **All buckets private.** No public buckets. Every client read goes through the broker.
- **Authz stays in Postgres** via `app_authorize_object`; never reimplement permission logic at the edge.
- **No secret reaches a client:** no service-role key and no R2 S3 secret in the browser. The broker holds R2 **bindings** (not S3 secrets) and only the Supabase **anon** key.
- **Strangler sequencing:** the decommission migration (Task 7) runs only after copy + cutover are verified.
- **Project ref:** Supabase project `joixzhdpnxqhnuscxsoy` (`https://joixzhdpnxqhnuscxsoy.supabase.co`).

---

## File Structure

**New:**
- `services/external-data/src/external_data/config.py` (modify) — add `r2` backend settings.
- `services/external-data/src/external_data/core/storage.py` (modify) — add `r2` branch to `make_store`.
- `supabase/migrations/0210_r2_access_api.sql` — `app_authorize_object` RPC (additive).
- `supabase/tests/0210_r2_access_api.test.sql` — RPC authorization test.
- `services/broker/wrangler.toml` — broker Worker + R2 bindings.
- `services/broker/src/entry.py` — the broker (authz-forward + R2 binding serve).
- `services/broker/test/integration.sh` — `wrangler dev` + curl integration test.
- `services/broker/README.md` — run/deploy/secret notes.
- `services/external-data/Dockerfile` — Container image for the pipeline.
- `services/external-data/cron/wrangler.toml` — Cron-triggered Worker that runs the Container.
- `services/migration/copy-supabase-to-r2.sh` — one-time bulk copy.
- `services/migration/verify.sql` — pointer reconciliation query.
- `docs/runbooks/r2-cutover.md` — cutover/decommission runbook.
- `supabase/migrations/0211_drop_supabase_storage.sql` — decommission (additive-last).

**Modified at decommission:**
- `supabase/tests/0013_storage.test.sql`, `supabase/tests/0103_external_data_storage.test.sql` — flip assertions to "removed".
- `supabase/STORAGE.md` — rewrite for R2.
- `supabase/config.toml` — drop the now-irrelevant `[storage]` block.

> **Numbering note:** the city-priority-map plan reserves `0200_app_read_api.sql` / `0201_app_analysis_api.sql`. This plan uses `0210`/`0211`. Before creating either file, run `ls supabase/migrations | sort | tail -3` and bump if `0210`/`0211` are already taken.

---

### Task 1: Cloudflare + R2 bootstrap (infrastructure)

Stand up the four R2 buckets and the credentials the later tasks bind to. This is the only click-ops/CLI-IaC task; everything after it is code.

**Files:**
- Create: `services/broker/README.md` (provisioning notes — extended in Task 4)

**Interfaces:**
- Produces: four R2 buckets `external-data`, `sweep-video`, `observation-thumbnails`, `tenant-tiles`; an R2 **S3 API** token (access key id + secret + account endpoint `https://<account_id>.r2.cloudflarestorage.com`) for Containers/copy; `wrangler` authenticated locally.

- [ ] **Step 1: Authenticate wrangler**

Run: `npx wrangler login`
Expected: browser auth completes; `npx wrangler whoami` prints your account id.

- [ ] **Step 2: Create the four private R2 buckets**

```bash
for b in external-data sweep-video observation-thumbnails tenant-tiles; do
  npx wrangler r2 bucket create "$b"
done
```
Expected: `Created bucket "<name>"` four times (or "already exists" if re-run — idempotent enough).

- [ ] **Step 3: Verify buckets exist**

Run: `npx wrangler r2 bucket list`
Expected: all four names listed.

- [ ] **Step 4: Create an R2 S3 API token** (dashboard: R2 → Manage API Tokens → Create, "Object Read & Write", scoped to these buckets). Record the **Access Key ID**, **Secret Access Key**, and the **S3 endpoint** `https://<account_id>.r2.cloudflarestorage.com`.

- [ ] **Step 5: Write provisioning notes**

Create `services/broker/README.md` capturing: bucket names, the S3 endpoint, and that the S3 token is for Containers + the copy job only (Workers use bindings, not this token). Do **not** commit any key value — reference env var names only.

- [ ] **Step 6: Commit**

```bash
git add services/broker/README.md
git commit -m "chore(r2): bootstrap R2 buckets + provisioning notes"
```

---

### Task 2: `r2` storage backend in the external-data pipeline

Add a third `STORAGE_BACKEND` value, `r2`, mirroring the existing `supabase` S3 branch. `s3fs` is already a dependency — no new packages.

**Files:**
- Modify: `services/external-data/src/external_data/config.py`
- Modify: `services/external-data/src/external_data/core/storage.py`
- Test: `services/external-data/tests/test_config.py`, `services/external-data/tests/test_storage.py`

**Interfaces:**
- Consumes: existing `Settings`, `ObjectStore`, `make_store(settings) -> ObjectStore`.
- Produces: `Settings.storage_backend in {"local","supabase","r2"}`; new `Settings` fields `r2_s3_endpoint`, `r2_access_key`, `r2_secret`; `make_store` returns an S3-backed `ObjectStore` rooted at `settings.external_data_bucket` when backend is `r2`.

- [ ] **Step 1: Write the failing config test**

Add to `services/external-data/tests/test_config.py`:
```python
def test_settings_r2_backend(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "r2")
    monkeypatch.setenv("R2_S3_ENDPOINT", "https://acct.r2.cloudflarestorage.com")
    get_settings.cache_clear()
    s = get_settings()
    assert s.storage_backend == "r2"
    assert s.r2_s3_endpoint == "https://acct.r2.cloudflarestorage.com"
    assert s.r2_access_key is None and s.r2_secret is None
    get_settings.cache_clear()
```

- [ ] **Step 2: Run it, verify it fails**

Run: `services/external-data/.venv/bin/pytest services/external-data/tests/test_config.py::test_settings_r2_backend -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'r2_s3_endpoint'`.

- [ ] **Step 3: Add the R2 settings fields**

In `services/external-data/src/external_data/config.py`, change the backend comment and add fields after `supabase_s3_secret`:
```python
    storage_backend: str = "local"            # "local" | "supabase" | "r2"
    local_root: str = ".data"
    supabase_s3_endpoint: str | None = None
    supabase_s3_access_key: str | None = None
    supabase_s3_secret: str | None = None
    r2_s3_endpoint: str | None = None
    r2_access_key: str | None = None
    r2_secret: str | None = None
    external_data_bucket: str = "external-data"
```

- [ ] **Step 4: Run it, verify it passes**

Run: `services/external-data/.venv/bin/pytest services/external-data/tests/test_config.py -v`
Expected: PASS (all config tests).

- [ ] **Step 5: Write the failing storage test**

Add to `services/external-data/tests/test_storage.py`:
```python
def test_r2_store_is_s3_rooted_at_bucket():
    s = make_store(Settings(
        storage_backend="r2",
        r2_s3_endpoint="https://acct.r2.cloudflarestorage.com",
        r2_access_key="k", r2_secret="x",
        external_data_bucket="external-data",
    ))
    assert s.root == "external-data"
    assert "s3" in s.fs.protocol  # s3fs filesystem, no network on construction
```

- [ ] **Step 6: Run it, verify it fails**

Run: `services/external-data/.venv/bin/pytest services/external-data/tests/test_storage.py::test_r2_store_is_s3_rooted_at_bucket -v`
Expected: FAIL — falls through to the `local` branch, `s.root` is `.data`.

- [ ] **Step 7: Add the `r2` branch to `make_store`**

In `services/external-data/src/external_data/core/storage.py`, add before the final `local` fallback in `make_store`:
```python
    if settings.storage_backend == "r2":
        fs = fsspec.filesystem(
            "s3",
            key=settings.r2_access_key,
            secret=settings.r2_secret,
            client_kwargs={"endpoint_url": settings.r2_s3_endpoint},
        )
        return ObjectStore(fs, settings.external_data_bucket)
```

- [ ] **Step 8: Run the full storage + config suite, verify pass**

Run: `services/external-data/.venv/bin/pytest services/external-data/tests/test_storage.py services/external-data/tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 9: Update `.env.example`**

In `services/external-data/.env.example`, add under the Supabase S3 block:
```bash
# --- Cloudflare R2 (STORAGE_BACKEND=r2) ---
R2_S3_ENDPOINT=https://<account_id>.r2.cloudflarestorage.com
R2_ACCESS_KEY=__set_me__
R2_SECRET=__set_me__
# EXTERNAL_DATA_BUCKET stays 'external-data' (now an R2 bucket id)
```

- [ ] **Step 10: Commit**

```bash
git add services/external-data/src/external_data/config.py \
        services/external-data/src/external_data/core/storage.py \
        services/external-data/tests/test_config.py \
        services/external-data/tests/test_storage.py \
        services/external-data/.env.example
git commit -m "feat(external-data): add R2 (s3fs) storage backend"
```

---

### Task 3: `app_authorize_object` RPC (Postgres-mediated R2 access)

The linchpin that replaces Storage-RLS. A `security definer` function that maps `(bucket, path)` → owning row and reuses the existing guards. Additive migration — drops nothing.

**Files:**
- Create: `supabase/migrations/0210_r2_access_api.sql`
- Test: `supabase/tests/0210_r2_access_api.test.sql`

**Interfaces:**
- Consumes: `platform.is_member(uuid, text)`, `platform.can_view_observation(uuid)`, `vision.recordings`, `vision.observations`, `vision.observation_thumbnails`.
- Produces: `public.app_authorize_object(p_bucket text, p_path text) returns boolean`, `execute` granted to `authenticated`, revoked from `public`.

- [ ] **Step 1: Write the failing test**

Create `supabase/tests/0210_r2_access_api.test.sql` (models the seed-dependent style of `0014_integration.test.sql`):
```sql
do $$
declare v_user uuid; v_tenant uuid;
begin
  assert to_regprocedure('public.app_authorize_object(text,text)') is not null,
    'app_authorize_object missing';

  -- resolve the seeded dev user + tenant
  select s.user_id, m.tenant_id into v_user, v_tenant
  from platform.tenant_memberships m
  join platform.oidc_subjects s on s.id = m.subject_id
  limit 1;
  assert v_user is not null and v_tenant is not null, 'seed membership missing';

  -- simulate the caller's JWT (auth.uid() reads this GUC)
  perform set_config('request.jwt.claims', json_build_object('sub', v_user)::text, true);

  -- tenant-tiles: member of the path's tenant -> allowed
  assert public.app_authorize_object('tenant-tiles', v_tenant::text || '/bv/1/0-0.pbf') = true,
    'member should be allowed on own tenant tiles';
  -- tenant-tiles: a random tenant -> denied
  assert public.app_authorize_object('tenant-tiles', gen_random_uuid()::text || '/bv/1/0-0.pbf') = false,
    'non-member tenant must be denied';
  -- external-data is never client-facing
  assert public.app_authorize_object('external-data', 'raw/x/y.csv') = false,
    'external-data must be denied';
  -- malformed paths -> denied, never error
  assert public.app_authorize_object('sweep-video', 'sweeps/x/not-a-uuid.mp4') = false,
    'malformed sweep path must be denied';
  assert public.app_authorize_object('tenant-tiles', '') = false, 'empty path must be denied';
end $$;
```

- [ ] **Step 2: Run it, verify it fails**

Run: `npx supabase db reset` then `psql "$DB_URL" -f supabase/tests/0210_r2_access_api.test.sql`
(or apply via the Supabase MCP `execute_sql`). Expected: FAIL — `app_authorize_object missing`.

- [ ] **Step 3: Write the migration**

Create `supabase/migrations/0210_r2_access_api.sql`:
```sql
-- Postgres-mediated authorization for R2-served objects. The broker Worker forwards
-- the user's JWT to this RPC; it reuses platform.can_view_observation / is_member.
-- Boolean only — no bytes. external-data is server-side and always denied here.
create or replace function public.app_authorize_object(p_bucket text, p_path text)
returns boolean
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_part text;
  v_id   uuid;
  uuid_re constant text := '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';
begin
  if coalesce(p_path, '') = '' then
    return false;
  end if;

  if p_bucket = 'tenant-tiles' then
    -- {tenant_id}/{boundary_version_id}/{data_version}/...
    v_part := split_part(p_path, '/', 1);
    if v_part !~* uuid_re then return false; end if;
    return platform.is_member(v_part::uuid, 'viewer');

  elsif p_bucket = 'observation-thumbnails' then
    -- observations/{observation_id}/...
    if split_part(p_path, '/', 1) <> 'observations' then return false; end if;
    v_part := split_part(p_path, '/', 2);
    if v_part !~* uuid_re then return false; end if;
    v_id := v_part::uuid;
    if not exists (
      select 1 from vision.observation_thumbnails t
      where t.observation_id = v_id
        and t.storage_bucket = 'observation-thumbnails'
        and t.storage_path = p_path
    ) then
      return false;
    end if;
    return platform.can_view_observation(v_id);

  elsif p_bucket = 'sweep-video' then
    -- sweeps/{sweep_id}/{recording_id}.mp4
    if split_part(p_path, '/', 1) <> 'sweeps' then return false; end if;
    v_part := split_part(split_part(p_path, '/', 3), '.', 1);  -- strip extension
    if v_part !~* uuid_re then return false; end if;
    v_id := v_part::uuid;
    if not exists (
      select 1 from vision.recordings r
      where r.id = v_id
        and r.storage_bucket = 'sweep-video'
        and r.storage_path = p_path
    ) then
      return false;
    end if;
    -- parity with the documented signed-URL flow: viewable iff some in-boundary,
    -- tenant-member observation references this recording.
    return exists (
      select 1 from vision.observations o
      where o.recording_id = v_id
        and platform.can_view_observation(o.id)
    );

  else
    return false;  -- external-data and anything unrecognized
  end if;
end;
$$;

revoke all on function public.app_authorize_object(text, text) from public;
grant execute on function public.app_authorize_object(text, text) to authenticated;
```

- [ ] **Step 4: Apply and run the test, verify it passes**

Run: `npx supabase db reset` (re-applies migrations + seed), then `psql "$DB_URL" -f supabase/tests/0210_r2_access_api.test.sql`
Expected: PASS (no assertion raised). Also re-run `supabase/tests/0013_storage.test.sql` and confirm it still passes (this task drops nothing).

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/0210_r2_access_api.sql supabase/tests/0210_r2_access_api.test.sql
git commit -m "feat(db): app_authorize_object RPC for Postgres-mediated R2 access"
```

---

### Task 4: Broker Worker (Python) — authz-forward + R2 binding serve

The client-facing path. `GET /api/r2/object?bucket=<id>&path=<path>` with the user's `Authorization: Bearer`. Validates via the Task 3 RPC, then streams from R2.

**Files:**
- Create: `services/broker/wrangler.toml`
- Create: `services/broker/src/entry.py`
- Create: `services/broker/test/integration.sh`
- Modify: `services/broker/README.md`

**Interfaces:**
- Consumes: `public.app_authorize_object` (Task 3); R2 buckets (Task 1).
- Produces: HTTP route `GET /api/r2/object?bucket&path` → `200` (member + object exists, streamed with `Content-Type`/`Cache-Control`, `Range`→`206`), `403` (authz denied), `404` (authz ok, object absent), `400` (bad/unknown bucket), `401` (no bearer).

> **Validation is the integration test (`wrangler dev` + curl)** — unit-testing Pyodide interop is unproductive. **Fallback (spec §7):** if R2/fetch interop is unstable in your `wrangler` version, port this same file to TypeScript; the route contract and the `app_authorize_object` call are byte-for-byte identical.

- [ ] **Step 1: Write the wrangler config**

Create `services/broker/wrangler.toml`:
```toml
name = "r2-access-broker"
main = "src/entry.py"
compatibility_date = "2025-06-01"
compatibility_flags = ["python_workers"]

[[r2_buckets]]
binding = "SWEEP_VIDEO"
bucket_name = "sweep-video"

[[r2_buckets]]
binding = "OBSERVATION_THUMBNAILS"
bucket_name = "observation-thumbnails"

[[r2_buckets]]
binding = "TENANT_TILES"
bucket_name = "tenant-tiles"

[vars]
SUPABASE_URL = "https://joixzhdpnxqhnuscxsoy.supabase.co"
# SUPABASE_ANON_KEY is a secret: npx wrangler secret put SUPABASE_ANON_KEY
```

- [ ] **Step 2: Write the broker**

Create `services/broker/src/entry.py`:
```python
from js import fetch, Response, Headers, URL
from pyodide.ffi import to_js
import json

BINDINGS = {
    "sweep-video": "SWEEP_VIDEO",
    "observation-thumbnails": "OBSERVATION_THUMBNAILS",
    "tenant-tiles": "TENANT_TILES",
}
CONTENT_TYPE = {
    "sweep-video": "video/mp4",
    "observation-thumbnails": "image/jpeg",
    "tenant-tiles": "application/octet-stream",
}

def _json_opts(method, headers, body):
    return to_js({"method": method, "headers": headers, "body": body},
                 dict_converter=lambda kvs: {k: v for k, v in kvs})

async def _authorized(env, bearer, bucket, path):
    url = f"{env.SUPABASE_URL}/rest/v1/rpc/app_authorize_object"
    headers = {"apikey": env.SUPABASE_ANON_KEY, "Authorization": bearer,
               "Content-Type": "application/json"}
    body = json.dumps({"p_bucket": bucket, "p_path": path})
    resp = await fetch(url, _json_opts("POST", headers, body))
    if not resp.ok:
        return False
    text = (await resp.text()).strip()
    return text == "true"

async def on_fetch(request, env):
    u = URL.new(request.url)
    if u.pathname != "/api/r2/object":
        return Response.new("Not found", status=404)

    bucket = u.searchParams.get("bucket")
    path = u.searchParams.get("path")
    if bucket not in BINDINGS or not path:
        return Response.new("Bad request", status=400)

    bearer = request.headers.get("Authorization")
    if not bearer:
        return Response.new("Unauthorized", status=401)

    if not await _authorized(env, bearer, bucket, path):
        return Response.new("Forbidden", status=403)

    binding = getattr(env, BINDINGS[bucket])
    rng = request.headers.get("Range")
    if rng:
        obj = await binding.get(path, to_js({"range": {"suffix": None}}))  # see Step 5
    else:
        obj = await binding.get(path)
    if obj is None:
        return Response.new("Not found", status=404)

    out = Headers.new()
    out.set("Content-Type", CONTENT_TYPE[bucket])
    out.set("Cache-Control", "private, max-age=60")
    return Response.new(obj.body, to_js({"status": 200, "headers": out},
                                        dict_converter=lambda kvs: {k: v for k, v in kvs}))
```
(Range is refined in Step 5; the base path serves whole objects with `200`.)

- [ ] **Step 3: Set the secret and start the dev server**

```bash
cd services/broker
npx wrangler secret put SUPABASE_ANON_KEY   # paste the project anon key
npx wrangler dev --remote                    # --remote so R2 bindings hit real buckets
```
Expected: dev server on `http://localhost:8787`.

- [ ] **Step 4: Write + run the integration test**

Create `services/broker/test/integration.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
BASE="${BROKER_URL:-http://localhost:8787}"
# Mint a member JWT for the seeded dev user.
TOK=$(curl -s "$SUPABASE_URL/auth/v1/token?grant_type=password" \
  -H "apikey: $SUPABASE_ANON_KEY" -H "Content-Type: application/json" \
  -d "{\"email\":\"$BROKER_TEST_EMAIL\",\"password\":\"$BROKER_TEST_PASSWORD\"}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

code () { curl -s -o /dev/null -w "%{http_code}" "$@"; }

# no bearer -> 401
[ "$(code "$BASE/api/r2/object?bucket=tenant-tiles&path=$TENANT_ID/bv/1/0.pbf")" = "401" ]
# unknown bucket -> 400
[ "$(code -H "Authorization: Bearer $TOK" "$BASE/api/r2/object?bucket=nope&path=x")" = "400" ]
# member + own tenant tiles, object absent -> 404 (authz PASSED)
[ "$(code -H "Authorization: Bearer $TOK" "$BASE/api/r2/object?bucket=tenant-tiles&path=$TENANT_ID/bv/1/0.pbf")" = "404" ]
# member + a foreign tenant -> 403 (authz DENIED)
[ "$(code -H "Authorization: Bearer $TOK" "$BASE/api/r2/object?bucket=tenant-tiles&path=00000000-0000-0000-0000-000000000000/bv/1/0.pbf")" = "403" ]
echo "broker integration OK"
```
Run: `chmod +x services/broker/test/integration.sh && SUPABASE_URL=... SUPABASE_ANON_KEY=... TENANT_ID=... BROKER_TEST_EMAIL=... BROKER_TEST_PASSWORD=... services/broker/test/integration.sh`
Expected: prints `broker integration OK` (403 vs 404 proves authz works without needing real objects).

- [ ] **Step 5: Add Range (206) support**

Replace the Range branch in `entry.py` with a real byte-range read and partial response:
```python
    rng = request.headers.get("Range")
    if rng and rng.startswith("bytes="):
        start_s, _, end_s = rng[len("bytes="):].partition("-")
        offset = int(start_s) if start_s else 0
        opts = {"range": {"offset": offset}} if not end_s else \
               {"range": {"offset": offset, "length": int(end_s) - offset + 1}}
        obj = await binding.get(path, to_js(opts, dict_converter=lambda kvs: {k: v for k, v in kvs}))
        if obj is None:
            return Response.new("Not found", status=404)
        out = Headers.new()
        out.set("Content-Type", CONTENT_TYPE[bucket])
        out.set("Accept-Ranges", "bytes")
        total = obj.size
        last = offset + (obj.range.length if hasattr(obj.range, "length") else total - offset) - 1
        out.set("Content-Range", f"bytes {offset}-{last}/{total}")
        return Response.new(obj.body, to_js({"status": 206, "headers": out},
                                            dict_converter=lambda kvs: {k: v for k, v in kvs}))
```
Run: `curl -s -D- -o /dev/null -H "Authorization: Bearer $TOK" -H "Range: bytes=0-1023" "$BASE/api/r2/object?bucket=sweep-video&path=sweeps/<sweep>/<rec>.mp4"`
Expected (once a real recording object exists): `HTTP/… 206`, `Content-Range: bytes 0-1023/<total>`. Until objects exist, a member request to a real-but-absent path returns `404` — acceptable for this step.

- [ ] **Step 6: Document run/deploy in README and commit**

Append run/deploy/secret steps to `services/broker/README.md`, then:
```bash
git add services/broker/
git commit -m "feat(broker): Python R2 access-broker Worker (authz-forward + binding serve)"
```

---

### Task 5: Containerize the external-data pipeline + Cron trigger

Lift the pipeline into a Container that writes to R2 (`STORAGE_BACKEND=r2`), triggered on a schedule.

**Files:**
- Create: `services/external-data/Dockerfile`
- Create: `services/external-data/cron/wrangler.toml`
- Modify: `services/external-data/README.md` (add Container run notes)

**Interfaces:**
- Consumes: the `r2` backend (Task 2); R2 S3 token + endpoint (Task 1); Supabase `DB_URL`.
- Produces: image `external-data:r2` whose `external-data` CLI writes raw/staging to R2; a Cron-triggered Worker that runs it.

> **Beta-surface fallback (spec §7):** if Cloudflare Containers are unavailable to you, the **same image** runs unchanged as a scheduled GitHub Actions job (or any container host) — the only Cloudflare-specific part is the trigger, not the code.

- [ ] **Step 1: Write the Dockerfile**

Create `services/external-data/Dockerfile`:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
ENV STORAGE_BACKEND=r2
ENTRYPOINT ["external-data"]
CMD ["--help"]
```

- [ ] **Step 2: Build the image, verify success**

Run: `docker build -t external-data:r2 services/external-data`
Expected: build succeeds (pyproj/numpy/shapely/psycopg manylinux wheels resolve).

- [ ] **Step 3: Smoke-run the CLI in the container**

Run: `docker run --rm external-data:r2 --help`
Expected: the typer help text (verbs `extract`, `roi-compute`, `load`, …) prints.

- [ ] **Step 4: Verify a real R2 write end-to-end**

```bash
docker run --rm \
  -e STORAGE_BACKEND=r2 \
  -e R2_S3_ENDPOINT="$R2_S3_ENDPOINT" -e R2_ACCESS_KEY="$R2_ACCESS_KEY" -e R2_SECRET="$R2_SECRET" \
  -e EXTERNAL_DATA_BUCKET=external-data -e DB_URL="$DB_URL" \
  external-data:r2 extract --source <one_small_source_id>
npx wrangler r2 object get external-data/staging/<one_small_source_id>/signals.jsonl --file /tmp/out.jsonl
```
Expected: the object downloads; `/tmp/out.jsonl` is non-empty (proves the container wrote to R2).

- [ ] **Step 5: Add the Cron-trigger Worker config**

Create `services/external-data/cron/wrangler.toml`:
```toml
name = "external-data-cron"
main = "src/scheduler.py"          # thin Worker that invokes the Container
compatibility_date = "2025-06-01"
compatibility_flags = ["python_workers"]

[triggers]
crons = ["0 6 * * *"]              # daily 06:00 UTC

[[containers]]
class_name = "PipelineRunner"      # Durable Object that owns the container instance
image = "../Dockerfile"
```
Document in `services/external-data/README.md` that deploying the Container is `npx wrangler deploy` from `services/external-data/cron/`, and the container env (R2 + DB) is set via `npx wrangler secret put`. (The `scheduler.py` Worker + `PipelineRunner` DO are minimal glue per current Cloudflare Containers docs; keep it to "on cron, run `external-data extract && external-data roi-compute --export && external-data load`".)

- [ ] **Step 6: Commit**

```bash
git add services/external-data/Dockerfile services/external-data/cron/ services/external-data/README.md
git commit -m "feat(external-data): Container image + Cron trigger writing to R2"
```

---

### Task 6: One-time bulk copy + verification runbook

Copy existing objects from Supabase Storage (S3 endpoint) to R2, then reconcile against DB pointers before any cutover.

**Files:**
- Create: `services/migration/copy-supabase-to-r2.sh`
- Create: `services/migration/verify.sql`
- Create: `docs/runbooks/r2-cutover.md`

**Interfaces:**
- Consumes: Supabase S3 creds (`SUPABASE_S3_*`), R2 S3 creds (Task 1), `DB_URL`.
- Produces: every Supabase object present in R2 with matching checksums; `verify.sql` confirms no `source_object_ref` is orphaned.

- [ ] **Step 1: Write the copy script**

Create `services/migration/copy-supabase-to-r2.sh` (rclone with two S3 remotes configured via env — see the runbook for the `rclone.conf` template):
```bash
#!/usr/bin/env bash
set -euo pipefail
BUCKETS=(external-data sweep-video observation-thumbnails tenant-tiles)
for b in "${BUCKETS[@]}"; do
  echo "== copying $b =="
  rclone copy "supabase:$b" "r2:$b" --checksum --transfers 8 --progress
done
for b in "${BUCKETS[@]}"; do
  echo "== verifying $b =="
  rclone check "supabase:$b" "r2:$b" --checksum   # exits non-zero on any difference
done
echo "copy + check complete"
```

- [ ] **Step 2: Dry-run the copy on the smallest bucket**

Run: `rclone copy supabase:external-data r2:external-data --checksum --dry-run`
Expected: lists objects that *would* copy; no errors connecting to either remote.

- [ ] **Step 3: Run the full copy + check**

Run: `chmod +x services/migration/copy-supabase-to-r2.sh && services/migration/copy-supabase-to-r2.sh`
Expected: ends with `copy + check complete`; every `rclone check` exits 0 (no differences).

- [ ] **Step 4: Write + run the pointer reconciliation**

Create `services/migration/verify.sql`:
```sql
-- Every external_signals.source_object_ref should resolve to an object now in R2.
-- Emits the refs to compare against `rclone lsf r2:external-data` output.
select distinct source_object_ref
from priority.external_signals
where source_object_ref is not null
order by 1;
```
Run: `psql "$DB_URL" -Atf services/migration/verify.sql > /tmp/refs.txt && rclone lsf --recursive r2:external-data > /tmp/r2.txt`
Then eyeball/diff that each ref's object path appears in `/tmp/r2.txt`. Expected: no missing refs.

- [ ] **Step 5: Write the cutover runbook**

Create `docs/runbooks/r2-cutover.md` documenting, in order: the `rclone.conf` template (both remotes), run the copy script, run reconciliation, flip `STORAGE_BACKEND=r2` (pipeline) + deploy broker + point the SPA at `/api/r2/object`, verify in-app, **then** apply Task 7. Include rollback (Supabase Storage stays intact until Task 7).

- [ ] **Step 6: Commit**

```bash
git add services/migration/ docs/runbooks/r2-cutover.md
git commit -m "chore(migration): Supabase->R2 bulk copy + verification runbook"
```

---

### Task 7: Cutover + decommission Supabase Storage

Run only after Task 6 verified the copy and the broker serves in production. Removes the now-inert Supabase Storage buckets/policy and rewrites the docs/tests.

**Files:**
- Create: `supabase/migrations/0211_drop_supabase_storage.sql`
- Modify: `supabase/tests/0013_storage.test.sql`
- Modify: `supabase/tests/0103_external_data_storage.test.sql`
- Modify: `supabase/STORAGE.md`
- Modify: `supabase/config.toml`

**Interfaces:**
- Consumes: a verified R2 copy (Task 6) and a live broker (Task 4).
- Produces: no `storage.buckets` rows and no `tenant_tiles_read` policy for the four ids; DB pointer columns unchanged.

- [ ] **Step 1: Write the decommission migration**

Create `supabase/migrations/0211_drop_supabase_storage.sql`:
```sql
-- Supabase Storage decommissioned; R2 (via app_authorize_object + the broker Worker)
-- is authoritative. Buckets are now R2 IaC, not storage.buckets rows. Pointer columns
-- (recordings.*, observation_thumbnails.*, tenant_tile_sets.*, external_signals.*) stay.
drop policy if exists tenant_tiles_read on storage.objects;

delete from storage.objects
 where bucket_id in ('external-data','sweep-video','observation-thumbnails','tenant-tiles');

delete from storage.buckets
 where id in ('external-data','sweep-video','observation-thumbnails','tenant-tiles');
```

- [ ] **Step 2: Flip the storage tests to assert removal**

Replace the body of `supabase/tests/0013_storage.test.sql` with:
```sql
do $$
begin
  -- Supabase Storage decommissioned (R2 is authoritative); buckets + policy must be gone.
  assert not exists (select 1 from storage.buckets
    where id in ('sweep-video','observation-thumbnails','tenant-tiles')),
    'supabase storage buckets should be removed';
  assert not exists (select 1 from pg_policies where schemaname='storage' and tablename='objects'
    and policyname='tenant_tiles_read'), 'tenant_tiles_read should be removed';
  -- pointer columns still exist (R2 paths live here)
  assert exists (select 1 from pg_attribute
    where attrelid='vision.recordings'::regclass and attname='storage_path'),
    'recordings.storage_path must remain';
end $$;
```
Replace the body of `supabase/tests/0103_external_data_storage.test.sql` with:
```sql
do $$
begin
  assert not exists (select 1 from storage.buckets where id='external-data'),
    'external-data supabase bucket should be removed';
  assert exists (select 1 from pg_attribute
    where attrelid='priority.external_signals'::regclass and attname='source_object_ref'),
    'external_signals.source_object_ref must remain';
end $$;
```

- [ ] **Step 3: Apply and run the full SQL suite, verify pass**

Run: `npx supabase db reset` then run every `supabase/tests/*.test.sql` (the project's existing test runner / loop of `psql -f`).
Expected: all pass — including the rewritten `0013` / `0103` and the unchanged `0210`.

- [ ] **Step 4: Rewrite `STORAGE.md` for R2**

Rewrite `supabase/STORAGE.md` so it documents: buckets are **R2** (IaC via `services/broker/wrangler.toml`, not SQL); access is via the **broker Worker** + `app_authorize_object` (replacing the signed-URL + path-prefix-RLS sections); Containers write via S3, the broker reads via binding; pointer columns + path templates unchanged. Remove the "raise the global Storage size limit" pending item (no longer applies).

- [ ] **Step 5: Drop the obsolete local-storage config**

In `supabase/config.toml`, remove the `[storage]` block (`file_size_limit = "5GiB"`) — it only governed the local Supabase Storage stack we no longer use.

- [ ] **Step 6: Commit**

```bash
git add supabase/migrations/0211_drop_supabase_storage.sql \
        supabase/tests/0013_storage.test.sql supabase/tests/0103_external_data_storage.test.sql \
        supabase/STORAGE.md supabase/config.toml
git commit -m "feat(db): decommission Supabase Storage; R2 is authoritative"
```

---

## Follow-on plans (dependency-gated — NOT in this plan)

These integrate with components that do not yet exist in the repo, so they get their own spec→plan→implement cycle once their dependency lands. Their **contract** with this migration:

1. **SPA hosting on Cloudflare Workers Static Assets** — *blocked on `apps/web` existing* (see `docs/superpowers/plans/2026-06-20-city-priority-map-application.md`). When built: a wrangler static-assets config serves `apps/web/dist`; the SPA fetches protected media/tiles from same-origin `GET /api/r2/object?bucket=&path=` (the Task 4 route) instead of Supabase signed URLs. No new broker work — the contract is already shipped here.

2. **Vision/tile worker as a Container** — *blocked on `services/worker` having code* (today only `.env.example`). When built: a Container that ingests recordings, generates thumbnails, and builds tenant tiles, writing to the `sweep-video` / `observation-thumbnails` / `tenant-tiles` R2 buckets via S3 using the **same path templates** and updating each owning row's `status`. Reads are already served by the Task 4 broker via `app_authorize_object`.

---

## Self-Review

**Spec coverage** (against `2026-06-20-cloudflare-migration-design.md`):
- §3.A R2 buckets (IaC) → Task 1. ✓
- §3.B broker Worker (authz-forward, binding serve, Range) → Task 4. ✓
- §3.C `app_authorize_object` RPC + drop Supabase Storage → Task 3 (add) + Task 7 (drop). ✓
- §3.D external-data → Container + `r2` backend → Task 2 (backend) + Task 5 (container/cron). ✓
- §3.E vision/tile worker → Follow-on #2 (dependency-gated, contract stated). ✓ (intentionally deferred)
- §3.F SPA hosting → Follow-on #1 (dependency-gated, contract stated). ✓ (intentionally deferred)
- §4 data copy + phased strangler → Task 6 (copy/verify) + Task 7 (decommission last). ✓
- §5 config/secrets → Task 2 (`.env.example`), Task 4 (`wrangler.toml` vars/secret). ✓
- §6 trade-offs (binding proxy, Postgres authz, strangler) → reflected in Tasks 3/4/6/7. ✓
- §8 definition of done (round-trip member 200 vs non-member 403) → Task 4 integration test (403 vs 404) + Task 3 SQL test. ✓

**Placeholder scan:** no "TBD/handle errors/similar to Task N". The two intentionally-deferred items are explicitly dependency-gated with contracts, not placeholders. The `scheduler.py`/`PipelineRunner` glue in Task 5 is described by its exact command sequence; treat its minimal body as current-Cloudflare-Containers-docs boilerplate.

**Type consistency:** RPC signature `public.app_authorize_object(text, text) -> boolean` is identical in Task 3 (def), Task 3 test, Task 4 (`{"p_bucket","p_path"}` body), and Task 7. Binding names (`SWEEP_VIDEO`/`OBSERVATION_THUMBNAILS`/`TENANT_TILES`) and bucket ids match across Tasks 1/4/5/6/7. `Settings` fields (`r2_s3_endpoint`/`r2_access_key`/`r2_secret`) match across config, test, and `.env.example`.
