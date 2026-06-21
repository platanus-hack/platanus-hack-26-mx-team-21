"""The planning contract. Routers depend on this protocol, not on any concrete engine, so
a real optimizer can replace MockPlanningEngine without touching the HTTP layer."""
from __future__ import annotations
from typing import Protocol

from citycrawl_api.modules.planning.models import (
    AnalysisRequest,
    ClusteredPriority,
    PlanResult,
)


class PlanningEngine(Protocol):
    # Stable label surfaced in API metadata so callers can tell a mock from a real engine.
    name: str

    def optimize(self, request: AnalysisRequest) -> PlanResult: ...

    def cluster_priorities(
        self, points: list, squad_count: int | None = None
    ) -> list[ClusteredPriority]: ...
