# Seed data

Deterministic test dataset for the "CityCrawl" City Priority Map app. Files apply in filename
order (wired via `config.toml` `[db.seed].sql_paths`):

```
00_catalog → 10_geo → 20_auth → 30_observations → 40_priority → 50_analysis → 60_rois → 99_finalize
```

All fixtures use fixed UUIDs and are idempotent (`on conflict do nothing`); no `UPDATE`s
(lifecycle states are inserted in final form, since immutability triggers fire BEFORE UPDATE).

## Apply

**Local** (requires the supabase CLI + Docker):
```bash
supabase start
supabase db reset                       # migrations/ then seed/*.sql
export DBURL="postgresql://postgres:postgres@127.0.0.1:54322/postgres"
psql "$DBURL" -v ON_ERROR_STOP=1 -f supabase/seed/verify.sql
```

**Remote** (this repo's deployed project, applied via Supabase MCP — the CLI is not installed here):
each fixture's SQL is applied with MCP `execute_sql` in the same order, then `verify.sql` is run
the same way. See `.superpowers/sdd/progress.md` for the as-run log.

## Dev login users (password for all: `citycrawl-dev-2026!`)

| email | role | purpose |
|---|---|---|
| `author.a@citycrawl.test` | analysis_author | full app |
| `viewer.a@citycrawl.test` | viewer | read-only |
| `nomember@citycrawl.test` | (none) | no-membership empty state |

Tenant: **CityCrawl CDMX**. Active boundary = 6 alcaldías (Cuauhtémoc, Iztapalapa, Coyoacán, GAM,
Álvaro Obregón, V. Carranza); **Tlalpan is excluded** so its ~10 observations test the geo-clip.

## Notes
- **Volume** is tunable: `generate_series(1,120)` in `30_observations.sql`.
- **ROIs**: on the remote deployment the real external-data pipeline ROIs are used (the app plan
  §4.5 prefers them); `60_rois.sql` is a synthetic LOCAL-reset fallback and is not applied to remote.
- **Access model**: the browser only reads through the `public` security-definer API (migrations
  0200/0201, owned by the app team). `verify.sql` therefore checks the access path those functions
  use (`is_member` / `current_subject_id` / `tenant_visible_observations`), not direct table SELECT
  as `authenticated` (which is correctly denied — no USAGE on the custom schemas).
