# Planning Service Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `MockPlanningEngine` with a real `OptimizationPlanningEngine` that adapts the `ActionableOptimization/` deliverable (proximity clustering → traffic-weighted criticality → capacity-bounded trip grouping → budget selection), bound behind the unchanged `/v1/planning` HTTP contract.

**Architecture:** Vendor the deliverable's clustering/superclustering/cost logic into `services/api/src/citycrawl_api/modules/planning/optimization/` as pure functions over `list[AnalysisPoint]` (no pandas in the request path). Traffic comes from a read-only cached `TrafficProvider` warmed offline from TomTom via a Typer CLI. The router binds the engine from config (`PLANNING_ENGINE`), keeping the mock as a selectable baseline. Wire shapes (`AnalysisRequest`/`PlanResult`/`ClusteredPriority`) and the frontend are untouched.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, httpx (TomTom calls), numpy (PCA/centroid), Typer (CLI), pytest. All already in `services/api/pyproject.toml`.

## Global Constraints

- **Engine-only, contract preserved.** Do NOT change `protocol.py`, the wire shapes in `models.py`, `routers/planning.py`'s function signatures, or any frontend file. The only router change is how `_engine` is constructed.
- **No live TomTom in `/optimize`.** `TrafficProvider.lookup` is read-only and must make zero network calls. TomTom is only called from the warm path (CLI / `warm`).
- **TomTom key is a secret.** It lives in `config.Settings.tomtom_api_key` from `.env`; never hardcode it, never commit a real key. `.env.example` gets an empty placeholder only.
- **Pure functions, no pandas in the engine.** The deliverable uses pandas DataFrames; the ports here operate on plain Python lists + numpy only.
- **Reuse existing geometry.** Use `citycrawl_api.modules.planning.geometry`: `LatLng`, `haversine`, `centroid_of`, `convex_hull`. Do not re-implement them.
- **Determinism.** Given the same request + cache, `optimize` must return identical output (stable sort ties by input order).
- **Run tests from `services/api/`** with the project venv: `cd services/api && .venv/bin/pytest`.

---

## File Structure

```
services/api/src/citycrawl_api/
  modules/planning/
    optimization/
      __init__.py          # NEW (empty package marker)
      clustering.py        # NEW: cluster_by_proximity
      superclustering.py   # NEW: build_superclusters
      cost.py              # NEW: supercluster_cost, select_within_budget, constants
    traffic.py             # NEW: TrafficSample, TrafficProvider, tomtom_fetch, DEFAULT_TRAFFIC
    engine.py              # NEW: OptimizationPlanningEngine
    cli.py                 # NEW: Typer app — warm-traffic command
  config.py                # MODIFY: + tomtom_api_key, planning_engine, traffic_* fields
  routers/planning.py      # MODIFY: build engine from settings
services/api/
  pyproject.toml           # MODIFY: + [project.scripts] citycrawl-planning
  .env.example             # MODIFY: + TOMTOM_API_KEY, PLANNING_ENGINE
  tests/unit/test_planning_clustering.py        # NEW
  tests/unit/test_planning_superclustering.py   # NEW
  tests/unit/test_planning_cost.py              # NEW
  tests/unit/test_planning_traffic.py           # NEW
  tests/unit/test_planning_engine.py            # NEW
  tests/integration/test_planning_optimization_route.py  # NEW
  tests/unit/test_planning_cli.py               # NEW
```

---

## Task 1: Proximity clustering

Replaces the deliverable's street-name grouping with fixed-radius greedy spatial clustering (connected components under one haversine threshold). Each cluster is a set of adjacent potholes.

**Files:**
- Create: `services/api/src/citycrawl_api/modules/planning/optimization/__init__.py`
- Create: `services/api/src/citycrawl_api/modules/planning/optimization/clustering.py`
- Test: `services/api/tests/unit/test_planning_clustering.py`

**Interfaces:**
- Consumes: `citycrawl_api.modules.planning.geometry.haversine`; `citycrawl_api.modules.planning.models.AnalysisPoint`.
- Produces: `cluster_by_proximity(points: list[AnalysisPoint], radius_m: float = 100.0) -> list[list[int]]` — clusters as lists of indices into `points`, every index assigned exactly once, deterministic (anchors taken in input order).

- [ ] **Step 1: Write the failing test**

```python
# services/api/tests/unit/test_planning_clustering.py
"""Proximity clustering: fixed-radius greedy grouping replacing street-name grouping."""
from citycrawl_api.modules.planning.models import AnalysisPoint
from citycrawl_api.modules.planning.optimization.clustering import cluster_by_proximity


def _pt(i: int, lat: float, lng: float) -> AnalysisPoint:
    return AnalysisPoint(id=f"p{i}", lat=lat, lng=lng, slug="pothole", volume=1.0)


def test_empty_input_returns_empty():
    assert cluster_by_proximity([]) == []


def test_two_near_points_one_cluster():
    # ~11 m apart at this latitude (0.0001 deg lng).
    pts = [_pt(0, 19.4, -99.1), _pt(1, 19.4, -99.0999)]
    groups = cluster_by_proximity(pts, radius_m=100.0)
    assert groups == [[0, 1]]


def test_far_points_separate_clusters():
    # ~1.1 km apart (0.01 deg lat) → two clusters at radius 100 m.
    pts = [_pt(0, 19.40, -99.1), _pt(1, 19.41, -99.1)]
    groups = cluster_by_proximity(pts, radius_m=100.0)
    assert sorted(map(sorted, groups)) == [[0], [1]]


def test_every_point_assigned_once():
    pts = [_pt(i, 19.4 + i * 0.02, -99.1) for i in range(6)]
    groups = cluster_by_proximity(pts, radius_m=100.0)
    flat = sorted(i for g in groups for i in g)
    assert flat == list(range(6))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/api && .venv/bin/pytest tests/unit/test_planning_clustering.py -v`
Expected: FAIL with `ModuleNotFoundError: ...optimization.clustering`

- [ ] **Step 3: Write minimal implementation**

