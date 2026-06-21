"""Citizen-report ingestion endpoint. Called server-to-server by the whatsapp-controller
(operator-key auth, no user token). Stores the photo in the observation-thumbnails bucket
and writes a vision.observations row that shows on the priority map."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, UploadFile

from citycrawl_api.auth import require_service
from citycrawl_api.config import get_settings
from citycrawl_api.errors import ApiError
from citycrawl_api.logging import get_logger, log_event
from citycrawl_api.modules.observations.schema import CitizenObservationResult
from citycrawl_api.modules.observations.storage import make_thumbnail_store
from citycrawl_api.modules.observations.store import PgObservationStore

router = APIRouter(prefix="/v1/observations", tags=["observations"])
logger = get_logger()


def _parse_dt(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc)


@router.post("/citizen", response_model=CitizenObservationResult, response_model_by_alias=True)
async def create_citizen_observation(
    lat: float = Form(...),
    lng: float = Form(...),
    observed_at: str = Form(...),
    observation_type: str = Form("pothole"),
    reporter_wa_id: str = Form(""),
    caption: str | None = Form(None),
    kapso_message_id: str = Form(""),
    image: UploadFile = File(...),
    _service: None = Depends(require_service),
) -> CitizenObservationResult:
    settings = get_settings()
    if not settings.db_url:
        raise ApiError(503, "db_unconfigured", "Database is not configured")

    data = await image.read()
    if not data:
        raise ApiError(400, "empty_image", "Image payload is empty")

    observation_id = uuid.uuid4()
    store, bucket = make_thumbnail_store(settings)
    thumbnail_path = f"observations/{observation_id}/report.jpg"
    try:
        store.write_bytes(thumbnail_path, data)
    except Exception as exc:  # noqa: BLE001 - surfaced as a clean 502
        raise ApiError(502, "storage_write_failed", "Could not store the report image") from exc

    pg = PgObservationStore(settings.db_url)
    result = pg.create_citizen_observation(
        observation_id=observation_id,
        observation_type=observation_type,
        lat=lat,
        lng=lng,
        observed_at=_parse_dt(observed_at),
        reporter_wa_id=reporter_wa_id,
        caption=caption,
        thumbnail_bucket=bucket,
        thumbnail_path=thumbnail_path,
    )
    log_event(
        logger,
        "citizen_observation_created",
        observationId=result["observation_id"],
        inBoundary=result["in_boundary"],
        bytes=len(data),
    )
    return CitizenObservationResult(**result)
