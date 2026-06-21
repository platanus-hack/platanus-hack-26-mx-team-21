"""Builds an ObjectStore rooted at the observation-thumbnails bucket. Citizen photos live
there (same bucket the broker serves to the app), separate from the external-data bucket the
datasets module uses. The DB always records the logical bucket name 'observation-thumbnails';
in local dev the bytes go under {local_root}/observation-thumbnails/."""
from __future__ import annotations

import fsspec

from citycrawl_api.config import Settings
from citycrawl_api.errors import ApiError
from citycrawl_api.modules.datasets.core.storage import ObjectStore

THUMBNAIL_BUCKET = "observation-thumbnails"


def make_thumbnail_store(settings: Settings) -> tuple[ObjectStore, str]:
    """Returns (store, logical_bucket_name). The logical name is what gets written to the DB
    so the broker can resolve it, regardless of the local/remote backend."""
    backend = settings.storage_backend
    if backend == "r2":
        if not settings.r2_s3_endpoint:
            raise ApiError(503, "storage_unconfigured", "R2 endpoint is not configured")
        fs = fsspec.filesystem(
            "s3",
            key=settings.r2_access_key,
            secret=settings.r2_secret,
            client_kwargs={"endpoint_url": settings.r2_s3_endpoint},
        )
        return ObjectStore(fs, THUMBNAIL_BUCKET), THUMBNAIL_BUCKET
    if backend == "supabase":
        fs = fsspec.filesystem(
            "s3",
            key=settings.supabase_s3_access_key,
            secret=settings.supabase_s3_secret,
            client_kwargs={"endpoint_url": settings.supabase_s3_endpoint},
        )
        return ObjectStore(fs, THUMBNAIL_BUCKET), THUMBNAIL_BUCKET
    fs = fsspec.filesystem("file")
    return ObjectStore(fs, f"{settings.local_root}/{THUMBNAIL_BUCKET}"), THUMBNAIL_BUCKET


def object_locator(bucket: str, path: str) -> str:
    """Backend-agnostic locator handed to the inference server (which holds R2 creds).
    The logical bucket name is what the DB records, so 's3://{bucket}/{path}' resolves the
    same object the broker serves."""
    return f"s3://{bucket}/{path}"
