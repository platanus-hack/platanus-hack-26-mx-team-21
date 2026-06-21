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
