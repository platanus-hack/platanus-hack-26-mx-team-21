"""Descarga imágenes de Cloudflare R2 (S3-compatible) para Etapa 2.

r2_url de la fila del job = "s3://observation-thumbnails/observations/<id>/report.jpg"
"""
from __future__ import annotations

import os

import boto3

_s3 = None


def _client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client(
            "s3",
            endpoint_url=os.environ["R2_S3_ENDPOINT"],
            aws_access_key_id=os.environ["R2_ACCESS_KEY"],
            aws_secret_access_key=os.environ["R2_SECRET"],
            region_name="auto",
        )
    return _s3


def parse_s3_url(r2_url: str) -> tuple[str, str]:
    """s3://bucket/key -> (bucket, key). Lanza ValueError si no es s3:// o no trae key."""
    if not r2_url.startswith("s3://"):
        raise ValueError(f"r2_url no es s3://: {r2_url[:60]}")
    rest = r2_url.removeprefix("s3://")
    if "/" not in rest:
        raise ValueError(f"r2_url sin key: {r2_url[:60]}")
    bucket, key = rest.split("/", 1)
    if not bucket or not key:
        raise ValueError(f"r2_url con bucket/key vacío: {r2_url[:60]}")
    return bucket, key


def fetch(r2_url: str) -> bytes:
    """s3://bucket/key -> bytes."""
    bucket, key = parse_s3_url(r2_url)
    return _client().get_object(Bucket=bucket, Key=key)["Body"].read()
