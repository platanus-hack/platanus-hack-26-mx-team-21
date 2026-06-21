"""Draft-parsing contract. The request carries the prompt plus the issue-type and region
choices already visible to the frontend, so the parser can resolve names to stable codes.
The response is an editable PlanDraft: recognized scalars may be null; list fields are
always arrays. Cost overrides are not inferred in this version."""
from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class IssueTypeChoice(_Camel):
    slug: str
    label: str


class RegionChoice(_Camel):
    cve: str
    name: str


class DraftParseRequest(_Camel):
    prompt: str
    issue_types: list[IssueTypeChoice] = []
    regions: list[RegionChoice] = []


class PlanDraft(_Camel):
    issue_type: str | None = None
    budget: float | None = None
    region_filter: list[str] = Field(default_factory=list)
    squad_count: int | None = None
    unresolved_terms: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# --- conversational chat contract --------------------------------------------
# The chat turn carries the full message history plus the draft accumulated so far,
# so the assistant can answer follow-ups in Spanish and update only what changed.


class ChatMessage(_Camel):
    role: str  # "user" | "assistant"
    content: str


class DraftChatRequest(_Camel):
    messages: list[ChatMessage]
    draft: PlanDraft | None = None
    issue_types: list[IssueTypeChoice] = []
    regions: list[RegionChoice] = []


class DraftChatResponse(_Camel):
    reply: str
    draft: PlanDraft