```python
# services/api/src/citycrawl_api/modules/planning/optimization/__init__.py
"""Pure-function ports of the ActionableOptimization pipeline (clustering, superclustering, cost)."""
```

```python
# services/api/src/citycrawl_api/modules/planning/optimization/clustering.py
"""Fixed-radius greedy proximity clustering.

Adapts ActionableOptimization/pipeline/clustering.py: the original grouped points by
street name and walked them along a PCA axis. No observation carries a street name in
this app, so we replace that with connected-components grouping under a single haversine
radius — adjacent potholes merge into one fine cluster. Deterministic: anchors are taken
in input order, and each unassigned point within `radius_m` of the growing cluster's
already-assigned members is absorbed (single-linkage chaining)."""
from __future__ import annotations

from citycrawl_api.modules.planning.geometry import haversine
from citycrawl_api.modules.planning.models import AnalysisPoint


def cluster_by_proximity(
    points: list[AnalysisPoint], radius_m: float = 100.0
) -> list[list[int]]:
    n = len(points)
    assigned = [False] * n
    clusters: list[list[int]] = []

    for seed in range(n):
        if assigned[seed]:
            continue
        cluster = [seed]
        assigned[seed] = True
        frontier = [seed]
        while frontier:
            i = frontier.pop()
            for j in range(n):
                if assigned[j]:
                    continue
                if haversine(points[i].lat, points[i].lng, points[j].lat, points[j].lng) <= radius_m:
                    assigned[j] = True
                    cluster.append(j)
                    frontier.append(j)
        clusters.append(sorted(cluster))
    return clusters
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/api && .venv/bin/pytest tests/unit/test_planning_clustering.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add services/api/src/citycrawl_api/modules/planning/optimization/__init__.py \
        services/api/src/citycrawl_api/modules/planning/optimization/clustering.py \
        services/api/tests/unit/test_planning_clustering.py
git commit -m "feat(planning): proximity clustering port for optimization engine"
```

---

## Task 2: Capacity-constrained superclustering

Groups fine clusters into superclusters (trips), each capped at `max_points` total original points, via greedy nearest-centroid. Ports `ActionableOptimization/pipeline/superclustering.py`.

**Files:**
- Create: `services/api/src/citycrawl_api/modules/planning/optimization/superclustering.py`
- Test: `services/api/tests/unit/test_planning_superclustering.py`

**Interfaces:**
- Consumes: `citycrawl_api.modules.planning.geometry.haversine`.
- Produces: `build_superclusters(centroids: list[tuple[float, float]], sizes: list[int], max_points: int = 12) -> list[list[int]]` — superclusters as lists of cluster indices (indexing into `centroids`/`sizes`), every cluster assigned once, deterministic.

- [ ] **Step 1: Write the failing test**

```python
# services/api/tests/unit/test_planning_superclustering.py
"""Capacity-constrained greedy nearest-centroid superclustering."""
from citycrawl_api.modules.planning.optimization.superclustering import build_superclusters


def test_empty_returns_empty():
    assert build_superclusters([], []) == []


def test_cap_forces_split():
    # Three clusters of 5 points each, cap 12 → first SC takes two (10), third alone.
    centroids = [(19.40, -99.1), (19.4001, -99.1), (19.4002, -99.1)]
    sizes = [5, 5, 5]
    sc = build_superclusters(centroids, sizes, max_points=12)
    assigned = sorted(i for g in sc for i in g)
    assert assigned == [0, 1, 2]            # all clusters placed
    assert all(sum(sizes[i] for i in g) <= 12 for g in sc)  # cap honored
    assert len(sc) == 2                     # 5+5 then 5


def test_single_cluster_over_cap_still_placed():
    # A cluster larger than the cap must still seed its own supercluster.
    sc = build_superclusters([(19.4, -99.1)], [20], max_points=12)
    assert sc == [[0]]


def test_nearest_centroid_growth():
    # Cluster 0 should absorb the nearer cluster 1 before the far cluster 2.
    centroids = [(19.40, -99.10), (19.4001, -99.10), (19.50, -99.10)]
    sizes = [1, 1, 1]
    sc = build_superclusters(centroids, sizes, max_points=12)
    # 0 and 1 are ~11 m apart; 2 is ~11 km away. All fit under cap → one SC, but the
    # growth order proves nearest-first. With cap high enough all merge:
    assert sorted(map(sorted, sc)) == [[0, 1, 2]]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/api && .venv/bin/pytest tests/unit/test_planning_superclustering.py -v`
Expected: FAIL with `ModuleNotFoundError: ...optimization.superclustering`

- [ ] **Step 3: Write minimal implementation**

```python
# services/api/src/citycrawl_api/modules/planning/optimization/superclustering.py
"""Greedy nearest-centroid supercluster builder (ports ActionableOptimization
superclustering.py). Seeds a supercluster with the first unassigned cluster, then
repeatedly absorbs the nearest unassigned cluster (by haversine to the running centroid)
that still fits under the point cap. A cluster larger than the cap seeds its own SC."""
from __future__ import annotations

from citycrawl_api.modules.planning.geometry import haversine


def build_superclusters(
    centroids: list[tuple[float, float]],
    sizes: list[int],
    max_points: int = 12,
) -> list[list[int]]:
    n = len(centroids)
    assigned = [False] * n
    superclusters: list[list[int]] = []

    while True:
        unassigned = [i for i in range(n) if not assigned[i]]
        if not unassigned:
            break
        seed = unassigned[0]
        assigned[seed] = True
        members = [seed]
        used = sizes[seed]

        while used < max_points:
            clat = sum(centroids[i][0] for i in members) / len(members)
            clon = sum(centroids[i][1] for i in members) / len(members)
            fits = [i for i in range(n) if not assigned[i] and sizes[i] <= max_points - used]
            if not fits:
                break
            best = min(fits, key=lambda i: haversine(clat, clon, centroids[i][0], centroids[i][1]))
            assigned[best] = True
            members.append(best)
            used += sizes[best]

        superclusters.append(sorted(members))
    return superclusters
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/api && .venv/bin/pytest tests/unit/test_planning_superclustering.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add services/api/src/citycrawl_api/modules/planning/optimization/superclustering.py \
        services/api/tests/unit/test_planning_superclustering.py
git commit -m "feat(planning): capacity-constrained superclustering port"
```

