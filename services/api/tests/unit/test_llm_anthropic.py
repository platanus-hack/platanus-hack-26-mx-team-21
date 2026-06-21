"""Anthropic adapter unit tests with a mocked client (no network). Covers structured-output
validation and rejection of malformed/missing tool output."""
import asyncio
from types import SimpleNamespace

import pytest

from citycrawl_api.config import Settings
from citycrawl_api.errors import ApiError
from citycrawl_api.modules.llm.anthropic import AnthropicDraftParser
from citycrawl_api.modules.llm.models import DraftParseRequest


class _FakeMessages:
    def __init__(self, content):
        self._content = content

    async def create(self, **kwargs):
        return SimpleNamespace(content=self._content)


class _FakeClient:
    def __init__(self, content):
        self.messages = _FakeMessages(content)


def _parser(content):
    settings = Settings(anthropic_api_key="x")
    return AnthropicDraftParser(settings, client=_FakeClient(content))


def _block(input_):
    return SimpleNamespace(type="tool_use", name="emit_plan_draft", input=input_)


def test_valid_structured_output():
    parser = _parser([_block({"regionFilter": ["005"], "unresolvedTerms": [], "warnings": [],
                              "issueType": "pothole", "budget": 1000000, "squadCount": 2})])
    draft = asyncio.run(parser.parse(DraftParseRequest(prompt="x")))
    assert draft.issue_type == "pothole"
    assert draft.region_filter == ["005"]
    assert draft.squad_count == 2


def test_missing_tool_block_rejected():
    parser = _parser([SimpleNamespace(type="text", text="hi")])
    with pytest.raises(ApiError) as ei:
        asyncio.run(parser.parse(DraftParseRequest(prompt="x")))
    assert ei.value.status_code == 502
    assert ei.value.code == "llm_invalid_output"


def test_invalid_output_rejected():
    # squadCount as a non-integer string that cannot coerce
    parser = _parser([_block({"regionFilter": "not-a-list", "unresolvedTerms": [], "warnings": []})])
    with pytest.raises(ApiError) as ei:
        asyncio.run(parser.parse(DraftParseRequest(prompt="x")))
    assert ei.value.code == "llm_invalid_output"
