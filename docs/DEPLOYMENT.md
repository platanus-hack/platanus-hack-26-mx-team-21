# Deployment — end-to-end runbook

How to stand up the whole CityCrawl stack from scratch and reproduce the live
deployment. Components are independent but have a **dependency order**: Supabase is
the system of record, the Fly API and R2 broker validate Supabase tokens, and the
frontend talks to all three. Deploy in the order below.

```
┌─────────────┐     reads (app_* RPCs)      ┌──────────────────────────┐
│  Frontend   │ ──────────────────────────► │  Supabase (Auth + Postgres) │  ← system of record
│ Cloudflare  │     planning (bearer JWT)   ├──────────────────────────┤
│   Pages     │ ──────────────────────────► │  Fly API  citycrawl-api    │
│ citycrawl.  │     object bytes (bearer)   ├──────────────────────────┤
│    dev      │ ──────────────────────────► │  CF Worker r2-access-broker │ ──► Cloudflare R2
└─────────────┘                             └──────────────────────────┘
```

Live URLs:
- Frontend: `https://citycrawl.pages.dev` (custom domain `https://citycrawl.dev`)
- API: `https://citycrawl-api.fly.dev`
- Broker: `https://r2-access-broker.<account>.workers.dev`
- Supabase: `https://joixzhdpnxqhnuscxsoy.supabase.co` (project ref `joixzhdpnxqhnuscxsoy`)

---

## 0. Prerequisites

| Tool | Used for | Install |
|------|----------|---------|
| `node` ≥ 18 + `npm` | frontend build | nodejs.org |
| `wrangler` | Cloudflare Pages + Workers | `npm i -g wrangler` (or `npx wrangler`) |
| `flyctl` / `fly` | Fly.io API | `brew install flyctl` |
| `supabase` CLI + Docker | local DB / migrations | supabase.com/docs |
| `uv` | API Python env (local dev) | astral.sh/uv |

Accounts: **Cloudflare** (Pages + R2 + Workers + the `citycrawl.dev` zone), **Fly.io**,
**Supabase**, **Anthropic** (LLM draft parsing). Authenticate each CLI:

```bash
wrangler login          # OAuth; needs Pages, Workers, R2 write
fly auth login
supabase login          # only for CLI-driven migrations
```

---

## 1. Supabase — Auth + Postgres (system of record)

The schema lives in `supabase/migrations/`; deterministic test data in `supabase/seed/`.

**Local stack**
```bash
supabase start
supabase db reset                       # applies migrations/ then seed/*.sql
export DBURL="postgresql://postgres:postgres@127.0.0.1:54322/postgres"
psql "$DBURL" -v ON_ERROR_STOP=1 -f supabase/seed/verify.sql
```

**Remote project** — migrations `0001`–`0211` are applied to `joixzhdpnxqhnuscxsoy`
(via the Supabase MCP `apply_migration` / `execute_sql`; the CLI is not installed in
this workspace). See `.superpowers/sdd/progress.md` for the as-run log and
`supabase/SCHEMA.md` / `supabase/STORAGE.md` for the data model.

Grab the values the other components need (Dashboard → Project Settings → API):
- `SUPABASE_URL` = `https://joixzhdpnxqhnuscxsoy.supabase.co`
- `SUPABASE_ANON_KEY` (publishable; safe in the browser, still not committed)
- `DB_URL` (Postgres connection string, for the dataset pipeline)

> The frontend reads live data **only** through `public.app_*` security-definer RPCs
> (auth.uid → tenant). It never queries tables directly.

### Test users tied to a tenant

Seeded dev users (password `citycrawl-dev-2026!`) live in `supabase/seed/20_auth.sql`:
`author.a@citycrawl.test` (analysis_author), `viewer.a@citycrawl.test` (viewer),
`nomember@citycrawl.test` (no membership). Tenant: **CityCrawl CDMX**.