---

## Task 3: Cost model + budget selection

The deliverable's monetary model and greedy budget selection.

**Files:**
- Create: `services/api/src/citycrawl_api/modules/planning/optimization/cost.py`
- Test: `services/api/tests/unit/test_planning_cost.py`

**Interfaces:**
- Produces:
  - `TRIP_COST = 2000.0`, `VOLUME_COST = 8000.0` (module constants).
  - `supercluster_cost(total_volume: float) -> float` → `TRIP_COST + VOLUME_COST * total_volume`.
  - `select_within_budget(weights: list[float], costs: list[float], budget: float) -> list[int]` → indices of selected superclusters, greedy by descending `weights` (ties by index), including one while cumulative cost stays `<= budget`; returns indices **in descending-weight order**.

- [ ] **Step 1: Write the failing test**

```python
# services/api/tests/unit/test_planning_cost.py
"""Cost model (2000 + 8000·volume) and greedy budget selection."""
from citycrawl_api.modules.planning.optimization.cost import (
    TRIP_COST,
    VOLUME_COST,
    select_within_budget,
    supercluster_cost,
)


def test_cost_formula():
    assert supercluster_cost(0) == TRIP_COST
    assert supercluster_cost(3) == TRIP_COST + VOLUME_COST * 3
    assert (TRIP_COST, VOLUME_COST) == (2000.0, 8000.0)


def test_selection_descending_weight_within_budget():
    weights = [10.0, 50.0, 30.0]
    costs = [3000.0, 4000.0, 5000.0]
    # Budget 9000: pick 1 (w50,c4000) then 2 (w30,c5000)=9000; then 0 (c3000) busts.
    assert select_within_budget(weights, costs, 9000.0) == [1, 2]


def test_selection_skips_unaffordable_but_keeps_going():
    weights = [10.0, 50.0, 30.0]
    costs = [3000.0, 8000.0, 1000.0]
    # Budget 5000: 1 (c8000) skipped, 2 (c1000) taken, 0 (c3000) taken → [2, 0].
    assert select_within_budget(weights, costs, 5000.0) == [2, 0]


def test_zero_budget_selects_nothing():
    assert select_within_budget([1.0], [2000.0], 0.0) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/api && .venv/bin/pytest tests/unit/test_planning_cost.py -v`
Expected: FAIL with `ModuleNotFoundError: ...optimization.cost`

- [ ] **Step 3: Write minimal implementation**

```python
# services/api/src/citycrawl_api/modules/planning/optimization/cost.py
"""Monetary cost model and budget selection (ports ActionableOptimization pipeline.py).

Each supercluster (trip) costs a fixed mobilization fee plus a per-volume repair cost.
Superclusters are selected greedily in descending criticality (weight) order; a trip is
included only while the running spend stays within budget, but selection continues past
an unaffordable trip in case a cheaper one still fits."""
from __future__ import annotations

TRIP_COST = 2000.0
VOLUME_COST = 8000.0


def supercluster_cost(total_volume: float) -> float:
    return TRIP_COST + VOLUME_COST * total_volume


def select_within_budget(
    weights: list[float], costs: list[float], budget: float
) -> list[int]:
    order = sorted(range(len(weights)), key=lambda i: (-weights[i], i))
    spent = 0.0
    selected: list[int] = []
    for i in order:
        if spent + costs[i] <= budget:
            spent += costs[i]
            selected.append(i)
    return selected
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/api && .venv/bin/pytest tests/unit/test_planning_cost.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add services/api/src/citycrawl_api/modules/planning/optimization/cost.py \
        services/api/tests/unit/test_planning_cost.py
git commit -m "feat(planning): cost model and greedy budget selection"
```

---

## Task 4: Cached traffic provider

Read-only cache lookup (no network) + a `warm` path that populates the cache from a fetch callable, plus a TomTom-backed fetch factory. Ports `ActionableOptimization/pipeline/traffic.py` math.

**Files:**
- Create: `services/api/src/citycrawl_api/modules/planning/traffic.py`
- Test: `services/api/tests/unit/test_planning_traffic.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) TrafficSample(vehicles_week: float, free_flow_speed: float)`.
  - `DEFAULT_TRAFFIC: TrafficSample` — neutral fallback `TrafficSample(250_000.0, 50.0)`.
  - `TrafficFetch = Callable[[float, float], TrafficSample]` (type alias).
  - `class TrafficProvider`:
    - `__init__(self, cache_path: str, grid_decimals: int = 3, fallback: TrafficSample = DEFAULT_TRAFFIC)`
    - `lookup(self, lat: float, lng: float) -> TrafficSample` — snap to grid, return cached sample or `fallback`. **No network.**
    - `warm(self, locations: Iterable[tuple[float, float]], fetch: TrafficFetch, delay_s: float = 0.0) -> int` — populate + persist cache; returns number of distinct grid cells written.
  - `tomtom_fetch(api_key: str, *, client: httpx.Client | None = None) -> TrafficFetch` — fetch backed by the TomTom Flow API.

- [ ] **Step 1: Write the failing test**

