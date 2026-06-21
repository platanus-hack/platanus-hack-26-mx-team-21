# External-Dataset ROIs as Per-Dimension Map Layers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the app's risk zones a real, per-dimension feature — bulk-load the external-data pipeline's ROIs for the four native-lat/long dimensions into remote Postgres, and turn the single combined "Zonas de riesgo" toggle into a grouped per-dimension layer control with per-dimension map styling and an ROI detail popup.

**Architecture:** Two workstreams sharing one contract (the `risk_dimension` values + the `public.app_*` RPC shapes). **WS-A (data)** runs `services/external-data` CLI against remote Postgres. **WS-B (frontend/API)** adds a migration (`0212`), a dimension-presentation module, lazy per-dimension fetch in `MapPage`, a grouped `LayersPanel` section, and per-dimension `MapCanvas` styling. WS-B is built/tested against today's 5-ROI crash sample and lights up fully as WS-A lands.

**Tech Stack:** Vite + React 18 + TypeScript, plain inline-styled + shadcn components, react-leaflet/leaflet, `@supabase/supabase-js`, **bun** (package manager). Python 3.12 pipeline (`services/external-data`, `typer` CLI). Supabase Postgres + PostGIS (remote `joixzhdpnxqhnuscxsoy`).

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-06-21-external-roi-layers-design.md` — authoritative.
- **No client-side priority math.** The pipeline emits `risk_score` per ROI; the app only visualizes it (memory `no-client-priority-heuristics`). Fill opacity is a *display* scaling of `risk_score`, not a computed priority.
- **Browser never touches custom schemas.** All reads go through `public.app_*` security-definer RPCs (memory `city-priority-map-architecture`). New functions follow the `0200` conventions: `security definer`, `set search_path = extensions, public`, tenant-clipped via `public._app_tenant()` + `geo.tenant_boundary_versions`, `grant execute … to authenticated`.
- **UI is Spanish.** Dimension labels: `crash`→"Choques", `flooding`→"Inundación", `road_surface`→"Bacheo", `crime`→"Crimen", `violation`→"Infracciones" (deferred/disabled).
- **Dimension colors (verbatim):** crash `#e5484d`, flooding `#2f64e6`, road_surface `#f5a623`, crime `#7c3aed`, violation `#0f9b8e`.
- **Verification bar (this project has NO JS test runner — `working-style-fast-build`):** code changes are verified by `bun run typecheck`, `bun run build`, and headless-Chrome screenshots (`scripts/shot.mjs`); DB/RPC changes by SQL assertion files run via the Supabase MCP **and** a live authenticated RPC smoke (`scripts/verify-roi-rpc.mjs`). "Test" steps below mean exactly these — do not scaffold vitest/playwright.
- **Dev login:** `author.a@vialia.test` / `vialia-dev-2026!`. Env vars: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` (in `frontend/.env`).
- **Commands run from `frontend/`** unless a path says otherwise. Migrations applied via Supabase MCP `apply_migration`; types regenerated via MCP `generate_typescript_types`.
- **WS-A prerequisite:** remote Postgres password as `DB_URL` + live CKAN reachability. If unavailable, WS-A tasks are skipped and WS-B runs against the existing 5-ROI sample (feature still works, sparsely).

---

## File Structure

**WS-A (data):**
- Modify (only if a header drifted): `services/external-data/src/external_data/registry/sources.yaml` — per-source column maps.
- No other code changes expected; WS-A is operational (CLI runs + verification SQL).

**WS-B (frontend/API):**
- Create: `supabase/migrations/0212_app_roi_layers.sql` — dimension-filtered/limited `app_current_rois` + new `app_roi_dimension_counts`.
- Create: `supabase/tests/0212_app_roi_layers.test.sql` — pg_proc signature assertions.
- Modify: `packages/db-types/database.ts` — regenerated types.
- Create: `frontend/src/lib/dimensions.ts` — per-dimension color/label presentation (single source of truth).
- Modify: `frontend/src/lib/types.ts` — `Roi.signalCount`, new `DimensionCount`.
- Modify: `frontend/src/lib/api.ts` — `getRois(dimensions?, limit?)`, `getRoiDimensionCounts()`.
- Create: `frontend/scripts/verify-roi-rpc.mjs` — live authenticated RPC smoke.
- Modify: `frontend/src/pages/MapPage.tsx` — dimension state, lazy fetch + cache, wiring.
- Modify: `frontend/src/components/LayersPanel.tsx` — grouped master + per-dimension sub-toggles.
- Modify: `frontend/src/components/MapCanvas.tsx` — per-dimension styling, risk-scaled fill, ROI popup.

---

## WS-A — Data load (operational; needs `DB_URL` + live CKAN)

> Each WS-A task: (1) confirm the source CSV headers resolve against `sources.yaml`; (2) `extract`; (3) `load-db`; (4) `roi-compute --dimension <d>`; (5) verify with a counts query via the Supabase MCP. Per-source isolation: if a source is unreachable or its headers don't resolve, **skip it, log it, continue** — every other dimension still lands. Run from `services/external-data` with the venv active and env exported.

### Task A1: Preflight — confirm the pipeline can reach DB + sources

**Files:** none (operational).

- [ ] **Step 1: Activate env and list sources**

```bash
cd services/external-data
. .venv/bin/activate
export STORAGE_BACKEND=local LOCAL_ROOT=.data \
       DB_URL="postgresql://postgres:<PASSWORD>@db.joixzhdpnxqhnuscxsoy.supabase.co:5432/postgres"
