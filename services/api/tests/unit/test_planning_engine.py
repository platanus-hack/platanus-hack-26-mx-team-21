"""OptimizationPlanningEngine: contract shape + budget/cost/cap behavior, no network."""
from citycrawl_api.modules.planning.engine import OptimizationPlanningEngine
from citycrawl_api.modules.planning.models import AnalysisPoint, AnalysisRequest
from citycrawl_api.modules.planning.traffic import TrafficProvider, TrafficSample


def _engine(tmp_path):
    # Empty cache -> provider returns its fallback for every lookup (deterministic, no net).
    # max_points=2 forces superclustering to split into multiple trips, so budget bounding
    # and criticality-first ordering are actually exercised.
    prov = TrafficProvider(cache_path=str(tmp_path / "c.json"),
                           fallback=TrafficSample(1.0, 1.0))
    return OptimizationPlanningEngine(prov, radius_m=100.0, max_points=2)


def _pts(n: int) -> list[AnalysisPoint]:
    # n well-separated single-point clusters (each ~1.1 km from the next).
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


def test_spent_within_budget_and_criticality_first(tmp_path):
    # max_points=2 -> trips: {p0,p1}(vol3,cost26000), {p2,p3}(vol7,cost58000), {p4}(vol5,cost42000).
    # Budget 60000, selection by descending weight: {p2,p3}(w7) fits; the others bust the budget.
    req = AnalysisRequest(issueType="pothole", budget=60_000.0, points=_pts(5))
    res = _engine(tmp_path).optimize(req)
    assert res.stats.spent <= req.budget
    selected_ids = {tc.id for tc in res.top_critical}
    # Criticality-first: the highest-volume trip is selected; the lowest-volume p0 is not.
    assert "p3" in selected_ids
    assert "p0" not in selected_ids
    for tc in res.top_critical:
        assert tc.cost > 0


def test_squads_have_geometry(tmp_path):
    res = _engine(tmp_path).optimize(
        AnalysisRequest(issueType="pothole", budget=1_000_000.0, points=_pts(4))
    )
    assert res.squad_count_used == len(res.squads)
    assert res.squads  # large budget -> at least one trip selected
    for sq in res.squads:
        assert 0.0 <= sq.weight <= 1.0
        assert sq.count == len(sq.members)
        assert sq.centroid.lat and sq.centroid.lng


def test_cluster_priorities_shape(tmp_path):
    out = _engine(tmp_path).cluster_priorities(_pts(4))
    assert all(0.0 <= cp.weight <= 1.0 and cp.count >= 1 for cp in out)