```python
# services/api/tests/unit/test_planning_traffic.py
"""TrafficProvider: read-only cache with fallback; warm populates from a fetch callable."""
from citycrawl_api.modules.planning.traffic import (
    DEFAULT_TRAFFIC,
    TrafficProvider,
    TrafficSample,
)


def test_lookup_miss_returns_fallback(tmp_path):
    prov = TrafficProvider(cache_path=str(tmp_path / "c.json"))
    assert prov.lookup(19.4, -99.1) == DEFAULT_TRAFFIC


def test_warm_then_lookup_hits_cache(tmp_path):
    prov = TrafficProvider(cache_path=str(tmp_path / "c.json"), grid_decimals=3)
    sample = TrafficSample(vehicles_week=999.0, free_flow_speed=42.0)
    calls: list[tuple[float, float]] = []

    def fake_fetch(lat: float, lng: float) -> TrafficSample:
        calls.append((lat, lng))
        return sample

    written = prov.warm([(19.4001, -99.1002), (19.4002, -99.1001)], fake_fetch)
    # Both round to (19.4, -99.1) at 3 decimals → one grid cell, one fetch.
    assert written == 1
    assert len(calls) == 1
    assert prov.lookup(19.4, -99.1) == sample


def test_warm_persists_across_instances(tmp_path):
    path = str(tmp_path / "c.json")
    TrafficProvider(cache_path=path).warm(
        [(19.42, -99.13)], lambda la, lo: TrafficSample(7.0, 8.0)
    )
    # A fresh instance reads the same file.
    assert TrafficProvider(cache_path=path).lookup(19.42, -99.13) == TrafficSample(7.0, 8.0)


def test_lookup_makes_no_network_call(tmp_path, monkeypatch):
    import httpx

    def boom(*a, **k):
        raise AssertionError("lookup must not hit the network")

    monkeypatch.setattr(httpx, "get", boom)
    prov = TrafficProvider(cache_path=str(tmp_path / "c.json"))
    assert prov.lookup(1.0, 2.0) == DEFAULT_TRAFFIC
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/api && .venv/bin/pytest tests/unit/test_planning_traffic.py -v`
Expected: FAIL with `ModuleNotFoundError: ...planning.traffic`

- [ ] **Step 3: Write minimal implementation**

```python
# services/api/src/citycrawl_api/modules/planning/traffic.py
"""Cached traffic layer for the optimization engine.

`lookup` is read-only and never touches the network — `/optimize` runs on every debounced
budget-slider tick, so TomTom (rate-limited) is called only from the offline `warm` path.
On a cache miss `lookup` returns a neutral fallback so the criticality weight stays
well-defined. The TomTom math (FRC→lanes, current/free-flow speed → hourly → weekly volume)
is ported from ActionableOptimization/pipeline/traffic.py."""
from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import httpx

TrafficFetch = Callable[[float, float], "TrafficSample"]


@dataclass(frozen=True)
class TrafficSample:
    vehicles_week: float
    free_flow_speed: float


# Neutral citywide stand-in: ~3 lanes at 60% of free flow → ~272k veh/week, 50 km/h.
DEFAULT_TRAFFIC = TrafficSample(vehicles_week=250_000.0, free_flow_speed=50.0)

_FRC_LANE_MAP = {"FRC0": 6.0, "FRC1": 6.0, "FRC2": 4.0, "FRC3": 3.0, "FRC4": 2.0, "FRC5": 1.5, "FRC6": 1.0}
_CAPACITY_PER_LANE = 1800
_DAILY_HOURS = 12
_DAYS_PER_WEEK = 7


class TrafficProvider:
    def __init__(
        self,
        cache_path: str,
        grid_decimals: int = 3,
        fallback: TrafficSample = DEFAULT_TRAFFIC,
    ) -> None:
        self._path = Path(cache_path)
        self._decimals = grid_decimals
        self._fallback = fallback
        self._cache: dict[str, TrafficSample] = self._load()

    def _key(self, lat: float, lng: float) -> str:
        return f"{round(lat, self._decimals)},{round(lng, self._decimals)}"

    def _load(self) -> dict[str, TrafficSample]:
        if not self._path.exists():
            return {}
        raw = json.loads(self._path.read_text())
        return {k: TrafficSample(**v) for k, v in raw.items()}

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        serializable = {k: {"vehicles_week": s.vehicles_week, "free_flow_speed": s.free_flow_speed}
                        for k, s in self._cache.items()}
        self._path.write_text(json.dumps(serializable))

    def lookup(self, lat: float, lng: float) -> TrafficSample:
        return self._cache.get(self._key(lat, lng), self._fallback)

    def warm(
        self, locations: Iterable[tuple[float, float]], fetch: TrafficFetch, delay_s: float = 0.0
    ) -> int:
        written = 0
        seen: set[str] = set()
        for lat, lng in locations:
            key = self._key(lat, lng)
            if key in seen:
                continue
            seen.add(key)
            self._cache[key] = fetch(lat, lng)
            written += 1
            if delay_s:
                time.sleep(delay_s)
        self._persist()
        return written


def tomtom_fetch(api_key: str, *, client: httpx.Client | None = None) -> TrafficFetch:
    url = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"

    def fetch(lat: float, lng: float) -> TrafficSample:
        owns = client is None
        c = client or httpx.Client(timeout=10.0)
        try:
            resp = c.get(url, params={"point": f"{lat},{lng}", "key": api_key})
            resp.raise_for_status()
            seg = resp.json()["flowSegmentData"]
            lanes = _FRC_LANE_MAP.get(seg.get("frc", "FRC3"), 3.0)
            hourly = round(lanes * _CAPACITY_PER_LANE * (seg["currentSpeed"] / seg["freeFlowSpeed"]))
            weekly = round(hourly * _DAILY_HOURS * _DAYS_PER_WEEK)
            return TrafficSample(vehicles_week=float(weekly), free_flow_speed=float(seg["freeFlowSpeed"]))
        finally:
            if owns:
                c.close()

    return fetch
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/api && .venv/bin/pytest tests/unit/test_planning_traffic.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add services/api/src/citycrawl_api/modules/planning/traffic.py \
        services/api/tests/unit/test_planning_traffic.py
git commit -m "feat(planning): cached traffic provider with TomTom warm path"
```

---

## Task 5: OptimizationPlanningEngine

Wires Tasks 1–4 into the `PlanningEngine` contract, producing `PlanResult`/`ClusteredPriority`.

**Files:**
- Create: `services/api/src/citycrawl_api/modules/planning/engine.py`
- Test: `services/api/tests/unit/test_planning_engine.py`