To add another user by hand, insert across all four tables in one transaction:
`auth.users` → `auth.identities` (email provider) → `platform.oidc_subjects`
(`user_id` → auth user) → `platform.tenant_memberships` (`subject_id` → subject,
`role`). See [`docs/runbooks/create-tenant-user.md`](runbooks/create-tenant-user.md).

> ⚠️ **GoTrue gotcha.** When inserting `auth.users` by raw SQL, set the token columns
> (`confirmation_token`, `recovery_token`, `email_change`, `email_change_token_new`,
> `email_change_token_current`, `phone_change`, `phone_change_token`,
> `reauthentication_token`) to `''` — **not NULL**. GoTrue scans them into non-nullable
> Go strings; a NULL makes every login for that user 500 with
> *"Database error querying schema"* (surfaces in the UI as an empty `{}` error).

---

## 2. Cloudflare R2 + access broker Worker

R2 buckets (private): `sweep-video`, `observation-thumbnails`, `tenant-tiles`,
`external-data`. Object bytes are served only through the broker Worker, which
validates the caller's Supabase JWT via `public.app_authorize_object(p_bucket, p_path)`
before streaming. No Supabase Storage, no signed URLs.

```bash
cd services/broker
npx wrangler secret put SUPABASE_ANON_KEY     # paste project anon key
npx wrangler deploy                            # publishes r2-access-broker
# dev: npx wrangler dev --remote               # hits real R2 buckets
```

`wrangler.toml` binds the three media buckets and sets `SUPABASE_URL` as a plain var.
Details + integration test: `services/broker/README.md`. R2 cutover history:
`docs/runbooks/r2-cutover.md`.

---

## 3. Fly.io API — `citycrawl-api`

FastAPI modular monolith (planning, LLM draft parsing, dataset refresh, video stub) on
one Fly Machine. Full runbook (scaling, autostop, rollback, teardown):
`services/api/README.md`.

```bash
cd services/api
fly apps create citycrawl-api          # or: fly launch --no-deploy (reuses fly.toml)
fly config validate

fly secrets set \
  SUPABASE_URL=https://joixzhdpnxqhnuscxsoy.supabase.co \
  SUPABASE_ANON_KEY=... \
  ANTHROPIC_API_KEY=... \
  ANTHROPIC_MODEL=claude-haiku-4-5-20251001 \
  OPERATOR_API_KEY=... \
  ALLOWED_ORIGINS="https://citycrawl.dev,https://www.citycrawl.dev,https://citycrawl.pages.dev,http://localhost:5173,http://127.0.0.1:5173" \
  STORAGE_BACKEND=r2 \
  R2_S3_ENDPOINT=https://<account_id>.r2.cloudflarestorage.com \
  R2_ACCESS_KEY=... R2_SECRET=... EXTERNAL_DATA_BUCKET=external-data \
  DB_URL=postgresql://...

fly deploy
curl -s https://citycrawl-api.fly.dev/health/live      # {"status":"ok"}
```

> ⚠️ **CORS — `ALLOWED_ORIGINS` must list every browser origin the app loads from.**
> It is an **exact-match** allowlist (Starlette `CORSMiddleware`, no wildcards). If you
> open the app from an origin that is not listed, the preflight returns **400 with no
> `access-control-allow-origin`** and the browser fails the request with **"Failed to
> fetch"** (e.g. the Plan button). Because the Pages site is reachable at **both**
> `citycrawl.pages.dev` and `citycrawl.dev`, **both** must be in the list. Re-set and
> redeploy with one command:
> ```bash
> fly secrets set ALLOWED_ORIGINS="https://citycrawl.dev,https://www.citycrawl.dev,https://citycrawl.pages.dev,http://localhost:5173,http://127.0.0.1:5173" -a citycrawl-api
> ```
> Verify a given origin is allowed:
> ```bash
> curl -s -i -X OPTIONS https://citycrawl-api.fly.dev/v1/planning/optimize \
>   -H "Origin: https://citycrawl.pages.dev" \
>   -H "Access-Control-Request-Method: POST" \
>   -H "Access-Control-Request-Headers: authorization,content-type" \
>   | grep -i "^HTTP\|access-control-allow-origin"
> # want: HTTP/2 200  AND  access-control-allow-origin: https://citycrawl.pages.dev
> ```

