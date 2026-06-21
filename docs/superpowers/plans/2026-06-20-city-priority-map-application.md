# City Priority Map — Application (Component #6) Implementation Plan

> **BUILD STATUS (2026-06-20, branch `feat/city-priority-map-app`):** Core app shipped and verified against live Supabase.
> - **Source of truth is now `design/CityPriorityMap.dc.html`** (the freshly re-imported design; the old `design/city-priority-map/` copy is disregarded per the user).
> - **All UI is in Spanish** (per user). Type labels come from the DB (already Spanish).
> - **Read API:** `supabase/migrations/0200_app_read_api.sql` applied to remote — 8 `public.app_*` security-definer RPCs (no RLS needed; `authenticated` has no schema USAGE). Types regenerated into `packages/db-types/database.ts`.
> - **Analyses are MOCKED client-side** behind a swappable provider seam (`apps/web/src/lib/analysis.ts`) — they are real Cloudflare-Worker jobs in the target architecture (draft→queue→worker→persist→render); see memory `city-priority-map-architecture`. Latent uses the **real** `priority.current_rois`.
> - **Stack simplified for speed:** plain Vite+React+TS with the reference's inline styles ported 1:1 (no shadcn/Tailwind/react-router/TanStack — the design is inline-styled, so this maximizes fidelity). Auth = Supabase email/password.
> - **Shipped:** Login, Map (114 live obs as weighted pins + heat grid + CDMX boundary), Layers panel, Observation card (live detail), Analysis dock (route/group + budget + cost basis + stats + ordered list), Latent scan (live ROIs), History popover (live runs), Agent chips (trigger analyses).
> - **Deferred / disabled (complex, per user):** Agent natural-language input + chat feed; Sweep-preview scrubber + the observation card's "Ver recorrido" button. The chips replace the NL parser for triggering analyses.
> - **Testing:** light per user — verified via typecheck + production build + headless-Chrome screenshots of every surface (login, map, group analysis, latent, observation card). No Vitest/Playwright suite yet.
>
> The sections below are the original (pre-build) plan, kept for reference; some choices (shadcn, in-DB analysis RPCs `0201`, E2E) were intentionally not taken.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Use the **shadcn** skill for all UI primitives and the **frontend-design** skill to keep fidelity to the reference.

**Goal:** Ship the live, authenticated "Vialia" CDMX priority-map application — a faithful React port of `design/city-priority-map/CityPriorityMap.dc.html` wired to the real Supabase data model (`vision`/`priority`/`geo`/`analysis`).

**Architecture:** A Vite + React + TypeScript SPA (`apps/web`) using shadcn/ui primitives and react-leaflet, talking to Supabase only through a **`public` read/analysis API layer** (security-definer SQL views + RPCs added in new migrations) so the browser never touches the custom schemas directly and RLS/tenancy stay enforced. Supabase Auth gates the app behind a login page; the authenticated user resolves to a `platform.oidc_subjects` → `tenant_memberships` → tenant. Map data (observations, priority heat, types, ROIs, districts, observation detail) comes from read endpoints; the Route/Group/Latent analyses run as plpgsql RPC executors that persist `analysis.analysis_runs` + `analysis_results` and return artifacts (a documented stand-in for the future external analysis provider/worker).

**Tech Stack:** Vite, React 18, TypeScript, bun, shadcn/ui (Radix + Tailwind), Tailwind CSS, react-leaflet + leaflet, @supabase/supabase-js, TanStack Query, react-router, Vitest (integration), Playwright (E2E). Fonts: Public Sans (display/body) + IBM Plex Mono (numeric/metadata).

## Global Constraints

