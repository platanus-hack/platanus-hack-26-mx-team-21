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
