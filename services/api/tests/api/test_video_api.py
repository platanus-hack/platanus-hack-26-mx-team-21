def test_capabilities_requires_auth(raw_client):
    assert raw_client.get("/v1/video/capabilities").status_code == 401


def test_capabilities_reports_not_implemented(client):
    r = client.get("/v1/video/capabilities")
    assert r.status_code == 200
    assert r.json() == {"implemented": False, "operations": []}
