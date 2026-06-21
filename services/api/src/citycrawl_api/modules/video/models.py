"""Versioned video request/result placeholders. Present so a future processor slots in
without a contract reshuffle; intentionally minimal until that design lands."""
from __future__ import annotations
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class VideoCapabilities(_Camel):
    implemented: bool = False
    operations: list[str] = []
