"""Dataset refresh route: operator protection and NDJSON streaming. Uses a narrow refresh
(unknown source id) so no real extraction runs but the full stream contract is exercised
end-to-end with local in-memory stores (no DB)."""
import json

import pytest

from citycrawl_api.config import get_settings


@pytest.fixture
def operator_env(monkeypatch, tmp_path):
    monkeypatch.setenv("OPERATOR_API_KEY", "secret-op-key")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_ROOT", str(tmp_path))
    monkeypatch.delenv("DB_URL", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_refresh_requires_auth(raw_client, operator_env):
    r = raw_client.post("/v1/datasets/refresh", json={"sourceIds": []})
    assert r.status_code == 401


def test_refresh_requires_operator_key(client, operator_env):
    r = client.post("/v1/datasets/refresh", json={"sourceIds": []})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


def test_refresh_streams_complete(client, operator_env):
    r = client.post(
        "/v1/datasets/refresh",
        json={"sourceIds": ["__nonexistent__"]},
        headers={"X-Operator-Key": "secret-op-key"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    records = [json.loads(line) for line in r.text.splitlines() if line.strip()]
    assert records, "expected at least one NDJSON record"
    complete = [rec for rec in records if rec["type"] == "complete"]
    assert len(complete) == 1
    assert complete[0]["signalCount"] == 0
    assert complete[0]["roiCount"] == 0
