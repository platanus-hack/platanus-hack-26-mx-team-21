"""Shared test fixtures. The default `client` authenticates every request with a fake user
so route logic can be tested without a live Supabase call; auth-failure tests use the
`raw_client` (no overrides)."""
from __future__ import annotations
import pytest
from fastapi.testclient import TestClient

from citycrawl_api.auth import User, require_user
from citycrawl_api.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    app.dependency_overrides[require_user] = lambda: User(id="test-user", email="t@example.com")
    c = TestClient(app, raise_server_exceptions=False)
    yield c
    app.dependency_overrides.clear()


@pytest.fixture
def raw_client(app):
    return TestClient(app, raise_server_exceptions=False)
