# Planning Service Integration — Design

**Date:** 2026-06-21
**Status:** Approved (brainstorm)
**Scope:** Replace the mock planning engine with a real optimizer that adapts the
`ActionableOptimization/` deliverable, behind the unchanged `/v1/planning` HTTP contract.

## Goal

Turn the offline `ActionableOptimization/` pipeline (cluster potholes → weight by
traffic → group into capacity-bounded trips → select the most critical within a
budget) into a real `PlanningEngine` bound to the already-live Fly API
(`services/api`), so the frontend's budget-slider action plan is driven by the real
cost model and trip grouping instead of the volume-only mock.

## Context (what exists today)

- `services/api/src/citycrawl_api/modules/planning/` holds the planning contract:
  - `protocol.py` — `PlanningEngine` (`name`, `optimize`, `cluster_priorities`).
  - `models.py` — `AnalysisRequest`, `PlanResult`, `Squad`, `TopCritical`,
    `ClusteredPriority`, etc. (camelCase wire aliases).
  - `mock.py` — `MockPlanningEngine` (volume-only ranking, flat `MOCK_UNIT_COST`
    budget proxy, `cluster_indices` squads). Labelled mock.
  - `geometry.py` — reusable `haversine`, `centroid_of`, `cluster_indices`,
    `convex_hull`, `LatLng`.
  - `routers/planning.py` — `POST /v1/planning/optimize`,
    `POST /v1/planning/priorities:cluster`; binds one `_engine`; reports it via the
    `X-Planning-Engine` response header.
- The **frontend already calls these endpoints live** (`frontend/src/lib/citycrawlApi.ts`
  → `optimizePlan` / `clusterPriorities`; `MapPage.tsx:296` debounces `/optimize` on
  the budget slider). No client-side mock remains.
- `ActionableOptimization/pipeline/` (the deliverable): `clustering.py` (cluster
  along named streets), `traffic.py` (TomTom flow → weekly volume + weight),
  `superclustering.py` (greedy nearest-centroid, point-capped), `pipeline.py`
  (orchestration + greedy budget selection + `within_budget`).
- `config.Settings` has a clean env-driven settings object; `db_url`, `local_root`,
  operator-key auth all already present.

## Key decisions

1. **Engine-only, contract preserved.** Implement a real engine behind the existing
   `AnalysisRequest`/`PlanResult`/`ClusteredPriority` shapes. **No frontend changes,
   no wire-shape changes.** The deliverable's outputs map onto the existing fields.
2. **Spatial clustering, not street-name clustering.** No observation carries a
   `street_name` in the app. The deliverable's "cluster along a street" step is
   replaced by proximity-based clustering (ports the anchor/near/far distance logic
   from `clustering.py`, keyed on lat/lng instead of grouping by street). No new data.
3. **Traffic via a cached layer, never live in the request.** The frontend re-calls
   `/optimize` on every debounced slider tick, so synchronous, rate-limited TomTom
   calls are unacceptable. `/optimize` reads a precomputed traffic cache; a separate
   warm/refresh path populates it from TomTom. Cache miss → neutral fallback factor,
   so the endpoint is always fast and deterministic. The TomTom key (provided
   out-of-band) lives in `config.Settings` / `.env` as a secret, never committed.
4. **`squad_count` becomes advisory for `optimize`.** The deliverable's capacity cap
   determines the number of trips/squads, so `request.squad_count` no longer forces K
   squads in `optimize`. It still drives `cluster_priorities` (the priority overlay).
   This is invisible to the wire shape.
5. **Engine is config-selectable.** `PLANNING_ENGINE=optimization|mock` (default
   `optimization`); the mock is retained as a fallback/baseline and for parity tests.

## Architecture

```
modules/planning/
  protocol.py            # unchanged
  models.py              # unchanged wire shapes (+ a few internal helper constants)
  geometry.py            # reused: haversine, centroid_of, cluster_indices, convex_hull
  mock.py                # retained (baseline / fallback)
  engine.py              # NEW: OptimizationPlanningEngine (implements PlanningEngine)
  optimization/          # NEW: vendored & adapted deliverable logic, pure functions
    clustering.py        #   proximity clustering (street-name step removed)
    superclustering.py   #   greedy nearest-centroid, point-capped trips
    cost.py              #   cost = 2000 + 8000 * total_volume; budget greedy select
  traffic.py             # NEW: TrafficProvider (cached read + warm/refresh from TomTom)
routers/planning.py      # binds engine from config; header already present
config.py                # + tomtom_api_key, planning_engine, traffic cache settings
```

