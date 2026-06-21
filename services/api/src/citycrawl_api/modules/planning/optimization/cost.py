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
