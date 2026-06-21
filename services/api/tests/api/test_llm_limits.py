"""M-AI-1: denial-of-wallet hardening on POST /v1/llm/drafts:parse — Pydantic input bounds,
a per-user in-memory rate limiter, plus the H2 body-size middleware (413 on Content-Length)."""
import citycrawl_api.routers.llm as llm_route
from citycrawl_api.config import get_settings
from citycrawl_api.modules.llm.models import DraftParseRequest, PlanDraft
from citycrawl_api.routers.llm import get_draft_parser


class FakeParser:
    name = "fake"

    async def parse(self, request: DraftParseRequest) -> PlanDraft:
        return PlanDraft(issue_type="pothole")


def _fresh_limiter():
    # Each test gets an isolated limiter so windows don't bleed across tests.
    llm_route._parse_limiter = llm_route._FixedWindowLimiter()


def test_prompt_too_long_rejected(app, client):
    app.dependency_overrides[get_draft_parser] = lambda: FakeParser()
    r = client.post("/v1/llm/drafts:parse", json={"prompt": "x" * 5000})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_request"


def test_too_many_issue_types_rejected(app, client):
    app.dependency_overrides[get_draft_parser] = lambda: FakeParser()
    payload = {"prompt": "x", "issueTypes": [{"slug": "a", "label": "L"} for _ in range(201)]}
    r = client.post("/v1/llm/drafts:parse", json=payload)
    assert r.status_code == 422


def test_rate_limit_returns_429(app, client, monkeypatch):
    _fresh_limiter()
    monkeypatch.setenv("LLM_PARSE_RATE_LIMIT", "3")
    monkeypatch.setenv("LLM_PARSE_RATE_WINDOW_S", "60")
    get_settings.cache_clear()
    app.dependency_overrides[get_draft_parser] = lambda: FakeParser()
    codes = [client.post("/v1/llm/drafts:parse", json={"prompt": "x"}).status_code for _ in range(4)]
    get_settings.cache_clear()
    assert codes[:3] == [200, 200, 200]
    assert codes[3] == 429


def test_body_size_middleware_413(app, client, monkeypatch):
    # Content-Length over the cap is rejected by the middleware before route logic runs.
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "10")
    get_settings.cache_clear()
    # Rebuild app so the middleware closure picks up the new cap.
    from citycrawl_api.main import create_app
    from fastapi.testclient import TestClient
    from citycrawl_api.auth import require_user, User

    fresh = create_app()
    fresh.dependency_overrides[require_user] = lambda: User(id="u", email="e@x.com")
    fresh.dependency_overrides[get_draft_parser] = lambda: FakeParser()
    c = TestClient(fresh, raise_server_exceptions=False)
    r = c.post("/v1/llm/drafts:parse", json={"prompt": "x" * 1000})
    get_settings.cache_clear()
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "payload_too_large"