### Engine: `optimize(request) -> PlanResult`

1. **Eligible points** = `request.points` with `volume > 0` (region/type filtering is
   already applied upstream by the frontend, as today).
2. **Proximity clustering** → fine clusters of adjacent potholes (ports
   `clustering.py` anchor/near/far thresholds on haversine distance).
3. **Traffic enrichment** per cluster centroid via `TrafficProvider.lookup(lat, lng)`
   → `vehicles_week`, `free_flow_speed`. Cluster
   `weight = total_volume * vehicles_week * free_flow_speed` (deliverable formula).
   Miss → neutral defaults.
4. **Capacity-constrained superclustering** (ports `superclustering.py`): greedy
   nearest-centroid grouping with a `max_points` cap → superclusters = trips.
5. **Cost** per supercluster: `2000 + 8000 * total_volume`.
6. **Budget selection**: greedy by descending `total_weight` until the next
   supercluster would exceed `request.budget` → selected = `within_budget` trips.

### Output mapping (deliverable → `PlanResult`)

| Deliverable | `PlanResult` field |
|---|---|
| selected supercluster | a `Squad` |
| `total_weight` (normalized 0..1) | `Squad.weight` |
| `cost = 2000 + 8000·vol` | `Squad.cost` |
| member point ids | `Squad.members` |
| convex hull of members (`convex_hull`) | `Squad.polygon` |
| centroid (`centroid_of`) | `Squad.centroid` |
| member count | `Squad.count` |
| # selected superclusters | `squad_count_used` |
| points of selected trips, ranked by weight | `top_critical[]` (+ real `cost` share, `rank`) |
| Σ selected cost | `stats.spent` |
| Σ points / distinct `district_cve` / Σ volume | `stats.count` / `regions` / `volume` |

`cluster_priorities(points, k)`: reuse proximity clustering + traffic weighting,
return `ClusteredPriority[]` (normalized weight, hull, centroid) — a real upgrade
over the mock's volume-only weight, same shape.

### Traffic cache

- `TrafficProvider`: a persistent cache keyed by lat/lng snapped to a grid
  (~3 decimals ≈ 100 m). Stored under `local_root` (JSON/SQLite); `optimize` only
  reads it.
- **Warm path**: a CLI command (`planning warm-traffic`, optionally also an
  operator-auth endpoint) iterates the tenant's observation locations (via `db_url`),
  calls TomTom (ports `traffic.py`: FRC→lanes, current/free-flow speed → hourly →
  weekly volume), and writes the cache with the configured request delay.
- **Fallback**: on miss, return a neutral `vehicles_week`/`free_flow_speed` constant
  so weight stays well-defined and `/optimize` never blocks on the network.

## Testing

- **Unit (optimization):** fixed point set → assert capacity cap honored, cost
  formula exact, budget greedy selection (`spent ≤ budget`, descending-weight order),
  deterministic output ordering.
- **Engine contract:** `optimize` returns a schema-valid `PlanResult` and
  `cluster_priorities` a valid `ClusteredPriority[]`; `engine.name == "optimization"`.
- **Traffic provider:** cache hit returns stored value; miss returns fallback; assert
  **no network call** inside `optimize` (inject a fake provider).
- **Router:** with `PLANNING_ENGINE=optimization`, `/optimize` responds 200 with the
  `X-Planning-Engine: optimization` header; mock still selectable.
- **Sanity vs. mock:** with neutral traffic + trivial cost, selection ranks
  sensibly against the mock baseline on a shared fixture.

## Out of scope

- Frontend/UI changes; new wire fields (explicit trips, `within_budget` flags,
  traffic metrics) — deferred (would be a contract-extending follow-up).
- Reverse-geocoding observations to street names.
- Live per-request TomTom calls.
- Persisting plans to `analysis.analysis_runs` (the API is stateless here, as today).

## Open risks

- **Cache coldness:** first run before a warm pass uses fallback factors only
  (weights degrade to volume-driven). Mitigation: run `warm-traffic` once at deploy;
  document it in the API runbook.
- **TomTom quota / key rotation:** key is a secret in `Settings`; warm job respects
  `request_delay`; never called from `/optimize`.
- **`squad_count` semantics shift:** documented (decision 4); revisit if the dock
  needs to force K squads.
