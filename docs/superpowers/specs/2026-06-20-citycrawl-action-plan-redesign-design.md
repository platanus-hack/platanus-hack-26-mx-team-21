# CityCrawl — Action-Plan Redesign (design)

> **Status:** approved-pending-review (2026-06-20, branch `feat/city-priority-map-app`).
> Supersedes the analysis portions of `2026-06-20-city-priority-map-application.md`. The
> app shell, auth, read-API layer, and map foundations from that plan stand; this spec
> changes the **analysis model**, **map priority visualization**, **surfaces**, and the
> **brand**.

## Goal

Reorient the `apps/web` map app around the analysis team's new model. The analysis is no
longer a choice between route/cluster/latent algorithms over a single observation set. It
is now: **pick an issue type → set a budget → narrow the region → generate an action
plan**. The plan is the deliverable. Priorities are no longer computed per point; points
are decorated by their own metadata (volume), and spatial priority is expressed as
irregular **clusters** (which also drive squad assignment). Rebrand from "Vialia" to
**CityCrawl**.

## 1. Rebrand: Vialia → CityCrawl

Mechanical sweep, UI stays Spanish:

- `index.html` — `<title>` → `CityCrawl · Mapa de prioridades CDMX`.
- `package.json` — `name` → `@citycrawl/web`.
- `src/components/LayersPanel.tsx` — brand header text → `CityCrawl`.
- `src/pages/LoginPage.tsx` — brand mark text → `CityCrawl`; demo email/creds domain
  (`@vialia.test` → `@citycrawl.test`) **only if the seeded auth user actually uses that
  domain** — otherwise leave the real seeded credentials untouched and only change the
  visible brand. Verify against the seed before editing.
- `src/index.css` — leading comment.

No data/schema names change (DB schemas `vision`/`priority`/`geo`/`analysis` are unaffected).

## 2. Analysis model

### 2.1 Inputs (what the "worker" receives)

A single analysis request:

```
{
  issueType: 'pothole',          // only potholes active now; others disabled in UI
  budget: number,                // MXN
  regionFilter: string[],        // included INEGI alcaldía cve_mun codes (empty = all)
  squadCount?: number,           // optional override; omitted = module default (a constant)
  costs: Record<slug, number>,   // cost-basis config — collected by the UI, passed
                                 // THROUGH to the module; the frontend does not compute
                                 // monetary cost from it
  points: Array<{                // region-filtered pothole locations WITH volume
    id, lat, lng, slug, volume, zone, districtCve
  }>
}
```

The frontend assembles `points` by filtering the loaded observations to the chosen issue
type and `regionFilter`, attaching each point's volume metadata (see §3). The frontend's
contribution is **volumes + budget + region + cost-basis config**; turning those into
monetary costs and an optimal selection is the optimization module's job.

### 2.2 Output (the action plan)

One combined result (no more `route`/`cluster`/`latent` kinds):

```
{
  issueType, budget, regionFilter, squadCountUsed,
  topCritical: Array<{ id, slug, lat, lng, volume, cost, zone, rank }>,
  squads: Array<{
    idx, color, members: string[],     // pothole ids in this squad's cluster
    polygon: [lat,lng][],              // convex hull for map rendering
    centroid: { lat, lng },
    cost, count
  }>,
  stats: { spent, count, squads, regions, volume, budgetPct }
}
```

- **topCritical** — potholes most worth attending within budget, ranked by criticality.
- **squads** — the in-budget potholes grouped into clusters; **one squad per cluster**.
- `cost`/`spent` are **module outputs** (placeholder in the mock — see §2.3), not values
  the frontend computes.

### 2.3 Mock algorithm (`src/lib/analysis.ts`, reshaped behind the existing seam)

This is a deliberate **placeholder for the optimization module** — it does NOT model
monetary cost. The real module computes costs and the optimal selection later; this mock
only needs to return a plausible, interactive plan.

1. **Eligible** = points (already region- and type-filtered) with a known `volume`.
2. **Criticality** ranks by volume (larger/worse first) → ordered candidate list.
3. **Budget selection** — the mock applies a trivial throwaway proxy (a flat nominal
   per pothole) solely so the budget slider visibly bounds the selection. **No cost model
   is designed here; real monetary-cost computation is the optimization module's job and is
   deferred.** Selected set → `topCritical`.
4. **Cluster** the selected set into `K` squads, where `K = squadCount` if the user
   overrode it, else `DEFAULT_SQUADS` (a constant in `types.ts`). Lightweight client-side
   clusterer (k-means-style on lat/lng, or greedy agglomeration) — a stand-in for the
   module's DBSCAN. Each cluster → one squad with a **convex-hull polygon** (monotone-chain
   helper in `geo.ts`), centroid, count, and a distinct color.
5. **stats** = count, #squads, #distinct regions, total volume, plus placeholder
   `spent`/`budgetPct` (faked by the mock, replaced by the real module).

The function stays pure and swappable; the real Cloudflare-Worker module plugs in later by
replacing this one call.

## 3. Read-API change (volume metadata)

Pins must decorate by real volume, not computed priority. Volume currently appears only in
`app_observation_detail`. Add it to the map list:

