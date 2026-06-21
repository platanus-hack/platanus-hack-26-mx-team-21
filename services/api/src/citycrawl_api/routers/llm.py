"""Natural-language draft parsing. Returns an editable PlanDraft for the frontend dock to
review; it never starts optimization or submits an analysis. The concrete parser is bound
via a dependency so tests can inject a fake without a live provider call."""
from __future__ import annotations
from fastapi import APIRouter, Depends

from citycrawl_api.auth import User, require_user
from citycrawl_api.config import get_settings
from citycrawl_api.modules.llm.anthropic import AnthropicDraftParser
from citycrawl_api.modules.llm.models import DraftParseRequest, PlanDraft
from citycrawl_api.modules.llm.protocol import DraftParser

router = APIRouter(prefix="/v1/llm", tags=["llm"])


def get_draft_parser() -> DraftParser:
    return AnthropicDraftParser(get_settings())


@router.post("/drafts:parse", response_model=PlanDraft, response_model_by_alias=True)
async def parse_draft(
    request: DraftParseRequest,
    parser: DraftParser = Depends(get_draft_parser),
    _user: User = Depends(require_user),
) -> PlanDraft:
    return await parser.parse(request)
