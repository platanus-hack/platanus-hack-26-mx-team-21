"""Real planning engine adapting the ActionableOptimization deliverable.

Pipeline: eligible points (volume>0) → proximity clusters → traffic-weighted criticality
(weight = total_volume · vehicles_week · free_flow_speed) → cost (2000 + 8000·volume) →
greedy budget selection (cheapest-first so the tightest budgets still pick up affordable
trips). Outputs map onto the existing wire contract: a selected proximity cluster is a
Squad; selected points ranked by weight are top_critical. Implements the PlanningEngine
protocol; swappable with the mock."""
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

        # Each proximity cluster maps to one trip (squad). Cost is per-cluster volume.
        # Selection uses inverted cost as priority so cheapest trips are preferred —
        # this ensures individually affordable trips are never blocked by a high-cost
        # trip that happens to have higher criticality weight.
        sc_costs = [supercluster_cost(v) for v in volumes]
        inv_costs = [1.0 / c for c in sc_costs]

        selected = select_within_budget(inv_costs, sc_costs, request.budget)  # cheapest-first
        if not selected:
            return empty

        max_w = max(weights[s] for s in selected) or 1.0
        squads: list[Squad] = []
        top_critical: list[TopCritical] = []
        rank = 0
        for color_i, s in enumerate(selected):
            member_pts = [eligible[pi] for pi in clusters[s]]
            share = sc_costs[s] / len(member_pts)
            squads.append(Squad(
                idx=color_i + 1,
                color=SQUAD_COLORS[color_i % len(SQUAD_COLORS)],
                weight=weights[s] / max_w,
                members=[m.id for m in member_pts],
                polygon=convex_hull(_latlng(member_pts)),
                centroid=LatLngModel(**centroid_of(_latlng(member_pts))),
                cost=sc_costs[s],
                count=len(member_pts),
            ))
            for m in member_pts:
                rank += 1
                top_critical.append(TopCritical(
                    id=m.id, slug=m.slug, lat=m.lat, lng=m.lng, volume=m.volume,
                    cost=share, zone=m.zone, rank=rank,
                ))

        spent = sum(sc_costs[s] for s in selected)
        sel_pts = [eligible[pi] for s in selected for pi in clusters[s]]
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
