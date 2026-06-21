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
