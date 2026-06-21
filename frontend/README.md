# CityCrawl web app

Vite + React + Tailwind v4 SPA for the City Priority Map. Reads live data from Supabase
through `public.app_*` RPCs and calls the Fly API (`citycrawl-api`) for planning and
natural-language draft parsing.

Full stack runbook: [`../docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md).

## Local development

```bash
cd frontend
cp .env.example .env          # fill in VITE_SUPABASE_ANON_KEY; point VITE_CITYCRAWL_API_URL at local or Fly
npm install
npm run dev                   # http://localhost:5173
```

Dev login users are seeded by `supabase/seed/*` (password `citycrawl-dev-2026!`); see
`.env.example` and `supabase/seed/README.md`.

## Environment variables

All are `VITE_*`, so they are **baked into the bundle at build time** — changing any of
them requires a **rebuild + redeploy** (see below). They are public values (the anon key
is RLS/JWT-protected), but real keys are never committed.

| Variable | Meaning |
|----------|---------|
| `VITE_SUPABASE_URL` | Supabase project URL |
| `VITE_SUPABASE_ANON_KEY` | Supabase publishable/anon key |
| `VITE_CITYCRAWL_API_URL` | Fly API base — prod `https://citycrawl-api.fly.dev` |

- `.env` — local dev (git-ignored).
- `.env.production` — values used by `vite build` (production mode). Overrides `.env`.

## Build

```bash
npm run build        # tsc --noEmit && vite build  →  dist/
npm run preview      # serve the built dist/ locally
```

## Deploy — Cloudflare Pages

Project: **`citycrawl`** (production branch `main`). `public/_redirects`
(`/* /index.html 200`) gives the SPA its deep-link fallback.

```bash
# First time only:
npx wrangler pages project create citycrawl --production-branch=main

# Every deploy (build first so dist/ reflects current .env.production):
npm run build
npx wrangler pages deploy dist --project-name=citycrawl --branch=main
```

Output: a unique `https://<hash>.citycrawl.pages.dev` and the alias
`https://citycrawl.pages.dev`. Custom domain `citycrawl.dev` is attached via the
Cloudflare dashboard (Workers & Pages → citycrawl → Custom domains) — see
[`../docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md) §5.

> ⚠️ The app is reachable at **both** `citycrawl.pages.dev` and `citycrawl.dev`. The Fly
> API's `ALLOWED_ORIGINS` must include **every** origin you load the app from, or planning
> calls fail with **"Failed to fetch"** (CORS). See `../docs/DEPLOYMENT.md` §3.