- New migration `supabase/migrations/0201_app_map_volume.sql`: `create or replace`
  `public.app_map_observations()` to also return `volume numeric` (and keep all existing
  columns), derived with the **same quantity-attribute lateral join** used by
  `app_observation_detail` (mirror its definition lookup; no new tables).
- Regenerate `packages/db-types/database.ts` (MCP `generate_typescript_types`, `public`).
- `weight` stays in the payload (still used for the optional risk-ROI/legacy paths) but is
  **no longer** the pin decoration driver.

**INEGI region filter** needs no new data: `app_map_observations.district_cve` is already
the INEGI `cve_mun`. The frontend derives the region list (distinct `districtCve` +
`districtName`) from the loaded observations.

## 4. Map decoration & layers (`MapCanvas.tsx`, `geo.ts`)

Priorities are no longer computed; the map shows three independent things:

1. **Pins by volume** — color/size ramp by each pothole's `volume` (replaces `weightColor`
   as the driver). Pending pins (no volume) keep the neutral dashed style.
2. **Cluster zones** (replaces the grid heatmap) — irregular convex-hull polygons over
   clustered **active** potholes; the Layers toggle "Mapa de calor"/"Priority heat"
   becomes **"Zonas (clústeres)"**. This is the always-available spatial-priority view.
   Same clustering family as the plan's squads (plan = budget-funded subset).
3. **Risk-ROIs (external)** — KEPT as a first-class feature. Render `app_current_rois`
   (the external-dataset risk polygons: crime/crash/flooding/…) as a toggleable layer with
   their dashed-polygon + label styling. No longer gated behind an "inspection-scan"
   analysis run.

While a plan is **previewing**: draw that plan's squad clusters (color per squad) and
numbered top-critical markers on top; `fitTo` stays dock/panel-aware.

## 5. Surfaces

- **Bottom dock = launcher + config** (`AnalysisDock.tsx`, reshaped): issue-type selector
  (Baches active; other types disabled "Próximamente"), budget slider, **region filter**
  (multi-select alcaldías derived from data), **squad override** (auto by default), the
  kept **cost-basis** popover, and **"Generar plan."** Changing budget/region/squads/costs
  recomputes the active plan live.
- **Right panel** (`AgentPanel.tsx`): the agent intro + quick-action chips by default;
  **swaps to the Action-Plan preview while a plan is active** — stats grid, top-critical
  list (click → locate), and per-squad cluster breakdown (click → locate/zoom). A
  close/back control returns it to the agent. (The plan does not permanently replace the
  agent panel — only during preview.)
- **History popover** (`HistoryPopover.tsx`): keeps listing past plans (relabeled to the
  single plan kind); selecting one re-opens its preview.
- **Layers panel** (`LayersPanel.tsx`): volume legend; toggles for Instances (pins),
  "Zonas (clústeres)", and "Zonas de riesgo (externas)"; per-type filter (potholes
  meaningful now). CityCrawl brand header + sign-out.

## 6. Removed / changed scope

- Removed: the `route`/`cluster`/`latent` analysis-kind segmentation, the
  inspection-scan-as-analysis flow, and the grid heatmap renderer.
- Kept (relocated): risk-ROIs become a standalone layer; cost basis; budget; history.
- `parseCommand`/NL agent input stays disabled (chips remain).

## 7. Testing (light, per working style)

Typecheck + production build pass; headless-Chrome screenshots of each surface (login,
map with volume pins + cluster zones + risk-ROIs, config dock, plan preview in right
panel, history, observation card). Reshape/replace any existing analysis unit tests to the
new model. No new E2E suite.

## 8. File-level change list

- `index.html`, `package.json`, `src/index.css` — rebrand.
- `supabase/migrations/0201_app_map_volume.sql` (new) + `packages/db-types/database.ts`
  (regen) — volume on the map payload.
- `src/lib/types.ts` — add `volume` to `Observation`; new analysis request/result types;
  region/squad fields; keep `DEFAULT_COSTS`.
- `src/lib/analysis.ts` — reshaped mock (top-critical + cluster→squad); drop kind union.
- `src/lib/geo.ts` — convex-hull + clustering helpers; volume color/size ramp.
- `src/components/MapCanvas.tsx` — pins-by-volume; cluster-zones layer; risk-ROI layer;
  plan-preview overlay.
- `src/components/AnalysisDock.tsx` — launcher+config (issue type, region filter, squad
  override, cost basis, generate).
- `src/components/AgentPanel.tsx` — agent ↔ action-plan-preview swap.
- `src/components/LayersPanel.tsx` — brand, new toggles, volume legend.
- `src/components/HistoryPopover.tsx` — single plan kind.
- `src/pages/MapPage.tsx` — orchestration: region/squad state, region-filtered points with
  volume, plan lifecycle, layer toggles.

## 9. Open assumptions (call out if wrong)

- INEGI region = alcaldía (`cve_mun`) granularity is sufficient (no AGEB-level filter).
- One squad == one cluster; squads are a presentation of clusters, not a separate solver.
- Risk-ROIs use the already-deployed `app_current_rois`; no new external-data work here.
- **Monetary cost + the real selection optimizer are out of scope** — owned by the
  optimization module. The frontend supplies volumes/budget/region/cost-config and renders
  the returned plan; the mock fakes costs as throwaway placeholders.