external-data status
```
Expected: lists 9 sources across 5 dimensions; DB reachable (no connection error).

- [ ] **Step 2: Confirm baseline ROI counts in remote (via Supabase MCP `execute_sql`)**

```sql
select risk_dimension, count(*) from priority.current_rois group by 1 order by 1;
```
Expected (baseline): `crash | 5`. Record this number; later tasks compare against it.

- [ ] **Step 3: Smoke the SSC extract (already-verified source) end to end**

```bash
external-data extract --source ssc_hechos_transito
external-data load-db --source ssc_hechos_transito
```
Expected: staging Parquet written under `.data/`; `load-db` reports rows inserted into `priority.external_signals` (idempotent — re-run inserts 0 new).

### Task A2: Load `crash` (SSC + C5 + ciclistas + peatones)

**Files:** `services/external-data/src/external_data/registry/sources.yaml` (only if a header drifted).

- [ ] **Step 1: Verify headers for each crash source**

For `c5_incidentes_viales`, `accidentes_ciclistas`, `accidentes_peatones`: fetch the live CSV head and confirm the `sources.yaml` `column_map` (lat/lng/date/type) matches. If a header changed, edit that source's `column_map` in `sources.yaml`. (SSC is already verified.)

- [ ] **Step 2: Extract + load each reachable crash source**

```bash
for s in ssc_hechos_transito c5_incidentes_viales accidentes_ciclistas accidentes_peatones; do
  external-data extract --source "$s" || echo "SKIP $s (extract failed)";
  external-data load-db --source "$s" || echo "SKIP $s (load failed)";
done
```
Expected: per-source row counts logged; failures skipped, not fatal.

- [ ] **Step 3: Compute crash ROIs**

```bash
external-data roi-compute --dimension crash
```
Expected: a new `roi_runs` row; new `rois`; prior current crash ROIs superseded (the 5 sample ROIs get `valid_to` set).

- [ ] **Step 4: Verify (Supabase MCP)**

```sql
select risk_dimension, count(*) c, round(max(risk_score)::numeric,1) maxr
from priority.current_rois where risk_dimension='crash' group by 1;
```
Expected: `crash` count now in the hundreds (SSC alone validated at 870 locally), `maxr` > 0.

- [ ] **Step 5: Commit any header fixes**

```bash
git add services/external-data/src/external_data/registry/sources.yaml
git commit -m "fix(external-data): verify/repair crash-source column maps for live load"
```
(If no YAML changed, skip the commit.)

### Task A3: Load `flooding` (SACMEX + 0311-agua)

**Files:** `sources.yaml` (only if a header drifted).

- [ ] **Step 1: Verify headers** for `sacmex_encharcamientos`, `locatel_0311_agua` (the `agua`/`encharcamientos` subset filter); fix `column_map`/`subset` if needed.
- [ ] **Step 2: Extract + load**

```bash
for s in sacmex_encharcamientos locatel_0311_agua; do
  external-data extract --source "$s" || echo "SKIP $s";
  external-data load-db --source "$s" || echo "SKIP $s";
