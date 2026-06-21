from __future__ import annotations
import math
from datetime import datetime, timezone

CDMX_BBOX = (-99.36, 19.04, -98.94, 19.59)  # minlon, minlat, maxlon, maxlat


def in_cdmx(lon: float, lat: float) -> bool:
    mnx, mny, mxx, mxy = CDMX_BBOX
    return mnx <= lon <= mxx and mny <= lat <= mxy


def _as_utc(dt: datetime) -> datetime:
    # Real source dates parse as timezone-naive; treat them as UTC so arithmetic
    # against a tz-aware `now` never raises.
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def recency_weight(occurred_at: datetime | None, half_life_days: float, now: datetime) -> float:
    if occurred_at is None:
        return 0.5
    age_days = max(0.0, (_as_utc(now) - _as_utc(occurred_at)).total_seconds() / 86400.0)
    return math.exp(-math.log(2) * age_days / half_life_days)