**Interfaces:**
- Consumes: `cluster_by_proximity` (Task 1), `build_superclusters` (Task 2), `supercluster_cost`/`select_within_budget` (Task 3), `TrafficProvider`/`TrafficSample` (Task 4); `geometry.centroid_of`/`convex_hull`/`LatLng`; models `AnalysisRequest`/`PlanResult`/`Squad`/`TopCritical`/`PlanStats`/`LatLngModel`/`ClusteredPriority`/`AnalysisPoint`; `SQUAD_COLORS` from `models`.
- Produces: `class OptimizationPlanningEngine` with `name = "optimization"`, `__init__(self, traffic: TrafficProvider, *, radius_m: float = 100.0, max_points: int = 12)`, `optimize(request) -> PlanResult`, `cluster_priorities(points, squad_count=None) -> list[ClusteredPriority]`.

- [ ] **Step 1: Write the failing test**

```python
# services/api/tests/unit/test_planning_engine.py
"""OptimizationPlanningEngine: contract shape + budget/cost/cap behavior, no network."""
from citycrawl_api.modules.planning.engine import OptimizationPlanningEngine
from citycrawl_api.modules.planning.models import AnalysisPoint, AnalysisRequest
from citycrawl_api.modules.planning.traffic import TrafficProvider, TrafficSample


def _engine(tmp_path):
    # Cache empty → provider returns its fallback for every lookup (deterministic, no net).
    prov = TrafficProvider(cache_path=str(tmp_path / "c.json"),
                           fallback=TrafficSample(1.0, 1.0))
    return OptimizationPlanningEngine(prov, radius_m=100.0, max_points=12)


def _pts(n: int) -> list[AnalysisPoint]:
    # n well-separated single-point clusters (each ~1 km from the next).
    return [AnalysisPoint(id=f"p{i}", lat=19.40 + i * 0.01, lng=-99.1, slug="pothole",
                          volume=float(i + 1), district_cve=f"d{i % 2}") for i in range(n)]


def test_engine_name():
    assert OptimizationPlanningEngine.name == "optimization"


def test_empty_points_empty_plan(tmp_path):
    res = _engine(tmp_path).optimize(
        AnalysisRequest(issueType="pothole", budget=1_000_000.0, points=[])
    )
    assert res.squads == [] and res.top_critical == []
    assert res.stats.spent == 0.0 and res.stats.count == 0


def test_spent_within_budget_and_cost_model(tmp_path):
    # Each point is its own supercluster: cost = 2000 + 8000*volume.
    req = AnalysisRequest(issueType="pothole", budget=20_000.0, points=_pts(5))
    res = _engine(tmp_path).optimize(req)
    assert res.stats.spent <= req.budget
    # Highest volume (p4, vol5 → cost 42000) can't fit; p0 vol1 → 10000 fits.
    selected_ids = {tc.id for tc in res.top_critical}
    assert "p0" in selected_ids
    for tc in res.top_critical:
        assert tc.cost > 0


def test_squads_have_geometry(tmp_path):
    res = _engine(tmp_path).optimize(
        AnalysisRequest(issueType="pothole", budget=1_000_000.0, points=_pts(4))
    )
    assert res.squad_count_used == len(res.squads)
    for sq in res.squads:
        assert 0.0 <= sq.weight <= 1.0
        assert sq.count == len(sq.members)
        assert sq.centroid.lat and sq.centroid.lng


def test_cluster_priorities_shape(tmp_path):
    out = _engine(tmp_path).cluster_priorities(_pts(4))
    assert all(0.0 <= cp.weight <= 1.0 and cp.count >= 1 for cp in out)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/api && .venv/bin/pytest tests/unit/test_planning_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: ...planning.engine`

- [ ] **Step 3: Write minimal implementation**

