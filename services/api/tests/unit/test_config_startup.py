"""M-CORS / M-storage: startup validation. CORS must not be wildcard/empty while credentials
are on; in production STORAGE_BACKEND must be 'r2' (else fail fast); elsewhere just warn."""
import pytest

from citycrawl_api.config import Settings


def _s(**kw):
    kw.setdefault("allowed_origins", "https://app.example.com")
    return Settings(**kw)


def test_wildcard_origin_warns_not_raises(caplog):
    # Downgraded from a hard failure to a loud warning so a misconfigured deployed
    # ALLOWED_ORIGINS can't crash the API on boot (Starlette already refuses to echo
    # a wildcard origin with credentials on).
    with caplog.at_level("WARNING"):
        _s(allowed_origins="*").validate_startup()
    assert any("cors_origins_insecure" in r.message for r in caplog.records)


def test_empty_origins_warns_not_raises(caplog):
    with caplog.at_level("WARNING"):
        _s(allowed_origins="").validate_startup()
    assert any("cors_origins_insecure" in r.message for r in caplog.records)


def test_explicit_origins_ok_in_dev():
    # Local backend in development only warns; must not raise.
    _s(app_env="development", storage_backend="local").validate_startup()


def test_production_requires_r2():
    with pytest.raises(RuntimeError):
        _s(app_env="production", storage_backend="local").validate_startup()


def test_production_r2_ok():
    _s(app_env="production", storage_backend="r2").validate_startup()


def test_fly_signal_forces_production(monkeypatch):
    monkeypatch.setenv("FLY_APP_NAME", "citycrawl-api")
    s = _s(app_env="development", storage_backend="local")
    assert s.is_production is True
    with pytest.raises(RuntimeError):
        s.validate_startup()


def test_cors_allow_headers_no_wildcard():
    s = _s()
    assert "*" not in s.cors_allow_headers
    assert "Authorization" in s.cors_allow_headers
    assert "X-Operator-Key" in s.cors_allow_headers
