"""Natural-language draft parsing. Returns an editable PlanDraft for the frontend dock to
review; it never starts optimization or submits an analysis. The concrete parser is bound
via a dependency so tests can inject a fake without a live provider call."""
from __future__ import annotations
import threading
import time

from fastapi import APIRouter, Depends, Request

from citycrawl_api.auth import User, require_user
from citycrawl_api.config import get_settings
from citycrawl_api.errors import ApiError
from citycrawl_api.modules.llm.anthropic import AnthropicDraftParser
from citycrawl_api.modules.llm.models import DraftParseRequest, PlanDraft
from citycrawl_api.modules.llm.protocol import DraftParser

router = APIRouter(prefix="/v1/llm", tags=["llm"])


class _FixedWindowLimiter:
    """Per-key fixed-window rate limiter to curb denial-of-wallet on the LLM parse route.

    LIMITATION: state is in-process, so the limit is enforced PER WORKER, not globally. For
    a hard global cap, move this to a shared store (e.g. Redis). The map is bounded by
    pruning expired windows on each call, so memory stays proportional to active callers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # key -> (window_start_epoch, count)
        self._buckets: dict[str, tuple[float, int]] = {}

    def allow(self, key: str, limit: int, window_s: float) -> bool:
        now = time.monotonic()
        with self._lock:
            # Prune expired windows to keep the map bounded.
            if len(self._buckets) > 4096:
                self._buckets = {
                    k: v for k, v in self._buckets.items() if now - v[0] < window_s
                }
            start, count = self._buckets.get(key, (now, 0))
            if now - start >= window_s:
                start, count = now, 0
            if count >= limit:
                return False
            self._buckets[key] = (start, count + 1)
            return True


_parse_limiter = _FixedWindowLimiter()


def get_draft_parser() -> DraftParser:
    return AnthropicDraftParser(get_settings())


@router.post("/drafts:parse", response_model=PlanDraft, response_model_by_alias=True)
async def parse_draft(
    request: DraftParseRequest,
    http_request: Request,
    parser: DraftParser = Depends(get_draft_parser),
    user: User = Depends(require_user),
) -> PlanDraft:
    settings = get_settings()
    # Per-user when we have an id, else per-IP. Each call spends Anthropic budget.
    key = f"user:{user.id}" if user.id else f"ip:{http_request.client.host if http_request.client else 'unknown'}"
    if not _parse_limiter.allow(key, settings.llm_parse_rate_limit, settings.llm_parse_rate_window_s):
        raise ApiError(
            429, "rate_limited",
            "Too many draft-parse requests; please slow down",
            {"limit": settings.llm_parse_rate_limit, "windowSeconds": settings.llm_parse_rate_window_s},
        )
    return await parser.parse(request)