```python
# services/api/src/citycrawl_api/modules/planning/engine.py
"""Real planning engine adapting the ActionableOptimization deliverable.

Pipeline: eligible points (volume>0) → proximity clusters → traffic-weighted criticality
(weight = total_volume · vehicles_week · free_flow_speed) → capacity-bounded superclusters
(= trips) → cost (2000 + 8000·volume) → greedy budget selection. Outputs map onto the
existing wire contract: a selected supercluster is a Squad; selected points ranked by
weight are top_critical. Implements the PlanningEngine protocol; swappable with the mock."""
from __future__ import annotations

import math

from citycrawl_api.modules.planning.geometry import LatLng, centroid_of, convex_hull
from citycrawl_api.modules.planning.models import (
    SQUAD_COLORS,
    AnalysisPoint,
    AnalysisRequest,
    ClusteredPriority,
    LatLngModel,
    PlanResult,
    PlanStats,
    Squad,
    TopCritical,
)
from citycrawl_api.modules.planning.optimization.clustering import cluster_by_proximity
from citycrawl_api.modules.planning.optimization.cost import (
    select_within_budget,
    supercluster_cost,
)
from citycrawl_api.modules.planning.optimization.superclustering import build_superclusters
from citycrawl_api.modules.planning.traffic import TrafficProvider


def _js_round(x: float) -> int:
    return math.floor(x + 0.5)


def _latlng(points: list[AnalysisPoint]) -> list[LatLng]:
    return [LatLng(p.lat, p.lng) for p in points]


class OptimizationPlanningEngine:
    name = "optimization"

    def __init__(self, traffic: TrafficProvider, *, radius_m: float = 100.0, max_points: int = 12) -> None:
        self._traffic = traffic
        self._radius_m = radius_m
        self._max_points = max_points

    def _cluster_weights(self, points: list[AnalysisPoint]):
        """Return (clusters, centroids, sizes, volumes, weights) for proximity clusters."""
        clusters = cluster_by_proximity(points, self._radius_m)
        centroids: list[tuple[float, float]] = []
        sizes: list[int] = []
        volumes: list[float] = []
        weights: list[float] = []
        for idxs in clusters:
            members = [points[j] for j in idxs]
            c = centroid_of(_latlng(members))
            vol = sum(m.volume for m in members)
            t = self._traffic.lookup(c["lat"], c["lng"])
            centroids.append((c["lat"], c["lng"]))
            sizes.append(len(members))
            volumes.append(vol)
            weights.append(vol * t.vehicles_week * t.free_flow_speed)
        return clusters, centroids, sizes, volumes, weights

    def optimize(self, request: AnalysisRequest) -> PlanResult:
        eligible = [p for p in request.points if p.volume > 0]
        empty = PlanResult(
            issueType=request.issue_type, budget=request.budget,
            regionFilter=request.region_filter, squadCountUsed=0,
            topCritical=[], squads=[],
            stats=PlanStats(spent=0.0, count=0, squads=0, regions=0, volume=0.0, budgetPct=0),
        )
        if not eligible:
            return empty

        clusters, centroids, sizes, volumes, weights = self._cluster_weights(eligible)
        superclusters = build_superclusters(centroids, sizes, self._max_points)
        if not superclusters:
            return empty

        # Per-supercluster aggregates.
        sc_point_idx: list[list[int]] = []   # flattened original-point indices
        sc_volume: list[float] = []
        sc_weight: list[float] = []
        sc_cost: list[float] = []
        for cl_idxs in superclusters:
            pts = [pi for ci in cl_idxs for pi in clusters[ci]]
            vol = sum(volumes[ci] for ci in cl_idxs)
            sc_point_idx.append(pts)
            sc_volume.append(vol)
            sc_weight.append(sum(weights[ci] for ci in cl_idxs))
            sc_cost.append(supercluster_cost(vol))

        selected = select_within_budget(sc_weight, sc_cost, request.budget)  # desc-weight order
        if not selected:
            return empty

        max_w = max(sc_weight[s] for s in selected) or 1.0
        squads: list[Squad] = []
        top_critical: list[TopCritical] = []
        rank = 0
        for color_i, s in enumerate(selected):
            member_pts = [eligible[pi] for pi in sc_point_idx[s]]
            share = sc_cost[s] / len(member_pts)
            squads.append(Squad(
                idx=color_i + 1,
                color=SQUAD_COLORS[color_i % len(SQUAD_COLORS)],
                weight=sc_weight[s] / max_w,
                members=[m.id for m in member_pts],
                polygon=convex_hull(_latlng(member_pts)),
                centroid=LatLngModel(**centroid_of(_latlng(member_pts))),
                cost=sc_cost[s],
                count=len(member_pts),
            ))
            for m in member_pts:
                rank += 1
                top_critical.append(TopCritical(
                    id=m.id, slug=m.slug, lat=m.lat, lng=m.lng, volume=m.volume,
                    cost=share, zone=m.zone, rank=rank,
                ))

        spent = sum(sc_cost[s] for s in selected)
        sel_pts = [eligible[pi] for s in selected for pi in sc_point_idx[s]]
        regions = len({p.district_cve for p in sel_pts if p.district_cve})
        volume = sum(p.volume for p in sel_pts)
        budget_pct = min(100, _js_round(spent / request.budget * 100)) if request.budget > 0 else 0

        return PlanResult(
            issueType=request.issue_type, budget=request.budget,
            regionFilter=request.region_filter, squadCountUsed=len(squads),
            topCritical=top_critical, squads=squads,
            stats=PlanStats(spent=spent, count=len(sel_pts), squads=len(squads),
                            regions=regions, volume=volume, budgetPct=budget_pct),
        )

    def cluster_priorities(
        self, points: list[AnalysisPoint], squad_count: int | None = None
    ) -> list[ClusteredPriority]:
        # squad_count is advisory and ignored: clusters are proximity-derived.
        pts = [p for p in points if p.volume > 0]
        if len(pts) < 2:
            return []
        clusters, _, _, _, weights = self._cluster_weights(pts)
        wmin, wmax = min(weights), max(weights)
        out: list[ClusteredPriority] = []
        for i, idxs in enumerate(clusters):
            members = [pts[j] for j in idxs]
            out.append(ClusteredPriority(
                id=f"cp-{i + 1}",
                weight=((weights[i] - wmin) / (wmax - wmin)) if wmax > wmin else 1.0,
                polygon=convex_hull(_latlng(members)),
                centroid=LatLngModel(**centroid_of(_latlng(members))),
                count=len(members),
            ))
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/api && .venv/bin/pytest tests/unit/test_planning_engine.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add services/api/src/citycrawl_api/modules/planning/engine.py \
        services/api/tests/unit/test_planning_engine.py
git commit -m "feat(planning): OptimizationPlanningEngine wiring deliverable into PlanResult"
```

---

## Task 6: Config + router binding

Add settings, build the engine from config, keep the mock selectable, document env vars.

**Files:**
- Modify: `services/api/src/citycrawl_api/config.py` (add fields after the existing planning/storage block)
- Modify: `services/api/src/citycrawl_api/routers/planning.py:18-19` (replace the single bound `_engine`)
- Modify: `services/api/.env.example` (append the two new keys)
- Test: `services/api/tests/integration/test_planning_optimization_route.py`

**Interfaces:**
- Consumes: `OptimizationPlanningEngine` (Task 5), `TrafficProvider` (Task 4), `MockPlanningEngine`, `get_settings`.
- Produces: `Settings.tomtom_api_key: str | None`, `Settings.planning_engine: str = "optimization"`, `Settings.traffic_cache_path: str`, `Settings.traffic_grid_decimals: int`; module-level `_engine` in the router selected by `planning_engine`.

- [ ] **Step 1: Write the failing test**

