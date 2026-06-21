"""Draft-parsing contract. The request carries the prompt plus the issue-type and region
choices already visible to the frontend, so the parser can resolve names to stable codes.
The response is an editable PlanDraft: recognized scalars may be null; list fields are
always arrays. Cost overrides are not inferred in this version."""
from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# Bounds on client-supplied input. These cap the system-prompt size (denial-of-wallet:
# every parse spends Anthropic budget) and bound how much untrusted text gets interpolated
# into the prompt. The anthropic adapter applies stricter per-field validation on top.
MAX_PROMPT_CHARS = 4000
MAX_CHOICES = 200
MAX_LABEL_CHARS = 80
MAX_SLUG_CHARS = 40
MAX_CVE_CHARS = 16


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class IssueTypeChoice(_Camel):
    slug: str = Field(min_length=1, max_length=MAX_SLUG_CHARS)
    label: str = Field(min_length=1, max_length=MAX_LABEL_CHARS)


class RegionChoice(_Camel):
    cve: str = Field(min_length=1, max_length=MAX_CVE_CHARS)
    name: str = Field(min_length=1, max_length=MAX_LABEL_CHARS)


class DraftParseRequest(_Camel):
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    issue_types: list[IssueTypeChoice] = Field(default=[], max_length=MAX_CHOICES)
    regions: list[RegionChoice] = Field(default=[], max_length=MAX_CHOICES)


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
    # True only when the user asked to run the plan now; the frontend triggers optimization.
    generate: bool = False
