"""#2: citizen-ingest is idempotent on kapso_message_id. A controller retry with the same
message id must NOT re-upload to R2 nor create a second observation; the API returns the
existing observation with deduped=True. Stores/R2 are faked so we observe the call counts."""
import pytest

import citycrawl_api.routers.observations as obs_route
from citycrawl_api.config import get_settings

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 8
EXISTING_ID = "11111111-1111-1111-1111-111111111111"


class _CountingThumbStore:
    writes = 0

    def write_bytes(self, path, data):
        type(self).writes += 1
        return None


def _fake_make_thumbnail_store(settings):
    return _CountingThumbStore(), "observation-thumbnails"


class _DedupingObsStore:
    """lookup_by_message_id returns a hit for the known message id, miss otherwise."""

    create_calls = 0

    def __init__(self, dsn):
        pass

    def lookup_by_message_id(self, kapso_message_id):
        return EXISTING_ID if kapso_message_id == "dup-msg" else None

    def create_citizen_observation(self, **kw):
        type(self).create_calls += 1
        return {
            "observation_id": str(kw["observation_id"]),
            "in_boundary": True,
            "thumbnail_path": kw["thumbnail_path"],
            "deduped": False,
        }


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("OPERATOR_API_KEY", "secret-op-key")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("DB_URL", "postgresql://fake")
    monkeypatch.setenv("INFERENCE_CONFIRMATION_ENABLED", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(obs_route, "make_thumbnail_store", _fake_make_thumbnail_store)
    monkeypatch.setattr(obs_route, "PgObservationStore", _DedupingObsStore)
    _CountingThumbStore.writes = 0
    _DedupingObsStore.create_calls = 0
    yield monkeypatch
    get_settings.cache_clear()


def _post(raw_client, *, kapso_message_id):
    return raw_client.post(
        "/v1/observations/citizen",
        data={
            "lat": "19.4326", "lng": "-99.1332",
            "observed_at": "2026-06-21T00:00:00Z", "observation_type": "pothole",
            "kapso_message_id": kapso_message_id,
        },
        files={"image": ("report.jpg", JPEG, "image/jpeg")},
        headers={"X-Operator-Key": "secret-op-key"},
    )


def test_duplicate_message_id_skips_upload_and_insert(raw_client, env):
    r = _post(raw_client, kapso_message_id="dup-msg")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["observationId"] == EXISTING_ID
    assert body["deduped"] is True
    # The whole point: no re-upload, no second observation.
    assert _CountingThumbStore.writes == 0
    assert _DedupingObsStore.create_calls == 0


def test_new_message_id_uploads_and_creates(raw_client, env):
    r = _post(raw_client, kapso_message_id="fresh-msg")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["observationId"] != EXISTING_ID
    assert body["deduped"] is False
    assert _CountingThumbStore.writes == 1
    assert _DedupingObsStore.create_calls == 1


def test_no_message_id_does_not_dedupe(raw_client, env):
    # Empty kapso_message_id never pre-checks; always uploads + creates.
    r = _post(raw_client, kapso_message_id="")
    assert r.status_code == 200, r.text
    assert r.json()["deduped"] is False
    assert _CountingThumbStore.writes == 1
    assert _DedupingObsStore.create_calls == 1
