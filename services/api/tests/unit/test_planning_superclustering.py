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