done
```
- [ ] **Step 3: Compute** `external-data roi-compute --dimension flooding`
- [ ] **Step 4: Verify (MCP):** `select count(*) from priority.current_rois where risk_dimension='flooding';` Expected: ≥ tens.
- [ ] **Step 5: Commit** any `sources.yaml` fixes (`fix(external-data): flooding-source column maps`).

### Task A4: Load `road_surface` (0311-baches)

**Files:** `sources.yaml` (only if a header drifted).

- [ ] **Step 1: Verify headers** for `locatel_0311_baches` (the `baches` subset filter).
- [ ] **Step 2: Extract + load** `external-data extract --source locatel_0311_baches` then `external-data load-db --source locatel_0311_baches`.
- [ ] **Step 3: Compute** `external-data roi-compute --dimension road_surface`
- [ ] **Step 4: Verify (MCP):** `select count(*) from priority.current_rois where risk_dimension='road_surface';` Expected: ≥ tens.
- [ ] **Step 5: Commit** any `sources.yaml` fix.

### Task A5: Load `crime` (FGJ carpetas + víctimas, via CKAN)

**Files:** `sources.yaml` (only if a header drifted).

- [ ] **Step 1: Verify reachability + headers.** The FGJ archive subdomain (`archivo.datos.cdmx.gob.mx`) is not routable from the dev sandbox; rely on the CKAN-linked URL. Confirm `fgj_carpetas`/`fgj_victimas` CSV headers resolve. If unreachable, **skip this task** (crime layer stays disabled in the UI; the other 3 dimensions still satisfy the DoD).
- [ ] **Step 2: Extract + load** both FGJ sources (skip-on-failure as in A2 Step 2).
- [ ] **Step 3: Compute** `external-data roi-compute --dimension crime`
- [ ] **Step 4: Verify (MCP):** `select count(*) from priority.current_rois where risk_dimension='crime';`
- [ ] **Step 5: Commit** any `sources.yaml` fix.

### Task A6: Data done-gate

**Files:** none.

- [ ] **Step 1: Final counts (MCP)**

```sql
select risk_dimension, count(*) rois, round(max(risk_score)::numeric,1) maxr
from priority.current_rois group by 1 order by 1;
select risk_dimension, count(*) signals
from priority.external_signals group by 1 order by 1;
```
Expected: **≥3 of the 4 dimensions** (crash, flooding, road_surface, crime) populated with plausible counts; corresponding signals present.
- [ ] **Step 2: Record the counts** in the task notes / PR description (they prove WS-A's DoD).

---

## WS-B — API + Frontend

### Task B1: Migration `0212` — dimension-filtered ROI reads + counts

**Files:**
- Create: `supabase/migrations/0212_app_roi_layers.sql`
- Create: `supabase/tests/0212_app_roi_layers.test.sql`
- Modify: `packages/db-types/database.ts` (regen)

**Interfaces:**
- Produces: `public.app_current_rois(p_dimensions text[] default null, p_limit int default 250)` returning `(id uuid, risk_dimension text, centroid_lat double precision, centroid_lng double precision, risk_score real, dominant_type text, description text, signal_count int, geom_geojson jsonb)`; and `public.app_roi_dimension_counts()` returning `(risk_dimension text, roi_count int, max_risk real)`.

- [ ] **Step 1: Write the migration**

Create `supabase/migrations/0212_app_roi_layers.sql`:

```sql
-- 0212_app_roi_layers.sql
-- Per-dimension risk-zone layers: dimension-filtered/limited ROI reads + per-dimension counts.
-- Replaces the zero-arg app_current_rois() with a filtered/limited variant; adds
-- app_roi_dimension_counts() for the Layers panel. Follows 0200 conventions.

-- Drop the old zero-arg overload so a no-arg call resolves unambiguously to the new one.
drop function if exists public.app_current_rois();

create or replace function public.app_current_rois(
  p_dimensions text[] default null,
  p_limit int default 250
)
returns table(
  id uuid, risk_dimension text,
  centroid_lat double precision, centroid_lng double precision,
  risk_score real, dominant_type text, description text,
  signal_count int,
  geom_geojson jsonb)
language sql stable security definer set search_path = extensions, public as $$
  select
    r.id, r.risk_dimension,
    ST_Y(r.centroid::geometry) as centroid_lat,
    ST_X(r.centroid::geometry) as centroid_lng,
    r.risk_score, r.dominant_type, r.description,
    r.signal_count,
    ST_AsGeoJSON(r.geom::geometry)::jsonb as geom_geojson
  from priority.current_rois r
  join geo.tenant_boundary_versions b
    on b.tenant_id = public._app_tenant() and b.status = 'active'
  where ST_Contains(b.materialized_geometry, r.centroid::geometry)
    and (
      p_dimensions is null
      or array_length(p_dimensions, 1) is null
      or r.risk_dimension = any(p_dimensions)
    )
  order by r.risk_score desc
  limit greatest(1, least(coalesce(p_limit, 250), 2000));
$$;

create or replace function public.app_roi_dimension_counts()
returns table(risk_dimension text, roi_count int, max_risk real)
language sql stable security definer set search_path = extensions, public as $$
  select r.risk_dimension, count(*)::int as roi_count, max(r.risk_score) as max_risk
  from priority.current_rois r
  join geo.tenant_boundary_versions b
    on b.tenant_id = public._app_tenant() and b.status = 'active'
  where ST_Contains(b.materialized_geometry, r.centroid::geometry)
  group by r.risk_dimension
  order by r.risk_dimension;
$$;

grant execute on function public.app_current_rois(text[], int) to authenticated;
grant execute on function public.app_roi_dimension_counts() to authenticated;
```

- [ ] **Step 2: Write the SQL assertion test**

Create `supabase/tests/0212_app_roi_layers.test.sql`:

```sql
-- 0212_app_roi_layers.test.sql — signature/contract assertions (run via Supabase MCP).
do $$
begin
  assert (
    select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and p.proname = 'app_current_rois'
      and pg_get_function_identity_arguments(p.oid) = 'p_dimensions text[], p_limit integer'
  ) = 1, 'app_current_rois(text[], int) is missing';

  assert (
    select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and p.proname = 'app_current_rois'
      and pg_get_function_identity_arguments(p.oid) = ''
  ) = 0, 'old zero-arg app_current_rois() still present (ambiguous no-arg calls)';

  assert (
    select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and p.proname = 'app_roi_dimension_counts'
  ) = 1, 'app_roi_dimension_counts() is missing';

  raise notice '0212 assertions passed';
