from datetime import datetime, timezone
from citycrawl_api.modules.datasets.geocode.base import ExtractedEvent, GeocodeResult
from citycrawl_api.modules.datasets.adapters.news_geocode import entries_to_signals
from citycrawl_api.modules.datasets.registry.loader import get_source

NOW = datetime(2026, 6, 20, tzinfo=timezone.utc)


class FakeExtractor:
    def extract(self, title, summary):
        if "choque" in (title + summary).lower():
            return ExtractedEvent(native_id=title, location_text="Av. Reforma y Bucareli",
                                  occurred_at=NOW, is_incident=True)
        return ExtractedEvent(native_id=title, location_text="", occurred_at=None, is_incident=False)


class FakeGeocoder:
    def geocode(self, text):
        if "Reforma" in text:
            return GeocodeResult(lon=-99.146, lat=19.435, confidence=0.9)
        return None


def test_entries_to_signals_filters_and_geocodes():
    src = get_source("news_nota_roja")
    entries = [
        {"id": "1", "title": "Choque en Reforma", "summary": "dos autos"},
        {"id": "2", "title": "Clima soleado hoy", "summary": "sin novedades"},
    ]
    sigs = entries_to_signals(entries, src, FakeExtractor(), FakeGeocoder(), NOW)
    assert len(sigs) == 1
    assert sigs[0].geom_quality == "geocoded"
    assert sigs[0].geocode_confidence == 0.9
    assert sigs[0].risk_dimension == "crash"
