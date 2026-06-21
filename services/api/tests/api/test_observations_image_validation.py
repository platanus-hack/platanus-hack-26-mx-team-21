"""H1/H2: the citizen-ingest endpoint validates the uploaded image (content-type allowlist +
magic-byte sniff + empty/oversize rejection) before storing it. Stores are faked so we only
exercise the validation branch; a valid image still reaches the (fake) store and creates a row."""
import pytest

import citycrawl_api.routers.observations as obs_route
from citycrawl_api.config import get_settings

# Minimal valid signatures.
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 8
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 16


class _FakeThumbStore:
    def write_bytes(self, path, data):
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


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("OPERATOR_API_KEY", "secret-op-key")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("DB_URL", "postgresql://fake")
    monkeypatch.setenv("INFERENCE_CONFIRMATION_ENABLED", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(obs_route, "make_thumbnail_store", _fake_make_thumbnail_store)
    monkeypatch.setattr(obs_route, "PgObservationStore", _FakeObsStore)
    yield monkeypatch
    get_settings.cache_clear()


def _post(raw_client, *, content, filename="report.jpg", content_type="image/jpeg"):
    return raw_client.post(
        "/v1/observations/citizen",
        data={
            "lat": "19.4326", "lng": "-99.1332",
            "observed_at": "2026-06-21T00:00:00Z", "observation_type": "pothole",
        },
        files={"image": (filename, content, content_type)},
        headers={"X-Operator-Key": "secret-op-key"},
    )


@pytest.mark.parametrize("content,ct", [(JPEG, "image/jpeg"), (PNG, "image/png"), (WEBP, "image/webp")])
def test_valid_images_accepted(raw_client, env, content, ct):
    r = _post(raw_client, content=content, content_type=ct)
    assert r.status_code == 200, r.text
    assert r.json()["observationId"]


def test_empty_image_rejected(raw_client, env):
    r = _post(raw_client, content=b"", content_type="image/jpeg")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "empty_image"


def test_disallowed_content_type_rejected(raw_client, env):
    r = _post(raw_client, content=JPEG, content_type="application/pdf")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "unsupported_image_type"


def test_magic_byte_mismatch_rejected(raw_client, env):
    # Claims JPEG but bytes are not an image -> magic-byte sniff rejects.
    r = _post(raw_client, content=b"%PDF-1.4 not an image", content_type="image/jpeg")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_image"


def test_oversize_image_rejected_on_read(raw_client, env):
    # Below the middleware's Content-Length check is hard to trigger via TestClient, so we
    # lower the cap and rely on the explicit len(data) guard in the route.
    env.setenv("MAX_UPLOAD_BYTES", "16")
    get_settings.cache_clear()
    r = _post(raw_client, content=JPEG + b"\x00" * 64, content_type="image/jpeg")
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "payload_too_large"
