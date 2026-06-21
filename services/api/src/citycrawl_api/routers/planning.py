"""Planning routes. These move the two former client-side mocks behind the API. Both
depend on the PlanningEngine protocol; the bound engine is a labelled mock today and is
reported via the X-Planning-Engine response header."""
from __future__ import annotations
from fastapi import APIRouter, Depends, Response

from citycrawl_api.auth import User, require_user
from citycrawl_api.config import get_settings
from citycrawl_api.modules.planning.engine import OptimizationPlanningEngine
from citycrawl_api.modules.planning.mock import MockPlanningEngine
from citycrawl_api.modules.planning.models import (
    AnalysisRequest,
    ClusterPrioritiesRequest,
    ClusteredPriority,
    PlanResult,
)
from citycrawl_api.modules.planning.protocol import PlanningEngine
from citycrawl_api.modules.planning.traffic import TrafficProvider

router = APIRouter(prefix="/v1/planning", tags=["planning"])


def _build_engine() -> PlanningEngine:
    settings = get_settings()
    if settings.planning_engine == "mock":
        return MockPlanningEngine()
    traffic = TrafficProvider(
        cache_path=settings.traffic_cache_path,
        grid_decimals=settings.traffic_grid_decimals,
    )
    return OptimizationPlanningEngine(traffic)


# Single bound engine, selected by PLANNING_ENGINE. Routes depend only on the protocol.
_engine: PlanningEngine = _build_engine()


@router.post("/optimize", response_model=PlanResult, response_model_by_alias=True)
def optimize(
    request: AnalysisRequest,
    response: Response,
    _user: User = Depends(require_user),
) -> PlanResult:
    response.headers["X-Planning-Engine"] = _engine.name
    return _engine.optimize(request)


@router.post(
    "/priorities:cluster",
    response_model=list[ClusteredPriority],
    response_model_by_alias=True,
)
def cluster_priorities(
    request: ClusterPrioritiesRequest,
    response: Response,
    _user: User = Depends(require_user),
) -> list[ClusteredPriority]:
    response.headers["X-Planning-Engine"] = _engine.name
    return _engine.cluster_priorities(request.points, request.squad_count)