end $$;
```

- [ ] **Step 3: Apply the migration (Supabase MCP)**

Use MCP `apply_migration` with name `0212_app_roi_layers` and the Step 1 SQL.
Expected: success, no error.

- [ ] **Step 4: Run the assertion test (Supabase MCP `execute_sql`)**

Run the Step 2 file contents.
Expected: `NOTICE: 0212 assertions passed`, no `assertion failed` error.

- [ ] **Step 5: Functional check against existing crash sample (Supabase MCP)**

```sql
select count(*) all_dims from public.app_current_rois();           -- defaults: all dims, top 250
select count(*) crash_only from public.app_current_rois(array['crash'], 250);
select * from public.app_roi_dimension_counts();
```
> Note: called as the table owner these resolve `_app_tenant()` to the function's definer context; if `_app_tenant()` returns null outside an auth session, assert instead that the calls execute without error (the live-auth behavior is covered by the B4 smoke). Expected: no error; `app_roi_dimension_counts` returns a `crash` row.

- [ ] **Step 6: Regenerate types**

Use MCP `generate_typescript_types`; overwrite `packages/db-types/database.ts`. Verify `app_current_rois` (with args) and `app_roi_dimension_counts` appear under `Database['public']['Functions']`.

- [ ] **Step 7: Commit**

```bash
git add supabase/migrations/0212_app_roi_layers.sql supabase/tests/0212_app_roi_layers.test.sql packages/db-types/database.ts
git commit -m "feat(db): per-dimension ROI read RPCs (app_current_rois filter+limit, app_roi_dimension_counts)"
```

### Task B2: Dimension presentation module

**Files:** Create `frontend/src/lib/dimensions.ts`

**Interfaces:**
- Produces: `DIMENSION_PRESENTATION`, `DIMENSION_ORDER`, `dimensionColor(dim)`, `dimensionLabel(dim)`, `DimensionPresentation`.

- [ ] **Step 1: Write the module**

```ts
// Per-risk-dimension presentation (app-owned) for the external-dataset ROI layers.
// Single source of truth for layer color + Spanish label. DIMENSION_ORDER defines
// the order rows appear in the Layers panel.

export interface DimensionPresentation {
  label: string;
  color: string;
  deferred?: boolean; // shown disabled until its data lands (needs geocoding)
}

export const DIMENSION_PRESENTATION: Record<string, DimensionPresentation> = {
  crash: { label: "Choques", color: "#e5484d" },
  flooding: { label: "Inundación", color: "#2f64e6" },
  road_surface: { label: "Bacheo", color: "#f5a623" },
  crime: { label: "Crimen", color: "#7c3aed" },
  violation: { label: "Infracciones", color: "#0f9b8e", deferred: true },
};

export const DIMENSION_ORDER = ["crash", "flooding", "road_surface", "crime", "violation"];
export const NEUTRAL_DIMENSION_COLOR = "#9aa3b1";

export function dimensionColor(dim: string): string {
  return DIMENSION_PRESENTATION[dim]?.color ?? NEUTRAL_DIMENSION_COLOR;
}
export function dimensionLabel(dim: string): string {
  return DIMENSION_PRESENTATION[dim]?.label ?? dim;
}
```

- [ ] **Step 2: Typecheck**

Run: `bun run typecheck`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/dimensions.ts
git commit -m "feat(app): risk-dimension presentation module (color/label per dimension)"
```

### Task B3: Types + API wrappers

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/api.ts`

**Interfaces:**
- Consumes: B1 RPC shapes.
- Produces: `Roi.signalCount`; `DimensionCount { dimension: string; count: number; maxRisk: number | null }`; `api.getRois(dimensions?: string[], limit?: number)`, `api.getRoiDimensionCounts(): Promise<DimensionCount[]>`.

- [ ] **Step 1: Add `signalCount` to `Roi` and the `DimensionCount` type**

In `frontend/src/lib/types.ts`, update the `Roi` interface (add `signalCount`) and append `DimensionCount`:

```ts
export interface Roi {
  id: string;
  riskDimension: string;
  lat: number;
  lng: number;
  riskScore: number;
  dominantType: string;
  description: string;
  signalCount: number | null;
  geojson: unknown;
}

export interface DimensionCount {
  dimension: string;
  count: number;
  maxRisk: number | null;
}
```

- [ ] **Step 2: Update `getRois` and add `getRoiDimensionCounts`**

In `frontend/src/lib/api.ts`, add `DimensionCount` to the type import, replace `getRois`, and add the counts wrapper:

```ts
import type {
  DimensionCount,
  Observation,
  ObservationDetail,
  Roi,
  RunSummary,
  Tenant,
  TypeCount,
} from "./types";

// ...

export async function getRois(dimensions?: string[], limit?: number): Promise<Roi[]> {
  const { data, error } = await supabase.rpc("app_current_rois", {
    p_dimensions: dimensions && dimensions.length ? dimensions : undefined,
    p_limit: limit ?? undefined,
  });
  if (error) throw error;
  return (data ?? []).map((r) => ({
    id: r.id,
    riskDimension: r.risk_dimension,
    lat: r.centroid_lat,
    lng: r.centroid_lng,
    riskScore: r.risk_score,
    dominantType: r.dominant_type,
    description: r.description,
    signalCount: r.signal_count,
    geojson: r.geom_geojson,
  }));
}

