from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class ExtractedEvent:
    native_id: str
    location_text: str
    occurred_at: datetime | None
    is_incident: bool


@dataclass
class GeocodeResult:
    lon: float
    lat: float
    confidence: float


class Extractor(Protocol):
    def extract(self, title: str, summary: str) -> ExtractedEvent | None: ...


class Geocoder(Protocol):
    def geocode(self, text: str) -> GeocodeResult | None: ...
