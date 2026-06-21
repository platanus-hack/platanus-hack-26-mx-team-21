"""Video extension point. Only a capabilities probe exists; it accurately reports that
processing is not implemented. Requires a valid user token like the other /v1 routes."""
from __future__ import annotations
from fastapi import APIRouter, Depends

from citycrawl_api.auth import User, require_user
from citycrawl_api.modules.video.models import VideoCapabilities
from citycrawl_api.modules.video.service import capabilities

router = APIRouter(prefix="/v1/video", tags=["video"])


@router.get("/capabilities", response_model=VideoCapabilities, response_model_by_alias=True)
def get_capabilities(_user: User = Depends(require_user)) -> VideoCapabilities:
    return capabilities()