export async function getRoiDimensionCounts(): Promise<DimensionCount[]> {
  const { data, error } = await supabase.rpc("app_roi_dimension_counts");
  if (error) throw error;
  return (data ?? []).map((r) => ({
    dimension: r.risk_dimension,
    count: r.roi_count,
    maxRisk: r.max_risk,
  }));
}
```

- [ ] **Step 3: Typecheck**

Run: `bun run typecheck`
Expected: no errors (B1 regenerated types make `app_current_rois` accept `p_dimensions`/`p_limit` and expose `signal_count`; `app_roi_dimension_counts` is known).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/lib/api.ts
git commit -m "feat(app): per-dimension ROI api wrappers + DimensionCount type"
```

### Task B4: Live RPC smoke

**Files:** Create `frontend/scripts/verify-roi-rpc.mjs`

**Interfaces:** Consumes B1 (applied) + B3 wrappers' contract (calls the raw RPCs).

- [ ] **Step 1: Write the smoke script**

```js
// Live authenticated smoke for the per-dimension ROI RPCs. Signs in as the dev
// user and asserts dimension filtering, ordering, and the limit cap. This is the
// project's "integration test" for 0212 (no JS test runner — see plan constraints).
import { readFileSync } from "node:fs";
import { createClient } from "@supabase/supabase-js";

const env = Object.fromEntries(
  readFileSync(new URL("../.env", import.meta.url), "utf8")
    .split("\n")
    .filter((l) => l && !l.trimStart().startsWith("#") && l.includes("="))
    .map((l) => {
      const i = l.indexOf("=");
      return [l.slice(0, i).trim(), l.slice(i + 1).trim().replace(/^["']|["']$/g, "")];
    }),
);

const supabase = createClient(env.VITE_SUPABASE_URL, env.VITE_SUPABASE_ANON_KEY);

const { error: authErr } = await supabase.auth.signInWithPassword({
  email: "author.a@vialia.test",
  password: "vialia-dev-2026!",
});
if (authErr) throw authErr;

const counts = await supabase.rpc("app_roi_dimension_counts");
if (counts.error) throw counts.error;
console.log("dimension counts:", counts.data);

const crash = await supabase.rpc("app_current_rois", { p_dimensions: ["crash"], p_limit: 5 });
if (crash.error) throw crash.error;
const rows = crash.data ?? [];
const onlyCrash = rows.every((r) => r.risk_dimension === "crash");
const withinLimit = rows.length <= 5;
const ordered = rows.every((r, i, a) => i === 0 || a[i - 1].risk_score >= r.risk_score);
console.log({ rows: rows.length, onlyCrash, withinLimit, ordered });

if (!onlyCrash || !withinLimit || !ordered) {
  console.error("RPC smoke FAIL");
  process.exit(1);
}
console.log("RPC smoke PASS");
process.exit(0);
```

- [ ] **Step 2: Run it**

Run: `bun scripts/verify-roi-rpc.mjs`
Expected: prints dimension counts (at least `crash`), then `{ onlyCrash: true, withinLimit: true, ordered: true }`, then `RPC smoke PASS`, exit 0.

- [ ] **Step 3: Commit**

```bash
git add frontend/scripts/verify-roi-rpc.mjs
git commit -m "test(app): live RPC smoke for per-dimension ROI reads"
```

### Task B5: MapPage — dimension state, lazy fetch + cache, wiring

**Files:** Modify `frontend/src/pages/MapPage.tsx`

**Interfaces:**
- Consumes: B3 `api.getRois(dims)`, `api.getRoiDimensionCounts()`; B2 nothing here.
- Produces (props passed down): to `LayersPanel` — `riskMaster`, `riskExpanded`, `dimensionCounts`, `activeDimensions`, `totalRoiCount`, `onToggleRiskMaster`, `onToggleRiskExpanded`, `onToggleDimension`; to `MapCanvas` — `rois={roisToRender}`, `showRois={riskMaster}`.

- [ ] **Step 1: Replace the ROI state declarations**

Replace `const [rois, setRois] = useState<Roi[]>([]);` (and the `showRois` line) with:

```ts
  const [dimensionCounts, setDimensionCounts] = useState<DimensionCount[]>([]);
  const roiCache = useRef<Map<string, Roi[]>>(new Map());
  const [roiVersion, setRoiVersion] = useState(0); // bump after a lazy fetch resolves

  // ---- layer toggles ------------------------------------------------------
  const [showPins, setShowPins] = useState(true);
  const [riskMaster, setRiskMaster] = useState(true);
  const [riskExpanded, setRiskExpanded] = useState(true);
  const [activeDimensions, setActiveDimensions] = useState<Record<string, boolean>>({});
  const [activeTypes, setActiveTypes] = useState<Record<string, boolean>>({});
```

(Delete the old `const [showRois, setShowRois] = useState(true);` and the old `showPins`/`activeTypes` lines you are replacing — keep exactly one declaration of each.)