```python
# services/api/tests/integration/test_planning_optimization_route.py
"""/v1/planning/optimize served by the real engine: header, schema, budget invariant."""


def _req(budget: float):
    return {
        "issueType": "pothole",
        "budget": budget,
        "regionFilter": [],
        "points": [
            {"id": f"p{i}", "lat": 19.40 + i * 0.01, "lng": -99.1,
             "slug": "pothole", "volume": float(i + 1), "districtCve": "d1"}
            for i in range(5)
        ],
    }


def test_optimize_reports_optimization_engine(client):
    r = client.post("/v1/planning/optimize", json=_req(1_000_000.0))
    assert r.status_code == 200
    assert r.headers["X-Planning-Engine"] == "optimization"


def test_optimize_schema_and_budget_invariant(client):
    r = client.post("/v1/planning/optimize", json=_req(20_000.0))
    body = r.json()
    assert set(body) >= {"issueType", "budget", "squads", "topCritical", "stats", "squadCountUsed"}
    assert body["stats"]["spent"] <= 20_000.0
    assert body["squadCountUsed"] == len(body["squads"])


def test_priorities_cluster_served(client):
    r = client.post("/v1/planning/priorities:cluster", json={
        "points": _req(0)["points"], "squadCount": 3,
    })
    assert r.status_code == 200
    assert r.headers["X-Planning-Engine"] == "optimization"
    assert isinstance(r.json(), list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/api && .venv/bin/pytest tests/integration/test_planning_optimization_route.py -v`
Expected: FAIL — header is `mock` (router still binds `MockPlanningEngine`)

- [ ] **Step 3a: Add config fields**

In `services/api/src/citycrawl_api/config.py`, add these fields inside the `Settings` class (place them just before the `cors_origins` property):

```python
    # --- Planning engine ------------------------------------------------------
    planning_engine: str = "optimization"     # "optimization" | "mock"
    tomtom_api_key: str | None = None
    traffic_cache_path: str = ".data/traffic_cache.json"
    traffic_grid_decimals: int = 3
```

- [ ] **Step 3b: Bind the engine from config**

Replace `services/api/src/citycrawl_api/routers/planning.py` lines 6-19 (the imports of `MockPlanningEngine` and the `_engine = MockPlanningEngine()` line) with:

```python
from citycrawl_api.auth import User, require_user
from citycrawl_api.config import get_settings
from citycrawl_api.modules.planning.engine import OptimizationPlanningEngine
from citycrawl_api.modules.planning.mock import MockPlanningEngine
from citycrawl_api.modules.planning.models import (
    AnalysisRequest,
    ClusterPrioritiesRequest,
    ClusteredPriority,
    PlanResult,
)
from citycrawl_api.modules.planning.protocol import PlanningEngine
from citycrawl_api.modules.planning.traffic import TrafficProvider

router = APIRouter(prefix="/v1/planning", tags=["planning"])


def _build_engine() -> PlanningEngine:
    settings = get_settings()
    if settings.planning_engine == "mock":
        return MockPlanningEngine()
    traffic = TrafficProvider(
        cache_path=settings.traffic_cache_path,
        grid_decimals=settings.traffic_grid_decimals,
    )
    return OptimizationPlanningEngine(traffic)


# Single bound engine, selected by PLANNING_ENGINE. Routes depend only on the protocol.
_engine: PlanningEngine = _build_engine()
```

- [ ] **Step 3c: Document env vars**

Append to `services/api/.env.example`:

```
# Planning engine: "optimization" (real, default) or "mock"
PLANNING_ENGINE=optimization
# TomTom Traffic Flow API key — used ONLY by the offline traffic warm job, never by /optimize
TOMTOM_API_KEY=
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/api && .venv/bin/pytest tests/integration/test_planning_optimization_route.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Confirm the mock parity suite still passes**

Run: `cd services/api && .venv/bin/pytest tests/integration/test_planning_parity.py -v`
Expected: PASS — if it constructs an engine directly it is unaffected; if it hits the route, set `PLANNING_ENGINE=mock` in that test's env. If it fails because the route now returns the optimization engine, update that test to instantiate `MockPlanningEngine()` directly (the parity test targets the mock, not the route).

- [ ] **Step 6: Commit**

```bash
git add services/api/src/citycrawl_api/config.py \
        services/api/src/citycrawl_api/routers/planning.py \
        services/api/.env.example \
        services/api/tests/integration/test_planning_optimization_route.py
git commit -m "feat(planning): bind optimization engine from config (PLANNING_ENGINE)"
```

---

## Task 7: Traffic warm CLI

A Typer command to populate the traffic cache from TomTom, with point locations from a file (testable) or the database.

**Files:**
- Create: `services/api/src/citycrawl_api/modules/planning/cli.py`
- Modify: `services/api/pyproject.toml` (add a `[project.scripts]` entry)
- Test: `services/api/tests/unit/test_planning_cli.py`

**Interfaces:**
- Consumes: `TrafficProvider`/`tomtom_fetch` (Task 4), `get_settings` (Task 6).
- Produces: a Typer `app` with command `warm-traffic` (`--from-file PATH` of `lat,lng` lines; `--delay FLOAT`); registered as console script `citycrawl-planning`. Internal helper `_read_locations(path: str) -> list[tuple[float, float]]`.

- [ ] **Step 1: Write the failing test**

```python
# services/api/tests/unit/test_planning_cli.py
"""warm-traffic CLI: reads lat,lng pairs and warms the provider without live TomTom."""
from typer.testing import CliRunner

from citycrawl_api.modules.planning import cli
from citycrawl_api.modules.planning.traffic import TrafficProvider, TrafficSample

runner = CliRunner()


def test_read_locations(tmp_path):
    f = tmp_path / "loc.csv"
    f.write_text("19.40,-99.10\n19.41,-99.11\n\n")  # blank line ignored
    assert cli._read_locations(str(f)) == [(19.40, -99.10), (19.41, -99.11)]