- **DEFINITION OF DONE (non-negotiable, applies to every task):** A feature is done only when (1) it is **compatible with the database schema** in `supabase/migrations/*` and `supabase/SCHEMA.md`, (2) it is **visually close to** `design/city-priority-map/CityPriorityMap.dc.html` rendered in a browser, and (3) its **integration tests pass when run** (output shown — no "should pass" claims). Do not stop or report completion until all three hold for all features.
- **Source of truth for UI + client logic:** `design/city-priority-map/CityPriorityMap.dc.html`. Port its markup → JSX, its inline styles → Tailwind/shadcn, and its `class Component` methods (`buildData` is replaced by live reads; `computeAnalysis`/`computeLatent`/`parseCommand`/`weightColor`/`heat`/`fitTo`/`drawPins`/`drawGrid`/`drawResult` are ported faithfully).
- **The DB is populated by a separate agent.** Do NOT write seed data for observations/types/geo/priority/ROIs/users. Instead implement against, and keep current, the **DB Data Contract** (§4). Coordinate via that section only.
- **Browser never queries custom schemas.** All reads/writes go through the `public` API layer (§2, §3). No `.schema('vision')` calls in `apps/web`.
- **No pure black/white, no AI-slop.** Honor the reference palette: bg `#eef1f5`, ink `#1b2430`, accent `#2f64e6` (configurable), type colors per §4.3. Frosted-glass panels, IBM Plex Mono for all numerics/ids/coords.
- **Money:** `Intl.NumberFormat('es-MX',{style:'currency',currency:'MXN'})`, strip `MX$`→`$` (matches reference `$()`).
- **bun** is the package manager. **Never** commit `.env*` with real keys; use `apps/web/.env.example`.

---

## 1. Reference anatomy (what we are building)

Rendered, the screen is a full-bleed CARTO-light Leaflet map of CDMX with four floating frosted-glass surfaces (port each as a component):

| Surface | Reference section | Component | Live data source |
|---|---|---|---|
| **Layers panel** (top-left) | `aside` "LAYERS PANEL" | `LayersPanel` | `app_observation_types_counts`, toggles local |
| **Agent panel** (top-right) | `aside` "AGENT PANEL" | `AgentPanel` | chat feed local; commands → analysis RPCs |
| **Launcher / Analysis dock** (bottom-center) | "LAUNCHER" + "ANALYSIS DOCK" | `AnalysisDock` | `app_run_analysis` / `app_run_latent` |
| **Past analyses popover** | "PAST ANALYSES" | `HistoryPopover` | `analysis_runs` via `app_list_runs` |
| **Selected observation card** (bottom-left) | "SELECTED OBSERVATION CARD" | `ObservationCard` | `app_observation_detail` |
| **Map overlays** | `initMap`/`drawPins`/`drawGrid`/`drawResult` | `MapCanvas` | `app_map_observations`, `app_priority_cells`, `app_current_rois` |
| **Login** (new, not in reference) | — | `LoginPage` | Supabase Auth |

Behaviors to preserve verbatim from the reference: layer toggles + per-type filter with live recompute, budget slider + cost-basis popover with live recompute, Route↔Group segment, latent ("inspection scan") mode, NL command parsing, non-modal dock that keeps the map interactive, `fitTo` padding that accounts for the open dock, pin/heat/route/ROI rendering, pending (dashed) vs scored pins.

---

## 2. Read API contract (`public` security-definer layer)

New migration `supabase/migrations/0200_app_read_api.sql`. Every function is `security definer`, `set search_path = ''`, resolves the caller via `auth.uid()` → `platform.oidc_subjects.user_id` → active `tenant_memberships`, and clips observations to the tenant's active boundary (reuse `platform.can_view_observation` / `tenant_visible_observations` / `ST_Contains`). They return UI-shaped rows so the browser needs no joins. **These signatures are the contract — the DB agent must populate the underlying tables (§4) so they return data.**

