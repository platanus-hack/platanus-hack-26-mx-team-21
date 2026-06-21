"""Citizen-report ingestion endpoint. Called server-to-server by the whatsapp-controller
(operator-key auth, no user token). Stores the photo in the observation-thumbnails bucket
and writes a vision.observations row that shows on the priority map."""
from __future__ import annotations

import asyncio
import math
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, UploadFile

from citycrawl_api.auth import require_service
from citycrawl_api.config import get_settings
from citycrawl_api.errors import ApiError
from citycrawl_api.logging import get_logger, log_event
from citycrawl_api.modules.observations.inference import (
    PgInferenceJobStore,
    is_confirmed,
)
from citycrawl_api.modules.observations.schema import CitizenObservationResult
from citycrawl_api.modules.observations.storage import make_thumbnail_store, object_locator
from citycrawl_api.modules.observations.store import PgObservationStore

router = APIRouter(prefix="/v1/observations", tags=["observations"])
logger = get_logger()

# Accepted upload content types and their magic-byte signatures. We sniff the bytes (not
# just the declared content-type, which is client-controlled) and reject mismatches.
_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


def _sniff_image(data: bytes) -> str | None:
    """Return a canonical image type from the leading bytes, or None if unrecognized.
    JPEG: FF D8 FF; PNG: 89 50 4E 47 0D 0A 1A 0A; WEBP: 'RIFF'....'WEBP'."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _parse_dt(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc)


# Bounded-read chunk size. We never call the unbounded image.read(): a chunked
# (Transfer-Encoding: chunked) upload has no Content-Length, so the middleware can't see it,
# and an unbounded read would buffer the whole stream into memory (OOM). We accumulate in
# chunks and abort with 413 the moment the running total exceeds max_upload_bytes.
_READ_CHUNK_BYTES = 64 * 1024


async def _read_bounded(image: UploadFile, max_bytes: int) -> bytes:
    """Read the upload in fixed-size chunks, aborting with 413 once the total exceeds
    max_bytes. Defends against a chunked upload bypassing the Content-Length middleware."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await image.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ApiError(
                413, "payload_too_large",
                "Image exceeds the maximum allowed size",
                {"maxBytes": max_bytes},
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/citizen", response_model=CitizenObservationResult, response_model_by_alias=True)
async def create_citizen_observation(
    lat: float = Form(..., ge=-90, le=90),
    lng: float = Form(..., ge=-180, le=180),
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

    # Reject non-finite coordinates (NaN/inf slip past ge/le bounds checks).
    if not (math.isfinite(lat) and math.isfinite(lng)):
        raise ApiError(400, "invalid_coordinates", "lat/lng must be finite numbers")

    # (a) Declared content-type must be in the allowlist.
    if (image.content_type or "").split(";")[0].strip().lower() not in _ALLOWED_IMAGE_TYPES:
        raise ApiError(
            400, "unsupported_image_type",
            "Image must be JPEG, PNG, or WebP",
        )

    # Read the upload in bounded chunks (NOT an unbounded image.read()) so a chunked upload
    # that skips the Content-Length middleware still can't OOM the worker.
    data = await _read_bounded(image, settings.max_upload_bytes)
    # (c) Reject empty payloads.
    if not data:
        raise ApiError(400, "empty_image", "Image payload is empty")
    # (b) Magic-byte sniff: the actual bytes must be a real image and match the allowlist.
    sniffed = _sniff_image(data)
    if sniffed is None:
        raise ApiError(
            400, "invalid_image",
            "Uploaded bytes are not a valid JPEG, PNG, or WebP image",
        )

    pg = PgObservationStore(settings.db_url)

    # Idempotency pre-check: a controller retry sends the same kapso_message_id. Look it up
    # BEFORE uploading to R2 so a duplicate doesn't re-upload the photo. The authoritative,
    # race-safe dedupe still happens in-transaction inside create_citizen_observation.
    if kapso_message_id:
        existing_id = pg.lookup_by_message_id(kapso_message_id)
        if existing_id is not None:
            log_event(
                logger,
                "citizen_observation_deduped",
                observationId=existing_id,
                stage="pre_upload",
            )
            return CitizenObservationResult(
                observation_id=existing_id,
                in_boundary=False,
                thumbnail_path=f"observations/{existing_id}/report.jpg",
                deduped=True,
            )

    observation_id = uuid.uuid4()
    store, bucket = make_thumbnail_store(settings)
    thumbnail_path = f"observations/{observation_id}/report.jpg"
    try:
        store.write_bytes(thumbnail_path, data)
    except Exception as exc:  # noqa: BLE001 - surfaced as a clean 502
        raise ApiError(502, "storage_write_failed", "Could not store the report image") from exc

    # Confirmation gate: the photo must be confirmed by the non-public inference server
    # before we create the observation.
    jobs = PgInferenceJobStore(settings.db_url)
    job_id = jobs.enqueue(
        observation_id=observation_id,
        r2_url=object_locator(bucket, thumbnail_path),
        thinking_mode=settings.inference_thinking_mode,
    )
    verdict = await asyncio.to_thread(
        jobs.wait_for_result,
        job_id,
        timeout_s=settings.inference_timeout_s,
        poll_interval_s=settings.inference_poll_interval_s,
    )
    if not is_confirmed(verdict):
        log_event(
            logger,
            "citizen_observation_unconfirmed",
            observationId=str(observation_id),
            status=verdict["status"],
        )
        raise ApiError(
            422, "not_confirmed",
            "The photo could not be confirmed as a valid report",
        )

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
        kapso_message_id=kapso_message_id,
    )
    log_event(
        logger,
        "citizen_observation_deduped" if result.get("deduped") else "citizen_observation_created",
        observationId=result["observation_id"],
        inBoundary=result["in_boundary"],
        deduped=bool(result.get("deduped")),
        bytes=len(data),
    )
    return CitizenObservationResult(**result)