---

## 4. Frontend — Cloudflare Pages

Vite + React SPA. Env vars are **baked in at build time** (`VITE_*`), so any change to
the API URL or Supabase keys requires a **rebuild + redeploy**. Full detail:
`frontend/README.md`.

```bash
cd frontend
# Production env (committed values are public; anon key is RLS-protected):
#   frontend/.env.production  → VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY, VITE_CITYCRAWL_API_URL
npm install
npm run build                # tsc --noEmit && vite build → dist/

# First time only — create the Pages project:
npx wrangler pages project create citycrawl --production-branch=main

# Deploy:
npx wrangler pages deploy dist --project-name=citycrawl --branch=main
```

`public/_redirects` (`/* /index.html 200`) provides the SPA fallback so deep links don't
404. The deploy prints both a unique `<hash>.citycrawl.pages.dev` URL and the alias
`citycrawl.pages.dev`.

---

## 5. Custom domain — `citycrawl.dev`

The zone is in the same Cloudflare account as Pages, so DNS is created automatically.

**Dashboard:** Workers & Pages → `citycrawl` → **Custom domains** → *Set up a custom
domain* → `citycrawl.dev` → Activate. Repeat for `www.citycrawl.dev` if wanted.

Cloudflare creates the CNAME (flattened at the apex) and provisions the edge cert; status
goes Pending → Active in a minute or two. Verify:
```bash
curl -sI https://citycrawl.dev | head -1     # want: HTTP/2 200
```

> `wrangler` in this version has **no** `pages domain` command — use the dashboard, or the
> REST API: `POST /accounts/{account_id}/pages/projects/citycrawl/domains {"name":"citycrawl.dev"}`
> with a token scoped **Account → Cloudflare Pages → Edit** and **Zone → DNS → Edit**.

---

## Environment-variable matrix

| Variable | Frontend (build) | Fly API (secret) | Broker (secret/var) |
|----------|:---:|:---:|:---:|
| `VITE_SUPABASE_URL` | ✅ | | |
| `VITE_SUPABASE_ANON_KEY` | ✅ | | |
| `VITE_CITYCRAWL_API_URL` = `https://citycrawl-api.fly.dev` | ✅ | | |
| `SUPABASE_URL` | | ✅ | ✅ (var) |
| `SUPABASE_ANON_KEY` | | ✅ | ✅ (secret) |
| `ALLOWED_ORIGINS` | | ✅ | |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | | ✅ | |
| `OPERATOR_API_KEY` | | ✅ | |
| `STORAGE_BACKEND` / `R2_*` / `EXTERNAL_DATA_BUCKET` | | ✅ | |
| `DB_URL` | | ✅ | |

---

## Post-deploy verification checklist

```bash
# 1. Supabase auth works for a tenant user (200 + access_token)
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
  "https://joixzhdpnxqhnuscxsoy.supabase.co/auth/v1/token?grant_type=password" \
  -H "apikey: <ANON_KEY>" -H "Content-Type: application/json" \
  -d '{"email":"<user>","password":"<pw>"}'

# 2. API is up
curl -s https://citycrawl-api.fly.dev/health/live          # {"status":"ok"}

# 3. CORS allows the frontend origin (see §3 verify command) → HTTP 200 + ACAO

# 4. Frontend loads and the Plan button succeeds end-to-end in the browser
```

Symptom → cause quick map:
- **Login fails, error shows `{}`** → manual auth user has NULL token columns (§1 gotcha).
- **Plan button → "Failed to fetch"** → frontend origin missing from `ALLOWED_ORIGINS` (§3).
- **`citycrawl.dev` returns HTTP 000** → custom domain not Active yet (§5).
- **Stale API URL / Supabase key in prod** → frontend not rebuilt after env change (§4).
