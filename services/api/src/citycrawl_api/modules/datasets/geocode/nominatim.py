from __future__ import annotations
import httpx
from citycrawl_api.modules.datasets.geocode.base import GeocodeResult


class NominatimGeocoder:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def geocode(self, text: str) -> GeocodeResult | None:
        r = httpx.get(
            f"{self.base_url}/search",
            params={
                "q": f"{text}, Ciudad de México, México", "format": "json", "limit": 1,
                "viewbox": "-99.36,19.59,-98.94,19.04", "bounded": 1,
            },
            headers={"User-Agent": "external-data-pipeline/0.1"},
            timeout=30,
        )
        hits = r.json()
        if not hits:
            return None
        h = hits[0]
        return GeocodeResult(
            lon=float(h["lon"]), lat=float(h["lat"]),
            confidence=min(1.0, float(h.get("importance", 0.5))),
        )
