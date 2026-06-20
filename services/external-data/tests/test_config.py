from external_data import __version__
from external_data.config import get_settings


def test_version_present():
    assert isinstance(__version__, str) and __version__


def test_settings_defaults(monkeypatch):
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    get_settings.cache_clear()
    s = get_settings()
    assert s.storage_backend == "local"
    assert s.external_data_bucket == "external-data"


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "supabase")
    get_settings.cache_clear()
    assert get_settings().storage_backend == "supabase"
    get_settings.cache_clear()