def test_warm_traffic_command(tmp_path, monkeypatch):
    loc = tmp_path / "loc.csv"
    loc.write_text("19.40,-99.10\n")
    cache = tmp_path / "cache.json"

    # Avoid real settings/network: stub the fetch factory and force the cache path.
    monkeypatch.setattr(cli, "_provider", lambda: TrafficProvider(cache_path=str(cache)))
    monkeypatch.setattr(cli, "_fetch", lambda: (lambda la, lo: TrafficSample(123.0, 45.0)))

    result = runner.invoke(cli.app, ["warm-traffic", "--from-file", str(loc)])
    assert result.exit_code == 0, result.output
    assert "1" in result.output  # reports cells written
    assert TrafficProvider(cache_path=str(cache)).lookup(19.40, -99.10) == TrafficSample(123.0, 45.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/api && .venv/bin/pytest tests/unit/test_planning_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: ...planning.cli`

- [ ] **Step 3: Write minimal implementation**

```python
# services/api/src/citycrawl_api/modules/planning/cli.py
"""Local Typer adapter that warms the traffic cache from TomTom. Run before deploy (or on a
schedule) so /optimize has real traffic weights; /optimize itself never calls TomTom.

Usage:
    citycrawl-planning warm-traffic --from-file locations.csv
where locations.csv has one `lat,lng` per line. `_provider`/`_fetch` are split out so tests
can stub them without real settings or network."""
from __future__ import annotations

import typer

from citycrawl_api.config import get_settings
from citycrawl_api.modules.planning.traffic import TrafficFetch, TrafficProvider, tomtom_fetch

app = typer.Typer(help="Planning maintenance commands.")


def _read_locations(path: str) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            lat, lng = line.split(",")
            out.append((float(lat), float(lng)))
    return out


def _provider() -> TrafficProvider:
    s = get_settings()
    return TrafficProvider(cache_path=s.traffic_cache_path, grid_decimals=s.traffic_grid_decimals)


def _fetch() -> TrafficFetch:
    s = get_settings()
    if not s.tomtom_api_key:
        raise typer.BadParameter("TOMTOM_API_KEY is not set.")
    return tomtom_fetch(s.tomtom_api_key)


@app.command("warm-traffic")
def warm_traffic(
    from_file: str = typer.Option(..., "--from-file", help="CSV of `lat,lng` per line."),
    delay: float = typer.Option(0.25, "--delay", help="Seconds between TomTom calls."),
) -> None:
    locations = _read_locations(from_file)
    written = _provider().warm(locations, _fetch(), delay_s=delay)
    typer.echo(f"Warmed {written} traffic grid cells from {len(locations)} locations.")
```

- [ ] **Step 3b: Register the console script**

In `services/api/pyproject.toml`, under the existing `[project.scripts]` block (which already has `citycrawl-datasets`), add:

```toml
citycrawl-planning = "citycrawl_api.modules.planning.cli:app"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/api && .venv/bin/pytest tests/unit/test_planning_cli.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add services/api/src/citycrawl_api/modules/planning/cli.py \
        services/api/pyproject.toml \
        services/api/tests/unit/test_planning_cli.py
git commit -m "feat(planning): warm-traffic CLI to populate the traffic cache"
```

---

## Task 8: Full suite green + docs

Verify the whole API test suite passes with the optimization engine bound, and note the warm step in the runbook.

**Files:**
- Modify: `services/api/README.md` (add a short "Planning engine / traffic warm" section)

- [ ] **Step 1: Run the full API test suite**

Run: `cd services/api && .venv/bin/pytest -q`
Expected: PASS (all tests, no skips). If the parity test fails because it now hits the optimization engine via the route, fix per Task 6 Step 5 (point it at `MockPlanningEngine()` directly).

- [ ] **Step 2: Document the runbook step**

Append to `services/api/README.md`:

```markdown
## Planning engine

`/v1/planning/optimize` and `/priorities:cluster` are served by the real
`OptimizationPlanningEngine` (set `PLANNING_ENGINE=mock` to fall back to the baseline).
Criticality is traffic-weighted; the endpoint reads a **cached** traffic layer and never
calls TomTom. Warm the cache before/after deploy:

    export TOMTOM_API_KEY=...        # in services/api/.env
    citycrawl-planning warm-traffic --from-file locations.csv

`locations.csv` is one `lat,lng` per line (export observation coordinates from Supabase).
On a cache miss the engine uses a neutral default factor, so the plan still ranks by
volume until the cache is warmed.
```

- [ ] **Step 3: Commit**

```bash
git add services/api/README.md
git commit -m "docs(planning): runbook for optimization engine + traffic warm"
```

---

## Self-Review

**Spec coverage:**
- §"Engine-only, contract preserved" → Tasks 5, 6 (no wire/frontend changes). ✓
- §"Spatial clustering, not street-name" → Task 1. ✓
- §"Traffic via cached layer, never live in request" → Task 4 (`lookup` no-network test) + Task 6 binding + Task 7 warm. ✓
- §"`squad_count` advisory for optimize" → Task 5 (`cluster_priorities` ignores it; `optimize` derives count from caps). ✓
- §"Engine config-selectable, mock retained" → Task 6 (`PLANNING_ENGINE`). ✓
- §Algorithm steps 1–6 (eligible → cluster → traffic weight → supercluster → cost → budget) → Tasks 1–5. ✓
- §Output mapping table (supercluster→Squad, top_critical, stats) → Task 5. ✓
- §Traffic cache (grid key, warm path, FRC math, fallback) → Task 4. ✓
- §Testing (unit, contract, traffic no-network, router, sanity) → Tasks 1–6 tests. ✓
- §"TomTom key is a secret" → Task 6 `.env.example` empty placeholder; Task 7 reads from settings. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✓

**Type consistency:** `cluster_by_proximity(points, radius_m)->list[list[int]]`, `build_superclusters(centroids, sizes, max_points)->list[list[int]]`, `supercluster_cost(total_volume)->float`, `select_within_budget(weights, costs, budget)->list[int]`, `TrafficProvider.lookup/warm`, `TrafficSample(vehicles_week, free_flow_speed)`, `OptimizationPlanningEngine(traffic, *, radius_m, max_points)` — names match across Tasks 1–7. PlanResult/Squad/etc. constructed with camelCase aliases (`issueType`, `squadCountUsed`, `topCritical`, `regionFilter`, `budgetPct`) per `models.py` `populate_by_name=True`. ✓

**Open risk to watch during execution:** the existing `tests/integration/test_planning_parity.py` asserts mock byte-parity. Confirm whether it calls the route (now optimization) or the engine directly; if the route, adjust per Task 6 Step 5 so it still targets the mock.
