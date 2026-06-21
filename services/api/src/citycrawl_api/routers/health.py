"""Public liveness endpoint. It does NOT call Supabase, Anthropic, or R2, so an upstream
outage cannot cause Fly to restart a healthy process."""
from __future__ import annotations
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}