- `app_active_tenant()` → `table(tenant_id uuid, tenant_name text, accent text)` — caller's resolved tenant; errors if none.
- `app_observation_types_counts()` → `table(slug text, label text, category text, is_latent boolean, current_count int)` — type catalog + count of current observations of each type in the tenant boundary. (`is_latent` = `not auto_resolvable`, matches reference `missing_signage` LATENT styling; adjust if catalog adds an explicit flag.)
- `app_map_observations()` → `table(id uuid, slug text, lat double precision, lng double precision, weight numeric, state text, zone text, district_cve text, district_name text)` — current, in-boundary observations with their current priority weight (`priority.current_priority_values` → `priority_values.weight`); `state` = `'pending'` when no current priority value else `'scored'`; `zone`/`district_*` via `geo.observation_geo_bindings` → `geo_areas`.
- `app_priority_cells(p_cols int default 18, p_rows int default 14)` → `table(lat_s double precision, lat_n double precision, lng_w double precision, lng_e double precision, weight_sum numeric, issue_count int)` — server-side grid binning over the boundary bbox (ports `buildCells`/`binCells`); drives the heat layer.
- `app_current_rois()` → `table(id uuid, risk_dimension text, centroid_lat double precision, centroid_lng double precision, risk_score real, dominant_type text, description text, geom_geojson jsonb)` — from `priority.current_rois`, clipped to boundary.
- `app_observation_detail(p_id uuid)` → `table(id uuid, slug text, label text, lat double precision, lng double precision, weight numeric, state text, qty numeric, unit text, confirmations int, misses int, conf real, observed_at timestamptz, sweep text, recording_id text, frame_ref text, image_bbox jsonb, detector text, district_name text, zone text)` — everything the `ObservationCard` shows; `qty`/`unit` from `observation_attribute_values` + definitions; `conf` from a `confidence`-keyed attribute if present else null.

**RLS note:** read 0012 before writing these. If a function returns data the caller may not see, that is a bug. Prefer reusing existing helpers over re-deriving predicates.

---

## 3. Analysis API contract (`public` RPC executors)

New migration `supabase/migrations/0201_app_analysis_api.sql`. These create real `analysis.analysis_runs`, run an in-DB executor that mirrors the reference algorithms, persist `analysis_results` (+ `result_metrics`, `artifacts`, `sequence_items`/`map_features`), and return the run id + result payload. Documented as a stand-in for the future provider/worker (README Component 4/5).

- `app_run_analysis(p_kind text, p_budget numeric, p_active_types text[], p_costs jsonb)` → `jsonb` where `p_kind in ('route','cluster')`. Ports `computeAnalysis`: eligible = current, scored, type-enabled observations; greedy pick by `weight + (weight/cost)*8000` under budget (cap 40); for `route`, nearest-neighbor order from the NE-most seed; compute `spent`, `count`, `riskRed` (% of weight≥70 cleared), `distKm` (haversine), `zones`. Returns `{ run_id, kind, budget, stats[], items:[{id,slug,lat,lng,weight,zone,cost,position}] }`. Persists a `analysis_runs` row + `analysis_results.payload` + a `map_features`/`sequence_items` artifact.
- `app_run_latent(p_params jsonb default '{}')` → `jsonb`. Ports `computeLatent`: select high-risk low-issue grid cells (riskN>0.5, issueCount≤1) as ROIs (top 6), synthesize hypotheses from `HYP` set. Returns `{ run_id, rois:[{idx,centroid_lat,centroid_lng,riskPct}], hypos:[{roi,type,riskPct,lat,lng}] }`. Where `priority.current_rois` already has rows, prefer them over synthetic cells.
- `app_list_runs()` → `table(id uuid, kind text, budget numeric, status text, created_at timestamptz, is_latent boolean)` — for the History popover (most-recent first), tenant-scoped.
- `app_get_run(p_id uuid)` → `jsonb` — re-hydrate a past run's result payload for re-opening in the dock.

