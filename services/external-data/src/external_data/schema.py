from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field, field_validator

DIMENSIONS = frozenset({"crash", "violation", "flooding", "road_surface", "crime"})
GEOM_QUALITY = frozenset({"point", "geocoded", "block_centroid"})
GEOM_QUALITY_FACTOR = {"point": 1.0, "geocoded": 0.7, "block_centroid": 0.5}


class Signal(BaseModel):
    signal_id: str
    source_id: str
    risk_dimension: str
    event_type: str
    event_subtype: str | None = None
    lon: float
    lat: float
    geom_quality: str = "point"
    occurred_at: datetime | None = None
    reported_at: datetime | None = None
    severity_weight: float = 1.0
    geocode_confidence: float | None = None
    attributes: dict = Field(default_factory=dict)
    source_object_ref: str | None = None
    source_url: str | None = None
    license: str | None = None
    fetched_at: datetime | None = None

    @field_validator("risk_dimension")
    @classmethod
    def _dim(cls, v: str) -> str:
        if v not in DIMENSIONS:
            raise ValueError(f"unknown risk_dimension {v!r}")
        return v

    @field_validator("geom_quality")
    @classmethod
    def _gq(cls, v: str) -> str:
        if v not in GEOM_QUALITY:
            raise ValueError(f"unknown geom_quality {v!r}")
        return v

    @field_validator("lat")
    @classmethod
    def _lat(cls, v: float) -> float:
        if not -90 <= v <= 90:
            raise ValueError("lat out of range")
        return v

    @field_validator("lon")
    @classmethod
    def _lon(cls, v: float) -> float:
        if not -180 <= v <= 180:
            raise ValueError("lon out of range")
        return v


class Roi(BaseModel):
    risk_dimension: str
    polygon_wkt: str
    centroid_lon: float
    centroid_lat: float
    area_m2: float
    risk_score: float
    signal_count: int
    dominant_type: str
    risk_breakdown: dict
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None
    recency_score: float = 0.0
    description: str = ""
    contributing_signal_ids: list[str] = Field(default_factory=list)
    source_object_refs: list[str] = Field(default_factory=list)


class RoiParams(BaseModel):
    eps_m: float = 100.0
    min_points: int = 5
    buffer_m: float = 15.0
    half_life_days: float = 365.0
    per_dimension: dict[str, dict] = Field(default_factory=dict)

    def for_dimension(self, dim: str) -> "RoiParams":
        base = self.model_dump(exclude={"per_dimension"})
        base.update(self.per_dimension.get(dim, {}))
        return RoiParams(**base)


class RoiRun(BaseModel):
    run_id: str
    dimensions: list[str]
    params: dict
    roi_count: int = 0