- [ ] **Step 2: Update the type import**

In the `import type { … } from "../lib/types";` block, add `DimensionCount` and keep `Roi`.

- [ ] **Step 3: Swap the initial load to fetch counts + prefetch enabled dims**

In the initial-load `useEffect`, replace `api.getRois()` in the `Promise.all` with `api.getRoiDimensionCounts()` and rename the result, then initialize dimension state and prefetch:

```ts
        const [tenant, tc, obs, dc, bnd, live] = await Promise.all([
          api.getActiveTenant(),
          api.getTypeCounts(),
          api.getObservations(),
          api.getRoiDimensionCounts(),
          api.getBoundary(),
          api.listRuns(),
        ]);
        if (!alive) return;
        // ...existing tenant/types/observations/boundary/liveRuns setters...
        setDimensionCounts(dc);
        const enabled = Object.fromEntries(
          dc.filter((d) => d.count > 0).map((d) => [d.dimension, true]),
        );
        setActiveDimensions(enabled);
        const dims = Object.keys(enabled);
        const fetched = await Promise.all(dims.map((d) => api.getRois([d])));
        if (!alive) return;
        dims.forEach((d, i) => roiCache.current.set(d, fetched[i]));
        setRoiVersion((v) => v + 1);
        setLoaded(true);
```

(Remove the old `setRois(ro);` line.)

- [ ] **Step 4: Add lazy-load + toggle handlers and the derived render list**

Add near the other handlers:

```ts
  const ensureDimLoaded = useCallback(async (dim: string) => {
    if (roiCache.current.has(dim)) return;
    const r = await api.getRois([dim]);
    roiCache.current.set(dim, r);
    setRoiVersion((v) => v + 1);
  }, []);

  const onToggleDimension = (dim: string) => {
    const turningOn = !activeDimensions[dim];
    setActiveDimensions((ad) => ({ ...ad, [dim]: !ad[dim] }));
    if (turningOn) void ensureDimLoaded(dim);
  };

  const onToggleRiskMaster = () => {
    const turningOn = !riskMaster;
    setRiskMaster(turningOn);
    if (turningOn) {
      for (const d of Object.keys(activeDimensions)) {
        if (activeDimensions[d]) void ensureDimLoaded(d);
      }
    }
  };
```

Add the derived list near the other `useMemo`s (the `roiVersion` dep makes it recompute after a cache write):

```ts
  const roisToRender = useMemo<Roi[]>(() => {
    if (!riskMaster) return [];
    const out: Roi[] = [];
    for (const [dim, on] of Object.entries(activeDimensions)) {
      if (!on) continue;
      const cached = roiCache.current.get(dim);
      if (cached) out.push(...cached);
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [riskMaster, activeDimensions, roiVersion]);

  const totalRoiCount = useMemo(
    () => dimensionCounts.reduce((s, d) => s + d.count, 0),
    [dimensionCounts],
  );
```

- [ ] **Step 5: Update the `MapCanvas` and `LayersPanel` props in render**

`MapCanvas`: change `showRois={showRois}` → `showRois={riskMaster}` and `rois={rois}` → `rois={roisToRender}`.

`LayersPanel`: replace the `roiCount` / `showRois` / `onToggleRois` props with the grouped set:

```tsx
      <LayersPanel
        types={types}
        totalObs={observations.length}
        showPins={showPins}
        riskMaster={riskMaster}
        riskExpanded={riskExpanded}
        dimensionCounts={dimensionCounts}
        activeDimensions={activeDimensions}
        totalRoiCount={totalRoiCount}
        activeTypes={activeTypes}
        lastSweepLabel={`${observations.length} obs · en vivo`}
        bottom={layersBottom}
        onTogglePins={() => setShowPins((v) => !v)}
        onToggleRiskMaster={onToggleRiskMaster}
        onToggleRiskExpanded={() => setRiskExpanded((v) => !v)}
        onToggleDimension={onToggleDimension}
        onToggleType={onToggleType}
        onSignOut={signOut}
      />
```

- [ ] **Step 6: Typecheck** (will fail until LayersPanel B6 lands — expected)

Run: `bun run typecheck`
Expected: errors ONLY about `LayersPanel` props (it still has the old signature). MapPage's own code typechecks. Proceed to B6; do not commit yet.

### Task B6: LayersPanel — grouped master + per-dimension sub-toggles

**Files:** Modify `frontend/src/components/LayersPanel.tsx`

**Interfaces:**
- Consumes: B2 `DIMENSION_ORDER`, `DIMENSION_PRESENTATION`, `dimensionColor`, `dimensionLabel`; B3 `DimensionCount`; B5 prop set.

- [ ] **Step 1: Replace the Props interface**