`budget_currency` = `'MXN'`. `idempotency_key` = `gen_random_uuid()::text` per submit (re-running with new budget creates a new run, matching reference behavior where budget changes recompute the active run — for live wiring, **debounce the slider and call `app_run_analysis` with the same `run_id` via an `app_update_run_budget(p_run_id,p_budget,...)` variant**; include that 5th RPC).

---

## 4. DB Data Contract (owned by the DB-populating agent — do not implement, keep accurate)

For the API layer to return a populated map, the DB must contain (the populating agent fills these; this section is the coordination handoff):

**4.1 Catalog & provenance** — `vision.sources` (≥1); `vision.observation_types` with at least the reference five: `pothole`, `open_drain`, `broken_light`, `missing_signage` (latent), `damaged_sidewalk`; per-type `observation_attribute_definitions` for quantity (`surface_area_m2`/`length_m`/`count`) + optional `confidence`; ≥1 `vision.sweeps` + `recordings`.

**4.2 Observations & priority** — ~150+ `vision.observations` spread across CDMX hot zones (Centro, Iztapalapa, Coyoacán, GAM, Álvaro Obregón, Roma-Norte, Tláhuac) with `location`, `observed_at`, `confirmation_count`, `miss_count`, `image_bbox`, `frame_ref`, `recording_id`; a portion left **without** a current priority value (→ `pending`); one active `priority.priority_models` + `priority_values` + `current_priority_values` giving weights 1–99.

**4.3 Geo** — active `geo.geo_editions`; `geo.geo_areas` for the CDMX alcaldías (district `cve`/`name`); `geo.observation_geo_bindings` so each observation resolves a district/zone.

**4.4 Tenancy & auth** — a tenant; an active `geo.tenant_boundary_versions` covering CDMX bbox (seed already has a dev one); a **dev login user** in `auth.users` bridged via `platform.oidc_subjects.user_id` + a `tenant_memberships` row (role `analysis_author`). Test credentials shared via `apps/web/.env.example` placeholders + a note in the populating agent's PR.

**4.5 ROIs (optional but preferred)** — `priority.roi_runs` + `priority.rois` (→ `current_rois`) so the latent layer shows real ROIs instead of synthetic cells.

**4.6 Analysis enablement** — `analysis.analysis_providers` + `analysis_definitions` (`budget.route`, `budget.cluster`, `inspection.latent`) + active `analysis_definition_versions` + `provider_capability_snapshots` so `analysis_runs` inserts satisfy FKs.

> **Presentation config (app-owned, not DB):** slug→{color,label-es,unit,step} map in `apps/web/src/lib/types-presentation.ts` mirroring the reference `TYPES` array (pothole `#e5484d`, open_drain `#2f64e6`, broken_light `#f5a623`, missing_signage `#7c3aed`, damaged_sidewalk `#0f9b8e`). Render is data-driven over `app_observation_types_counts`, falling back to a neutral color for unknown slugs.

---

## 5. Auth & login flow

- Supabase Auth email+password. `LoginPage` (`/login`) — branded "Vialia" card (reuse the reference brand mark + palette), shadcn `Card`/`Input`/`Button`/`Form`, error states via `clarify`/`harden` skills.
- `AuthProvider` (context) wraps the app; `useSession()` exposes session + the resolved tenant (`app_active_tenant()`); `RequireAuth` route guard redirects unauthenticated users to `/login`; the map lives at `/`.
- On login, call `app_active_tenant()`; if the user has no membership, show a clear empty state (not a crash).
- Sign-out control in the Layers panel header area.

---

## 6. File structure (`apps/web`)

