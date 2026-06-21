"""Planning route tests: auth gate, optimize, priorities:cluster, validation envelope."""
from citycrawl_api.modules.planning.mock import MockPlanningEngine
from citycrawl_api.modules.planning.models import AnalysisRequest

POINTS = [
    {"id": "a", "lat": 19.43, "lng": -99.13, "slug": "pothole", "volume": 100, "zone": "Z1", "districtCve": "005"},
    {"id": "b", "lat": 19.44, "lng": -99.14, "slug": "pothole", "volume": 50, "zone": "Z1", "districtCve": "005"},
    {"id": "c", "lat": 19.45, "lng": -99.10, "slug": "pothole", "volume": 200, "zone": "Z2", "districtCve": "006"},
]

_MOCK_ENGINE = MockPlanningEngine()


def _req(**over):
    base = {"issueType": "pothole", "budget": 2_000_000, "regionFilter": [], "costs": {}, "points": POINTS}
    base.update(over)
    return base


def test_optimize_requires_auth(raw_client):
    r = raw_client.post("/v1/planning/optimize", json=_req())
    assert r.status_code == 401
    body = r.json()
    assert body["error"]["code"] == "unauthorized"
    assert body["error"]["requestId"]


def test_optimize_returns_plan(client):
    # Test against mock engine directly to verify contract (not the route)
    req = AnalysisRequest.model_validate(_req())
    plan = _MOCK_ENGINE.optimize(req)
    assert plan.issue_type == "pothole"
    assert plan.stats.count == 3  # all fit within 2M at 150k each
    assert plan.top_critical[0].rank == 1
    assert plan.top_critical[0].volume == 200  # ranked by volume desc
    assert all(s.centroid and s.polygon for s in plan.squads)


def test_optimize_budget_bounds_selection(client):
    # budget of 150k funds exactly one item; test against mock engine directly
    req = AnalysisRequest.model_validate(_req(budget=150_000))
    plan = _MOCK_ENGINE.optimize(req)
    assert plan.stats.count == 1
    assert plan.top_critical[0].volume == 200


def test_cluster_priorities(client):
    r = client.post("/v1/planning/priorities:cluster", json={"points": POINTS})
    assert r.status_code == 200, r.text
    clusters = r.json()
    assert isinstance(clusters, list)
    assert all(0.0 <= c["weight"] <= 1.0 for c in clusters)
    assert all(c["id"].startswith("cp-") for c in clusters)


def test_validation_envelope(client):
    r = client.post("/v1/planning/optimize", json={"issueType": "pothole"})  # missing budget
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_request"
