from __future__ import annotations
from pydantic import BaseModel, field_validator
from external_data.schema import DIMENSIONS, GEOM_QUALITY


class ColumnMap(BaseModel):
    lon: str
    lat: str
    occurred_at: str | None = None
    reported_at: str | None = None
    native_id: str | None = None
    event_subtype: str | None = None
    attributes: list[str] = []


class SourceConfig(BaseModel):
    id: str
    kind: str
    enabled: bool = True
    risk_dimension: str
    event_type: str
    ckan_slug: str | None = None
    resource_match: str | None = None
    feeds: list[str] = []
    column_map: ColumnMap | None = None
    subset: dict | None = None           # {column: [allowed values]} filter on native rows
    geom_quality: str = "point"
    severity: dict[str, float] = {}      # event_subtype -> weight
    default_severity: float = 1.0
    license: str | None = None
    schedule: str | None = None

    @field_validator("risk_dimension")
    @classmethod
    def _dim(cls, v):
        if v not in DIMENSIONS:
            raise ValueError(f"bad dimension {v}")
        return v

    @field_validator("kind")
    @classmethod
    def _kind(cls, v):
        if v not in ("ckan_csv", "news_geocode"):
            raise ValueError(f"bad kind {v}")
        return v

    @field_validator("geom_quality")
    @classmethod
    def _gq(cls, v):
        if v not in GEOM_QUALITY:
            raise ValueError(f"bad geom_quality {v}")
        return v
