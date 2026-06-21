"""Geometry helpers — a faithful Python port of the frontend `lib/geo.ts`. Distance,
deterministic k-means-style clustering, convex hull (monotone chain), and centroid.
Behavior is kept identical to the TypeScript so planning output matches byte-for-byte."""
from __future__ import annotations
import math
from dataclasses import dataclass


@dataclass
class LatLng:
    lat: float
    lng: float


def haversine(la1: float, lo1: float, la2: float, lo2: float) -> float:
    R = 6371000.0
    d_la = (la2 - la1) * math.pi / 180.0
    d_lo = (lo2 - lo1) * math.pi / 180.0
    a = (
        math.sin(d_la / 2) ** 2
        + math.cos(la1 * math.pi / 180.0) * math.cos(la2 * math.pi / 180.0) * math.sin(d_lo / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))


def centroid_of(pts: list[LatLng]) -> dict[str, float]:
    if not pts:
        return {"lat": 0.0, "lng": 0.0}
    lat = sum(p.lat for p in pts)
    lng = sum(p.lng for p in pts)
    return {"lat": lat / len(pts), "lng": lng / len(pts)}


def cluster_indices(pts: list[LatLng], k: int) -> list[list[int]]:
    """Deterministic k-means-style clustering on lat/lng. Returns, per non-empty cluster,
    the indices of its members. Mirrors geo.ts exactly (seeding, iteration cap, reseed)."""
    n = len(pts)
    if n == 0:
        return []
    K = max(1, min(k, n))
    if K == 1:
        return [list(range(n))]

    order = sorted(range(n), key=lambda i: (pts[i].lng, pts[i].lat))
    centroids: list[LatLng] = []
    for j in range(K):
        idx = order[min(n - 1, math.floor((j + 0.5) * (n / K)))]
        centroids.append(LatLng(pts[idx].lat, pts[idx].lng))

    assign = [0] * n
    for it in range(14):
        changed = False
        for i in range(n):
            best = 0
            bd = math.inf
            for j in range(K):
                d = haversine(pts[i].lat, pts[i].lng, centroids[j].lat, centroids[j].lng)
                if d < bd:
                    bd = d
                    best = j
            if assign[i] != best:
                assign[i] = best
                changed = True
        sums = [{"lat": 0.0, "lng": 0.0, "c": 0} for _ in range(K)]
        for i in range(n):
            a = assign[i]
            sums[a]["lat"] += pts[i].lat
            sums[a]["lng"] += pts[i].lng
            sums[a]["c"] += 1
        centroids = [
            LatLng(s["lat"] / s["c"], s["lng"] / s["c"]) if s["c"] else centroids[j]
            for j, s in enumerate(sums)
        ]
        if not changed and it > 0:
            break

    groups: list[list[int]] = [[] for _ in range(K)]
    for i, a in enumerate(assign):
        groups[a].append(i)
    # Reseed empty clusters by stealing one member from the largest group.
    for j in range(K):
        if len(groups[j]) == 0:
            big = 0
            for g in range(K):
                if len(groups[g]) > len(groups[big]):
                    big = g
            if len(groups[big]) > 1:
                groups[j].append(groups[big].pop())
    return [g for g in groups if len(g) > 0]


def convex_hull(pts: list[LatLng]) -> list[list[float]]:
    """Andrew's monotone chain. Input LatLng list; output [lat, lng] pairs. For <3 points
    the hull is just the points (matches geo.ts)."""
    if len(pts) < 3:
        return [[p.lat, p.lng] for p in pts]
    ps = [[p.lng, p.lat] for p in pts]  # x=lng, y=lat
    ps.sort(key=lambda a: (a[0], a[1]))

    def cross(o: list[float], a: list[float], b: list[float]) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[list[float]] = []
    for p in ps:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[list[float]] = []
    for i in range(len(ps) - 1, -1, -1):
        p = ps[i]
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    lower.pop()
    upper.pop()
    return [[y, x] for x, y in (lower + upper)]  # -> [lat, lng]
