"""LLM route test with a fake DraftParser injected via dependency override — no live
provider call. Verifies the route returns a validated PlanDraft and is auth-gated."""
from citycrawl_api.modules.llm.models import (
    DraftChatRequest,
    DraftChatResponse,
    DraftParseRequest,
    PlanDraft,
)
from citycrawl_api.routers.llm import get_draft_parser


class FakeParser:
    name = "fake"

    async def parse(self, request: DraftParseRequest) -> PlanDraft:
        return PlanDraft(issue_type="pothole", budget=2_000_000, region_filter=["005"], squad_count=3)

    async def chat(self, request: DraftChatRequest) -> DraftChatResponse:
        return DraftChatResponse(
            reply="Listo, armé un borrador.",
            draft=PlanDraft(issue_type="pothole", budget=2_000_000, region_filter=["005"], squad_count=3),
        )


def test_parse_requires_auth(raw_client):
    r = raw_client.post("/v1/llm/drafts:parse", json={"prompt": "x"})
    assert r.status_code == 401


def test_parse_returns_draft(app, client):
    app.dependency_overrides[get_draft_parser] = lambda: FakeParser()
    r = client.post("/v1/llm/drafts:parse", json={"prompt": "baches 2 millones en alcaldia 005, 3 cuadrillas"})
    assert r.status_code == 200, r.text
    draft = r.json()
    assert draft["issueType"] == "pothole"
    assert draft["budget"] == 2_000_000
    assert draft["regionFilter"] == ["005"]
    assert draft["squadCount"] == 3
    assert draft["unresolvedTerms"] == [] and draft["warnings"] == []


def test_chat_requires_auth(raw_client):
    r = raw_client.post("/v1/llm/chat", json={"messages": [{"role": "user", "content": "hola"}]})
    assert r.status_code == 401


def test_chat_returns_reply_and_draft(app, client):
    app.dependency_overrides[get_draft_parser] = lambda: FakeParser()
    r = client.post(
        "/v1/llm/chat",
        json={"messages": [{"role": "user", "content": "baches 2 millones, 3 cuadrillas"}]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reply"] == "Listo, armé un borrador."
    assert body["draft"]["issueType"] == "pothole"
    assert body["draft"]["budget"] == 2_000_000
    assert body["draft"]["regionFilter"] == ["005"]
    assert body["draft"]["squadCount"] == 3
