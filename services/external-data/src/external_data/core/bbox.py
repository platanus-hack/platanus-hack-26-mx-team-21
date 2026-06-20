from __future__ import annotations
import math
from datetime import datetime

CDMX_BBOX = (-99.36, 19.04, -98.94, 19.59)  # minlon, minlat, maxlon, maxlat


def in_cdmx(lon: float, lat: float) -> bool:
    mnx, mny, mxx, mxy = CDMX_BBOX
    return mnx <= lon <= mxx and mny <= lat <= mxy


def recency_weight(occurred_at: datetime | None, half_life_days: float, now: datetime) -> float:
    if occurred_at is None:
        return 0.5
    age_days = max(0.0, (now - occurred_at).total_seconds() / 86400.0)
    return math.exp(-math.log(2) * age_days / half_life_days)
