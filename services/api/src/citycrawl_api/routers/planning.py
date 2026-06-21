"""Planning routes. These move the two former client-side mocks behind the API. Both
depend on the PlanningEngine protocol; the bound engine is a labelled mock today and is
reported via the X-Planning-Engine response header."""
from __future__ import annotations
from fastapi import APIRouter, Depends, Response

from citycrawl_api.auth import User, require_user
from citycrawl_api.modules.planning.mock import MockPlanningEngine
from citycrawl_api.modules.planning.models import (
    AnalysisRequest,
    ClusterPrioritiesRequest,
    ClusteredPriority,
    PlanResult,
)

router = APIRouter(prefix="/v1/planning", tags=["planning"])

# Single bound engine. Swap this line when a real optimizer exists; routes are unchanged.
_engine = MockPlanningEngine()


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
