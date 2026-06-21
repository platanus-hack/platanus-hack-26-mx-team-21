"""/v1/planning/optimize served by the real engine: header, schema, budget invariant."""


def _req(budget: float):
    return {
        "issueType": "pothole",
        "budget": budget,
        "regionFilter": [],
        "points": [
            {"id": f"p{i}", "lat": 19.40 + i * 0.01, "lng": -99.1,
             "slug": "pothole", "volume": float(i + 1), "districtCve": "d1"}
            for i in range(5)
        ],
    }


def test_optimize_reports_optimization_engine(client):
    r = client.post("/v1/planning/optimize", json=_req(1_000_000.0))
    assert r.status_code == 200
    assert r.headers["X-Planning-Engine"] == "optimization"


def test_optimize_schema_and_budget_invariant(client):
    r = client.post("/v1/planning/optimize", json=_req(20_000.0))
    body = r.json()
    assert set(body) >= {"issueType", "budget", "squads", "topCritical", "stats", "squadCountUsed"}
    assert body["stats"]["spent"] <= 20_000.0
    assert body["squadCountUsed"] == len(body["squads"])


def test_priorities_cluster_served(client):
    r = client.post("/v1/planning/priorities:cluster", json={
        "points": _req(0)["points"], "squadCount": 3,
    })
    assert r.status_code == 200
    assert r.headers["X-Planning-Engine"] == "optimization"
    assert isinstance(r.json(), list)
