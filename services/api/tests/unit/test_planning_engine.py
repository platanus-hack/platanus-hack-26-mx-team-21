"""OptimizationPlanningEngine: contract shape + budget/cost/cap behavior, no network."""
from citycrawl_api.modules.planning.engine import OptimizationPlanningEngine
from citycrawl_api.modules.planning.models import AnalysisPoint, AnalysisRequest
from citycrawl_api.modules.planning.traffic import TrafficProvider, TrafficSample


def _engine(tmp_path):
    # Cache empty → provider returns its fallback for every lookup (deterministic, no net).
    prov = TrafficProvider(cache_path=str(tmp_path / "c.json"),
                           fallback=TrafficSample(1.0, 1.0))
    return OptimizationPlanningEngine(prov, radius_m=100.0, max_points=12)


def _pts(n: int) -> list[AnalysisPoint]:
    # n well-separated single-point clusters (each ~1 km from the next).
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


def test_spent_within_budget_and_cost_model(tmp_path):
    # Each point is its own supercluster: cost = 2000 + 8000*volume.
    req = AnalysisRequest(issueType="pothole", budget=20_000.0, points=_pts(5))
    res = _engine(tmp_path).optimize(req)
    assert res.stats.spent <= req.budget
    # Highest volume (p4, vol5 → cost 42000) can't fit; p0 vol1 → 10000 fits.
    selected_ids = {tc.id for tc in res.top_critical}
    assert "p0" in selected_ids
    for tc in res.top_critical:
        assert tc.cost > 0


def test_squads_have_geometry(tmp_path):
    res = _engine(tmp_path).optimize(
        AnalysisRequest(issueType="pothole", budget=1_000_000.0, points=_pts(4))
    )
    assert res.squad_count_used == len(res.squads)
    for sq in res.squads:
        assert 0.0 <= sq.weight <= 1.0
        assert sq.count == len(sq.members)
        assert sq.centroid.lat and sq.centroid.lng


def test_cluster_priorities_shape(tmp_path):
    out = _engine(tmp_path).cluster_priorities(_pts(4))
    assert all(0.0 <= cp.weight <= 1.0 and cp.count >= 1 for cp in out)
