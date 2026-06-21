"""External dataset refresh. Operator-protected. Because a refresh can take minutes, the
endpoint streams newline-delimited JSON progress records over one long-lived request.
Authentication and configuration failures are raised by the dependencies BEFORE streaming
begins (normal HTTP error); a failure after streaming starts is a terminal NDJSON error
record, since the HTTP status can no longer change."""
from __future__ import annotations
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from citycrawl_api.auth import User, require_operator
from citycrawl_api.config import get_settings
from citycrawl_api.logging import get_request_id
from citycrawl_api.modules.datasets.service import DatasetRefreshService

router = APIRouter(prefix="/v1/datasets", tags=["datasets"])


class RefreshRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    source_ids: list[str] = []


@router.post("/refresh")
def refresh(
    request: RefreshRequest | None = None,
    _operator: User = Depends(require_operator),
) -> StreamingResponse:
    settings = get_settings()
    request_id = get_request_id()
    source_ids = request.source_ids if request else []
    service = DatasetRefreshService(settings)

    def stream():
        for record in service.run(source_ids=source_ids, request_id=request_id):
            yield json.dumps(record) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")
