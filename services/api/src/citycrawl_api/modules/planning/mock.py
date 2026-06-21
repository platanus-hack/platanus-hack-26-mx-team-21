"""MOCK planning engine — a faithful Python port of the frontend `lib/analysis.ts`
(`runAnalysis` + `mockClusteredPriorities`). It deliberately does NOT model monetary cost:
it ranks by volume, bounds the selection with a flat throwaway nominal so the budget slider
matters, and clusters the selection into squads. A real optimizer replaces this one class;
the request/result wire shapes are unaffected. Explicitly a mock."""
from __future__ import annotations
import math

from citycrawl_api.modules.planning.geometry import (
    LatLng,
    centroid_of,
    cluster_indices,
    convex_hull,
)
from citycrawl_api.modules.planning.models import (
    DEFAULT_SQUADS,
    MAX_SQUADS,
    MOCK_UNIT_COST,
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


def _js_round(x: float) -> int:
    """JS Math.round semantics (round half toward +infinity), unlike Python's round()."""
    return math.floor(x + 0.5)


def _clamp_squads(override: int | None) -> int:
    k = override if override is not None else DEFAULT_SQUADS
    return max(1, min(MAX_SQUADS, _js_round(k)))


def _latlng(points: list[AnalysisPoint]) -> list[LatLng]:
    return [LatLng(p.lat, p.lng) for p in points]


class MockPlanningEngine:
    """Labelled mock; see module docstring. Surfaced as the engine name in API metadata."""

    name = "mock"

    def cluster_priorities(
        self, points: list[AnalysisPoint], squad_count: int | None = None
    ) -> list[ClusteredPriority]:
        k = squad_count if squad_count is not None else DEFAULT_SQUADS
        pts = [p for p in points if p.volume > 0]
        if len(pts) < 2:
            return []
        groups = cluster_indices(_latlng(pts), k)
        vols = [sum(pts[j].volume for j in idxs) for idxs in groups]
        vmin = min(vols)
        vmax = max(vols)
        out: list[ClusteredPriority] = []
        for i, idxs in enumerate(groups):
            members = [pts[j] for j in idxs]
            out.append(
                ClusteredPriority(
                    id=f"cp-{i + 1}",
                    weight=((vols[i] - vmin) / (vmax - vmin)) if vmax > vmin else 1,
                    polygon=convex_hull(_latlng(members)),
                    centroid=LatLngModel(**centroid_of(_latlng(members))),
                    count=len(members),
                )
            )
        return out

    def optimize(self, request: AnalysisRequest) -> PlanResult:
        squad_target = _clamp_squads(request.squad_count)

        # 1. Eligible = region/type-filtered points that have a known volume.
        eligible = [p for p in request.points if p.volume > 0]

        # 2. Criticality ranks by volume (larger/worse first); stable on ties.
        ranked = sorted(eligible, key=lambda p: -p.volume)

        # 3. Budget selection — trivial throwaway proxy (flat nominal per item). NOT a
        #    cost model; real monetary cost is the optimizer's job (deferred).
        selected: list[AnalysisPoint] = []
        spent = 0.0
        for p in ranked:
            if spent + MOCK_UNIT_COST > request.budget:
                break
            selected.append(p)
            spent += MOCK_UNIT_COST

        top_critical = [
            TopCritical(
                id=p.id,
                slug=p.slug,
                lat=p.lat,
                lng=p.lng,
                volume=p.volume,
                cost=MOCK_UNIT_COST,  # placeholder — replaced by the optimizer's real cost
                zone=p.zone,
                rank=i + 1,
            )
            for i, p in enumerate(selected)
        ]

        # 4. Cluster the selected set into K squads (one squad per cluster).
        groups = cluster_indices(_latlng(selected), squad_target)
        raw_weights = [sum(selected[j].volume for j in idxs) for idxs in groups]
        max_weight = max([1.0, *raw_weights])
        squads: list[Squad] = []
        for i, idxs in enumerate(groups):
            members = [selected[j] for j in idxs]
            squads.append(
                Squad(
                    idx=i + 1,
                    color=SQUAD_COLORS[i % len(SQUAD_COLORS)],
                    # MOCK cluster priority — proxied by the cluster's normalized total
                    # volume only so the region color ramp renders. The optimizer supplies
                    # the real weight; the app never derives priority itself.
                    weight=raw_weights[i] / max_weight,
                    members=[m.id for m in members],
                    polygon=convex_hull(_latlng(members)),
                    centroid=LatLngModel(**centroid_of(_latlng(members))),
                    cost=len(members) * MOCK_UNIT_COST,
                    count=len(members),
                )
            )

        # 5. Stats — placeholder spent/budgetPct (faked by the mock).
        regions = len({p.district_cve for p in selected if p.district_cve})
        volume = sum(p.volume for p in selected)
        budget_pct = (
            min(100, _js_round(spent / request.budget * 100)) if request.budget > 0 else 0
        )

        return PlanResult(
            issue_type=request.issue_type,
            budget=request.budget,
            region_filter=request.region_filter,
            squad_count_used=len(squads),
            top_critical=top_critical,
            squads=squads,
            stats=PlanStats(
                spent=spent,
                count=len(selected),
                squads=len(squads),
                regions=regions,
                volume=volume,
                budget_pct=budget_pct,
            ),
        )