```
apps/web/
  package.json, tsconfig.json, vite.config.ts, index.html, .env.example
  tailwind.config.ts, postcss.config.js, components.json   # shadcn
  src/
    main.tsx, App.tsx, router.tsx, index.css               # tokens/fonts
    lib/
      supabase.ts            # typed client (anon key) — public schema only
      auth.tsx               # AuthProvider, useSession, RequireAuth
      api.ts                 # typed wrappers over §2/§3 RPCs (TanStack Query hooks)
      types-presentation.ts  # slug→color/unit/step/label
      money.ts               # $() formatter
      geo.ts                 # haversine, grid helpers (shared w/ map)
    pages/
      LoginPage.tsx
      MapPage.tsx            # composes the four surfaces + MapCanvas
    components/
      MapCanvas.tsx          # leaflet init + drawPins/drawGrid/drawResult/drawRois/fitTo
      LayersPanel.tsx
      AgentPanel.tsx         # feed, chips, command input, parseCommand
      AnalysisDock.tsx       # launcher + dock + controls + cost popover
      HistoryPopover.tsx
      ObservationCard.tsx
      ui/                    # shadcn-generated primitives
    state/
      useMapState.ts         # showPins/showHeat/activeTypes/selected/...
      useAnalysis.ts         # runs/activeId/drawer/cost state + RPC mutations
  tests/
    integration/             # vitest — hit live RPCs with a test session
    e2e/                     # playwright — login→map→analysis flows
  packages/db-types regenerated after 0200/0201 land
```

---

## 7. Workstreams & tasks

Each task ends with an independently testable deliverable and a commit. Foundations (W0) are sequential and block the rest; W1–W5 parallelize on disjoint files after W0; W6 is the closing gate.

### W0 — Foundations (sequential; blocks all)

**Task 0.1 — Read/analysis API migrations + type regen.**
- Files: Create `supabase/migrations/0200_app_read_api.sql`, `0201_app_analysis_api.sql`; Test `supabase/tests/0200_app_api.test.sql`; Modify `packages/db-types/database.ts` (regen with `public` exposed).
- Steps: read `0006`,`0011`,`0012`,`0007–0009`; write the §2/§3 functions; write a pgTAP/SQL test that, **with the DB Data Contract present**, asserts each function returns the expected columns and ≥0 rows and that `app_run_analysis('route',3000000,...)` persists one `analysis_runs`+`analysis_results`; apply via Supabase MCP `apply_migration`; regenerate types via MCP `generate_typescript_types` (request `public` + verify the new functions appear) and overwrite `database.ts`. Commit.
- Produces: typed `Database['public']['Functions']` for all §2/§3 RPCs.

**Task 0.2 — App scaffold + design tokens + shadcn.**
- Files: all `apps/web` config + `src/index.css`, `src/main.tsx`, `src/App.tsx`, `src/router.tsx`, `lib/supabase.ts`, `lib/money.ts`, `lib/types-presentation.ts`.
- Steps: `bun create vite apps/web --template react-ts`; add Tailwind + `shadcn init` (`components.json`); install leaflet/react-leaflet, supabase-js, @tanstack/react-query, react-router; load Public Sans + IBM Plex Mono; encode palette tokens; build the typed supabase client importing `packages/db-types`; smoke test (`vitest`) that the client constructs and `money.$(1800)` === `"$1,800"`. Commit.
- Consumes: 0.1 types. Produces: `supabase` client, `$()`, presentation map, router shell.

**Task 0.3 — Auth + login + guard (W5 folded into foundations because everything is gated by it).**
- Files: `lib/auth.tsx`, `pages/LoginPage.tsx`, `components/ui/*` (form/card/input/button), `tests/integration/auth.test.ts`.
- Steps: AuthProvider/useSession/RequireAuth; LoginPage UI to reference brand; integration test: sign in with the DB-contract dev user, assert session + `app_active_tenant()` returns a tenant. Commit.

