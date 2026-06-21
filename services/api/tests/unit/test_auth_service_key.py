"""M-key: require_service prefers INGEST_SERVICE_KEY when set, else falls back to
OPERATOR_API_KEY, so the WhatsApp controller keeps working until the new secret exists."""
import anyio
import pytest

from citycrawl_api.auth import require_service
from citycrawl_api.config import get_settings
from citycrawl_api.errors import ApiError


def _call(key):
    return anyio.run(require_service, key)


@pytest.fixture
def clear():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_fallback_to_operator_key_when_ingest_unset(monkeypatch, clear):
    monkeypatch.setenv("OPERATOR_API_KEY", "op-key")
    monkeypatch.delenv("INGEST_SERVICE_KEY", raising=False)
    get_settings.cache_clear()
    # operator key accepted
    _call("op-key")  # no raise
    with pytest.raises(ApiError) as ei:
        _call("wrong")
    assert ei.value.status_code == 403


def test_ingest_key_used_when_set(monkeypatch, clear):
    monkeypatch.setenv("OPERATOR_API_KEY", "op-key")
    monkeypatch.setenv("INGEST_SERVICE_KEY", "ingest-key")
    get_settings.cache_clear()
    # ingest key accepted
    _call("ingest-key")  # no raise
    # operator key NO LONGER accepted for the ingest route once ingest key is set
    with pytest.raises(ApiError):
        _call("op-key")


def test_unconfigured_returns_503(monkeypatch, clear):
    # A local .env may set OPERATOR_API_KEY, so build a Settings with both keys None and
    # inject it directly rather than relying on env deletion.
    import citycrawl_api.auth as auth_mod
    from citycrawl_api.config import Settings

    unconfigured = Settings(operator_api_key=None, ingest_service_key=None)
    monkeypatch.setattr(auth_mod, "get_settings", lambda: unconfigured)
    with pytest.raises(ApiError) as ei:
        _call(None)
    assert ei.value.status_code == 503
