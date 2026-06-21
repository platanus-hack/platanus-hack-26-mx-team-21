"""Geometry sanity checks (the parity test covers exact-match behavior end to end)."""
import math

from citycrawl_api.modules.planning.geometry import (
    LatLng,
    centroid_of,
    cluster_indices,
    convex_hull,
)


def test_haversine_centroid():
    pts = [LatLng(0, 0), LatLng(0, 2)]
    c = centroid_of(pts)
    assert c == {"lat": 0.0, "lng": 1.0}


def test_cluster_partitions_all_points():
    pts = [LatLng(19.4 + i * 0.01, -99.1 - i * 0.01) for i in range(10)]
    groups = cluster_indices(pts, 3)
    flat = sorted(i for g in groups for i in g)
    assert flat == list(range(10))  # every point assigned exactly once
    assert 1 <= len(groups) <= 3


def test_cluster_k_one_and_empty():
    assert cluster_indices([], 3) == []
    pts = [LatLng(1, 1), LatLng(2, 2)]
    assert cluster_indices(pts, 1) == [[0, 1]]


def test_convex_hull_small_and_square():
    assert convex_hull([LatLng(1, 1)]) == [[1, 1]]
    square = [LatLng(0, 0), LatLng(0, 1), LatLng(1, 1), LatLng(1, 0), LatLng(0.5, 0.5)]
    hull = convex_hull(square)
    assert len(hull) == 4  # interior point dropped
    for corner in ([0, 0], [0, 1], [1, 1], [1, 0]):
        assert corner in hull
