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

    def lookup_by_message_id(self, kapso_message_id):
        return None

    def create_citizen_observation(self, **kw):
        return {
            "observation_id": str(kw["observation_id"]),
            "in_boundary": True,
            "thumbnail_path": kw["thumbnail_path"],
            "deduped": False,
        }


class _ConfirmingJobStore:
    """Stands in for the inference confirmation gate: always confirms, no DB."""

    def __init__(self, dsn):
        pass

    def enqueue(self, **kw):
        import uuid

        return uuid.uuid4()

    def wait_for_result(self, job_id, **kw):
        return {"status": "done", "response": {"confirmed": True}, "error": None}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("OPERATOR_API_KEY", "secret-op-key")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("DB_URL", "postgresql://fake")
    get_settings.cache_clear()
    monkeypatch.setattr(obs_route, "make_thumbnail_store", _fake_make_thumbnail_store)
    monkeypatch.setattr(obs_route, "PgObservationStore", _FakeObsStore)
    monkeypatch.setattr(obs_route, "PgInferenceJobStore", _ConfirmingJobStore)
    yield monkeypatch
    get_settings.cache_clear()


def _post(raw_client, *, content, filename="report.jpg", content_type="image/jpeg",
          lat="19.4326", lng="-99.1332"):
    return raw_client.post(
        "/v1/observations/citizen",
        data={
            "lat": lat, "lng": lng,
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
    # The bounded chunked read aborts with 413 once the running total exceeds the cap, even
    # without a (spoofable/absent) Content-Length. Lower the cap and oversend.
    env.setenv("MAX_UPLOAD_BYTES", "16")
    get_settings.cache_clear()
    r = _post(raw_client, content=JPEG + b"\x00" * 64, content_type="image/jpeg")
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "payload_too_large"


@pytest.mark.parametrize("lat,lng", [
    ("91", "0"), ("-91", "0"), ("0", "181"), ("0", "-181"),
])
def test_out_of_range_coordinates_rejected(raw_client, env, lat, lng):
    # ge/le Form bounds -> 422 invalid_request before the route body runs.
    r = _post(raw_client, content=JPEG, lat=lat, lng=lng)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_request"


@pytest.mark.parametrize("lat,lng", [("nan", "0"), ("0", "inf"), ("0", "-inf")])
def test_non_finite_coordinates_rejected(raw_client, env, lat, lng):
    # NaN/inf are rejected before the handler body: pydantic's ge/le bound comparison fails
    # for non-finite values (422 invalid_request). The explicit isfinite() guard in the route
    # is defense-in-depth should the bounds ever be loosened.
    r = _post(raw_client, content=JPEG, lat=lat, lng=lng)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_request"
