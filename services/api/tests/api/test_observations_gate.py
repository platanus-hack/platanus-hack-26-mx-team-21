"""The citizen route's confirmation gate. Stores are faked (no DB/R2) so we test only the
branching: gate off → create; gate on + confirmed → create; gate on + unconfirmed/timeout → 422."""
import uuid

import pytest

import citycrawl_api.routers.observations as obs_route
from citycrawl_api.config import get_settings


class _FakeThumbStore:
    def write_bytes(self, path, data):  # noqa: D401
        return None


def _fake_make_thumbnail_store(settings):
    return _FakeThumbStore(), "observation-thumbnails"


class _FakeObsStore:
    def __init__(self, dsn):
        pass

    def create_citizen_observation(self, **kw):
        return {
            "observation_id": str(kw["observation_id"]),
            "in_boundary": True,
            "thumbnail_path": kw["thumbnail_path"],
        }


class _FakeJobStore:
    verdict = {"status": "done", "response": {"confirmed": True}, "error": None}

    def __init__(self, dsn):
        pass

    def enqueue(self, **kw):
        return uuid.uuid4()

    def wait_for_result(self, job_id, **kw):
        return type(self).verdict


@pytest.fixture
def gate_env(monkeypatch):
    monkeypatch.setenv("OPERATOR_API_KEY", "secret-op-key")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("DB_URL", "postgresql://fake")
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


@pytest.fixture
def patched_stores(monkeypatch):
    monkeypatch.setattr(obs_route, "make_thumbnail_store", _fake_make_thumbnail_store)
    monkeypatch.setattr(obs_route, "PgObservationStore", _FakeObsStore)
    monkeypatch.setattr(obs_route, "PgInferenceJobStore", _FakeJobStore)
    _FakeJobStore.verdict = {"status": "done", "response": {"confirmed": True}, "error": None}


def _post(raw_client):
    return raw_client.post(
        "/v1/observations/citizen",
        data={
            "lat": "19.4326", "lng": "-99.1332",
            "observed_at": "2026-06-21T00:00:00Z", "observation_type": "pothole",
        },
        files={"image": ("report.jpg", b"\xff\xd8\xff\xd9", "image/jpeg")},
        headers={"X-Operator-Key": "secret-op-key"},
    )


def test_gate_off_creates_observation(raw_client, gate_env, patched_stores):
    gate_env.setenv("INFERENCE_CONFIRMATION_ENABLED", "false")
    get_settings.cache_clear()
    r = _post(raw_client)
    assert r.status_code == 200
    assert r.json()["observationId"]


def test_gate_on_confirmed_creates_observation(raw_client, gate_env, patched_stores):
    gate_env.setenv("INFERENCE_CONFIRMATION_ENABLED", "true")
    get_settings.cache_clear()
    r = _post(raw_client)
    assert r.status_code == 200
    assert r.json()["observationId"]


def test_gate_on_unconfirmed_returns_422(raw_client, gate_env, patched_stores):
    gate_env.setenv("INFERENCE_CONFIRMATION_ENABLED", "true")
    get_settings.cache_clear()
    _FakeJobStore.verdict = {"status": "done", "response": {"confirmed": False}, "error": None}
    r = _post(raw_client)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "not_confirmed"


def test_gate_on_timeout_returns_422(raw_client, gate_env, patched_stores):
    gate_env.setenv("INFERENCE_CONFIRMATION_ENABLED", "true")
    get_settings.cache_clear()
    _FakeJobStore.verdict = {"status": "timeout", "response": None, "error": "inference timeout"}
    r = _post(raw_client)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "not_confirmed"
