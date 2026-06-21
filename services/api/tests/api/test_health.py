def test_live_is_public(raw_client):
    r = raw_client.get("/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert r.headers.get("X-Request-ID")


def test_request_id_is_echoed(raw_client):
    r = raw_client.get("/health/live", headers={"X-Request-ID": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123"