```ts
import type { DimensionCount, TypeCount } from "../lib/types";
import { typeColor } from "../lib/types";
import {
  DIMENSION_ORDER,
  DIMENSION_PRESENTATION,
  dimensionColor,
  dimensionLabel,
} from "../lib/dimensions";
import { Panel } from "@/components/ui/panel";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

interface Props {
  types: TypeCount[];
  totalObs: number;
  showPins: boolean;
  riskMaster: boolean;
  riskExpanded: boolean;
  dimensionCounts: DimensionCount[];
  activeDimensions: Record<string, boolean>;
  totalRoiCount: number;
  activeTypes: Record<string, boolean>;
  lastSweepLabel: string;
  bottom: number;
  onTogglePins: () => void;
  onToggleRiskMaster: () => void;
  onToggleRiskExpanded: () => void;
  onToggleDimension: (dim: string) => void;
  onToggleType: (slug: string) => void;
  onSignOut: () => void;
}
```

- [ ] **Step 2: Replace the single ROI button + subtitle with the grouped section**

Replace the existing block (the `Zonas de riesgo` `<Button>` and the `externas · …` `<div>`) with:

```tsx
        <Button variant="ghost" onClick={props.onToggleRiskMaster} className={ROW}>
          <Indicator on={props.riskMaster} color="#e5484d" />
          <span className="flex-1 text-left text-[12.5px] font-semibold">Zonas de riesgo</span>
          <span className={COUNT}>{props.totalRoiCount}</span>
          <span
            role="button"
            aria-label="Mostrar dimensiones"
            onClick={(e) => {
              e.stopPropagation();
              props.onToggleRiskExpanded();
            }}
            className="ml-1 cursor-pointer select-none text-[10px] text-muted-foreground"
          >
            {props.riskExpanded ? "▾" : "▸"}
          </span>
        </Button>

        {props.riskExpanded &&
          DIMENSION_ORDER.map((dim) => {
            const pres = DIMENSION_PRESENTATION[dim];
            const count = props.dimensionCounts.find((d) => d.dimension === dim)?.count ?? 0;
            const disabled = !!pres.deferred || count === 0;
            const on = !disabled && props.riskMaster && !!props.activeDimensions[dim];
            return (
              <Button
                key={dim}
                variant="ghost"
                disabled={disabled}
                onClick={() => props.onToggleDimension(dim)}
                className={`${ROW} pl-[22px] ${
                  disabled ? "opacity-40" : on ? "opacity-100" : "opacity-55"
                }`}
              >
                <Indicator on={on} color={dimensionColor(dim)} round />
                <span
                  className="flex-1 text-left text-[12px] font-semibold"
                  style={{ color: on ? "#1b2430" : "#a9b1bd" }}
                >
                  {dimensionLabel(dim)}
                  {pres.deferred ? " · próximamente" : ""}
                </span>
                <span className="font-mono text-[9.5px] text-[#aab2bd]">{count}</span>
              </Button>
            );
          })}
```

- [ ] **Step 3: Typecheck**

Run: `bun run typecheck`
Expected: no errors (B5 + B6 props now agree).

- [ ] **Step 4: Build**

Run: `bun run build`
Expected: build succeeds.

- [ ] **Step 5: Screenshot the panel**

Start the dev server (`bun run dev`) in the background, then run `node scripts/shot.mjs` (logs in, screenshots `/tmp/citycrawl-map.png`). Open the PNG and confirm: "Zonas de riesgo" master row + indented per-dimension sub-rows with color dots and counts; `Infracciones · próximamente` greyed/disabled.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/MapPage.tsx frontend/src/components/LayersPanel.tsx
git commit -m "feat(app): grouped per-dimension risk-zone layers with lazy fetch"
```

### Task B7: MapCanvas — per-dimension styling, risk-scaled fill, ROI popup

**Files:** Modify `frontend/src/components/MapCanvas.tsx`

**Interfaces:** Consumes B2 `dimensionColor`, `dimensionLabel`; renders `props.rois` (already filtered to active dims by MapPage).

- [ ] **Step 1: Update imports**

```ts
import { dimensionColor, dimensionLabel } from "../lib/dimensions";
```
(Remove the `riskLabel` import — it is replaced by `dimensionLabel`. Leave the rest.)

- [ ] **Step 2: Add the popup helpers (module scope, above the component)**

```ts
function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string,
  );
}

function roiPopupHtml(roi: Roi): string {
  const color = dimensionColor(roi.riskDimension);
  const sc = roi.signalCount != null ? ` · ${roi.signalCount} señales` : "";
  const score = typeof roi.riskScore === "number" ? roi.riskScore.toFixed(1) : roi.riskScore;
  return `
    <div style="font-family:Public Sans,sans-serif;max-width:240px;">
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
        <span style="width:9px;height:9px;border-radius:50%;background:${color};display:inline-block;"></span>
        <strong style="font-size:12px;color:#1b2430;">${dimensionLabel(roi.riskDimension)}</strong>
      </div>
      <div style="font-family:IBM Plex Mono,monospace;font-size:10px;color:#7a8493;margin-bottom:5px;">
        riesgo ${score} · ${escapeHtml(roi.dominantType ?? "")}${sc}
      </div>
      <div style="font-size:11px;line-height:1.4;color:#3a4250;">${escapeHtml(roi.description ?? "")}</div>
    </div>`;
}
```

- [ ] **Step 3: Replace the ROI render effect body**

Replace the loop inside the `// ---- risk-ROIs …` effect (the `for (const roi of props.rois) { … }` block) with per-dimension coloring, risk-scaled fill, an interactive popup, and a dimension-colored label:

```tsx
    // per-dimension max risk → within-dimension opacity scaling
    const maxByDim: Record<string, number> = {};
    for (const roi of props.rois) {
      maxByDim[roi.riskDimension] = Math.max(maxByDim[roi.riskDimension] ?? 0, roi.riskScore ?? 0);
    }

    for (const roi of props.rois) {
      const color = dimensionColor(roi.riskDimension);
      const max = maxByDim[roi.riskDimension] || 1;
      const share = Math.max(0, Math.min(1, (roi.riskScore ?? 0) / max));
      const fillOpacity = 0.08 + share * 0.24; // 0.08–0.32 within the dimension
      try {
        const layer = L.geoJSON({ type: "Feature", geometry: roi.geojson, properties: {} } as never, {
          interactive: true,
          style: {
            color,
            weight: 1.6,
            opacity: 0.75,
            dashArray: "5 4",
            fill: true,
            fillColor: color,
            fillOpacity,
          },
        });
        layer.bindPopup(roiPopupHtml(roi), { maxWidth: 260 });
        layer.addTo(g);
      } catch {
        /* ignore malformed geometry */
      }
      L.marker([roi.lat, roi.lng], {
        interactive: false,
        icon: L.divIcon({
          className: "",
          html: `<div style="background:#fff;color:${color};font:600 9.5px IBM Plex Mono,monospace;padding:2px 7px;border-radius:6px;white-space:nowrap;border:1px solid ${color}55;box-shadow:0 3px 9px -3px ${color}66;transform:translate(-50%,-50%);">${dimensionLabel(roi.riskDimension)}</div>`,
          iconSize: [0, 0],
        }),
      }).addTo(gl);
    }
```

(Leave the surrounding effect structure — `g.clearLayers()`, the `!props.showRois` early-return, `syncRoiLabels()`, and the dependency array `[props.rois, props.showRois]` — unchanged.)

- [ ] **Step 4: Typecheck + build**

Run: `bun run typecheck && bun run build`
Expected: both succeed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/MapCanvas.tsx
git commit -m "feat(app): per-dimension ROI styling, risk-scaled fill, detail popup"
```

### Task B8: Closing visual gate

**Files:** none (verification).

- [ ] **Step 1: Run the full screenshot flow**

With the dev server running, run `node scripts/shot.mjs`. Open `/tmp/citycrawl-map.png`.

- [ ] **Step 2: Confirm the feature visually**

Check: ≥2 dimension layers rendered in distinct colors (after WS-A: crash red, flooding blue, road_surface amber, crime purple); the grouped Layers panel with master + sub-toggles; toggling a sub-dimension off removes only that color from the map. Click an ROI polygon → popup shows dimension, risk, dominant type, signal count, description. (If only the crash sample is loaded, verify crash renders + popup works; the rest validates once WS-A lands.)

- [ ] **Step 3: Re-run the RPC smoke**

Run: `bun scripts/verify-roi-rpc.mjs`
Expected: `RPC smoke PASS`.

- [ ] **Step 4: Final confirmation**

`bun run typecheck && bun run build` both green; WS-A done-gate (A6) counts recorded. Feature complete.

---

## Self-Review (spec coverage)

- "Both halves" → WS-A (A1–A6) + WS-B (B1–B8). ✓
- "Point-source dims, full real load" → A2 crash, A3 flooding, A4 road_surface, A5 crime; violation deferred (B2 `deferred`, B6 disabled row). ✓
- "Grouped: master + sub-toggles" → B6. ✓
- `app_current_rois` filter+limit + `app_roi_dimension_counts` → B1. ✓
- Lazy per-dimension fetch + top-N cap → B5 (`ensureDimLoaded`, cache) + B1 (`p_limit`). ✓
- Per-dimension styling + risk-scaled fill + ROI popup → B7. ✓
- No client priority math → fill opacity is display-only scaling of `risk_score` (B7). ✓
- Schema-compat + tests run → B1 (conventions, SQL assert), B4 (live smoke), screenshots. ✓
- Credential dependency + fallback → WS-A header + Global Constraints. ✓
- Type consistency: `Roi.signalCount`, `DimensionCount{dimension,count,maxRisk}`, `getRois(dimensions?,limit?)`, `getRoiDimensionCounts()`, `app_current_rois(p_dimensions,p_limit)`, `app_roi_dimension_counts()`, panel props (`riskMaster/riskExpanded/dimensionCounts/activeDimensions/totalRoiCount/onToggleRiskMaster/onToggleRiskExpanded/onToggleDimension`) — used identically across B1/B3/B5/B6/B7. ✓
- Open risk: non-SSC CSV headers unverified (A2–A5 Step 1 each) — skip-on-failure keeps remaining dimensions landing; `app_roi_dimension_counts` drives which sub-rows enable, so the UI self-adjusts to whatever data lands.