### W1 — Map canvas & overlays (consumes 0.1–0.2)
**Task 1.1** base map (`MapCanvas` leaflet init, CARTO light tiles, boundary polygon, zoom bottom-right, the reference's Leaflet guards) + render real observations as pins via `app_map_observations` (scored colored by `weightColor`, pending dashed) + click → select. Integration test: `app_map_observations` returns rows for the test tenant; component test: N rows → N markers.
**Task 1.2** heat grid layer from `app_priority_cells` (port `heat()` color ramp, opacity by weight share) + Layers-panel heat toggle.
**Task 1.3** ROI layer from `app_current_rois` (dashed purple rectangles/centroid labels), shown in latent mode.
**Task 1.4** `fitTo` with dock-aware padding; basemap switch (light/voyager/dark) wired to accent/prop.

### W2 — Layers panel (consumes 0.2, 1.x)
**Task 2.1** `LayersPanel`: brand header + LIVE pulse + last-sweep; Instances/Priority-heat toggles; data-driven per-type filter rows (dot, label, LATENT chip, count) from `app_observation_types_counts`; pending legend; sign-out. Recompute hooks update map + active analysis. Integration test: counts endpoint shape; component test: toggling a type filters markers and re-queries the active run.

### W3 — Agent panel & NL commands (consumes 0.2, W4 RPCs)
**Task 3.1** `AgentPanel`: scrollable feed (user/agent text + analysis cards w/ status pill, spinner, result summary, "open in analysis view"), suggestion chips, command input. **Task 3.2** port `parseCommand` (budget `$Xm/k`, latent/cluster/route intent, type-only filters, ES/EN synonyms) → dispatch to `useAnalysis`. Integration test: each chip command produces a persisted run of the right kind; unit test: `parseCommand` table of inputs→intents.

### W4 — Analysis dock & execution (consumes 0.1 analysis RPCs)
**Task 4.1** `useAnalysis` state + RPC mutations (`app_run_analysis`, `app_update_run_budget`, `app_run_latent`, `app_list_runs`, `app_get_run`) via TanStack Query; debounced budget slider; cost-basis local overrides passed to RPC. **Task 4.2** `AnalysisDock` UI: launcher, non-modal dock, Route/Group segment, budget slider + formatted value, cost-basis popover (per active type, ±step), stats grid, ordered stops/members list (click→locate), collapse/close, latent variant (purple, ROIs/hypotheses). **Task 4.3** `HistoryPopover`. Integration tests: `app_run_analysis('route',...)` persists run+result and returns stats with `count≤40` and `spent≤budget`; `app_run_latent` returns ≤6 ROIs; `app_list_runs` returns them newest-first.

### W5 — (folded into Task 0.3)

### W6 — Integration & E2E gate (the closing requirement)
**Task 6.1** Vitest integration suite green for every read/analysis RPC against the live project with the test session (no skips). **Task 6.2** Playwright E2E: `/login` → sign in → map renders with pins+heat → toggle a type → run "best pothole route under $3M" via chip → dock shows stats + ordered stops + route polyline on map → open latent scan → ROIs render → select a pin → ObservationCard shows detail → sign out. **Task 6.3** Visual-fidelity pass against the reference (side-by-side screenshot) using `polish`/`critique` skills; fix spacing/typography/color drift. **Done only when 6.1–6.3 all pass with shown output.**

---

## 8. Self-review (spec coverage)

- Login page → §5 + Task 0.3. ✓
- shadcn → Tech Stack + 0.2 + ui/. ✓
- Live Supabase wiring → §2/§3 API layer + W1/W3/W4. ✓
- Schema compatibility → §2/§3 read 0006/0011/0012/0007-0009; DoD #1; W6.1. ✓
- Visual fidelity → DoD #2; reference cited per surface; Task 6.3. ✓
- Integration tests for all features → DoD #3; W6. ✓
- DB populated by another agent → §4 contract; no app-side seed. ✓
- Vite SPA → §6 + 0.2. ✓
- Open risks to watch: exact RLS predicates in 0012 (read before 0.1); whether catalog needs an explicit `latent`/color column vs app-side map (defaulted app-side); analysis FK prerequisites (§4.6) must exist before `app_run_analysis` inserts succeed — if missing, 0201 should create minimal provider/definition rows itself, idempotently.
