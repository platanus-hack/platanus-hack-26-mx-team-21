"""The draft-parser contract. The router depends on this protocol; the only initial
adapter is AnthropicDraftParser. No unused provider factory or second adapter is added."""
from __future__ import annotations
from typing import Protocol

from citycrawl_api.modules.llm.models import DraftParseRequest, PlanDraft


class DraftParser(Protocol):
    name: str

    async def parse(self, request: DraftParseRequest) -> PlanDraft: ...
