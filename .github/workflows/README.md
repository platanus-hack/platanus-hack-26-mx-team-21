# CI / CD

Per-component workflows, each **path-filtered** so only what changed runs. They fire on
pull requests and on pushes to `main`.

| Workflow | Trigger paths | CI | CD |
|---|---|---|---|
| `frontend.yml` | `frontend/**` | bun typecheck + build | — |
| `api.yml` | `services/api/**` | pytest (py 3.11) | Fly deploy `citycrawl-api` on `main` |
| `controller.yml` | `services/whatsapp-controller/**` | tsc typecheck + offline smoke test | Fly deploy `citycrawl-whatsapp` on `main` |
| `supabase.yml` | `supabase/**` | `supabase start` (migrations + seed) → run `supabase/tests/*.test.sql` | — |
| `broker.yml` | `services/broker/**` | py_compile worker + validate `wrangler.toml` | — |

## Deploy (CD)

`api` and `controller` auto-deploy to Fly on merge to `main`. Deploy jobs are **guarded**:
if the `FLY_API_TOKEN` secret is absent they skip (green), so nothing breaks before it's set.

### Required secret

```bash
fly tokens create deploy -a citycrawl-api          # or an org-wide deploy token covering both apps
gh secret set FLY_API_TOKEN --body "<token>"        # repo-level secret
```

### One-time app creation

The deploy assumes both Fly apps exist. `citycrawl-api` already does; create the controller once:

```bash
fly apps create citycrawl-whatsapp
fly secrets set -a citycrawl-whatsapp \
  KAPSO_API_KEY=… KAPSO_PHONE_NUMBER_ID=597907523413541 WRITE_API_TOKEN=<api OPERATOR_API_KEY>
```

## Not yet wired (future)

- **Frontend deploy** — no host chosen yet (Cloudflare Pages / Fly static / etc.).
- **Broker deploy** — `wrangler deploy` needs `CLOUDFLARE_API_TOKEN`; currently CI only.
- **Supabase migration push** — applying migrations to the remote project needs the DB
  password; CI validates them locally only.
