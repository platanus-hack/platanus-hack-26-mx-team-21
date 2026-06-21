from __future__ import annotations
from datetime import datetime
import feedparser
from citycrawl_api.modules.datasets.adapters.base import ExtractContext
from citycrawl_api.modules.datasets.core.bbox import in_cdmx
from citycrawl_api.modules.datasets.core.ids import signal_id
from citycrawl_api.modules.datasets.geocode.base import Extractor, Geocoder
from citycrawl_api.modules.datasets.net import OutboundFetchError, safe_get
from citycrawl_api.modules.datasets.registry.models import SourceConfig
from citycrawl_api.modules.datasets.schema import Signal


def entries_to_signals(entries: list[dict], source: SourceConfig,
                       extractor: Extractor, geocoder: Geocoder, now: datetime) -> list[Signal]:
    out: list[Signal] = []
    for e in entries:
        ev = extractor.extract(e.get("title", ""), e.get("summary", ""))
        if not ev or not ev.is_incident or not ev.location_text:
            continue
        geo = geocoder.geocode(ev.location_text)
        if not geo or not in_cdmx(geo.lon, geo.lat):
            continue
        out.append(Signal(
            signal_id=signal_id(source.id, e.get("id") or ev.native_id),
            source_id=source.id,
            risk_dimension=source.risk_dimension,
            event_type=source.event_type,
            event_subtype=None,
            lon=geo.lon, lat=geo.lat,
            geom_quality="geocoded",
            occurred_at=ev.occurred_at,
            geocode_confidence=geo.confidence,
            attributes={"location_text": ev.location_text, "title": e.get("title")},
            source_url=e.get("link"),
            license=source.license,
            fetched_at=now,
        ))
    return out


def extract(source: SourceConfig, ctx: ExtractContext,
            extractor: Extractor, geocoder: Geocoder) -> list[Signal]:
    entries: list[dict] = []
    for feed in source.feeds:
        # Fetch the feed through the SSRF guard rather than letting feedparser open the URL
        # itself (which would bypass the host allowlist / private-IP checks / body cap).
        try:
            resp = safe_get(feed, timeout=60)
        except OutboundFetchError:
            continue
        parsed = feedparser.parse(resp.content)
        for it in parsed.entries:
            entries.append({
                "id": getattr(it, "id", None) or it.get("guid"),
                "title": it.get("title", ""),
                "summary": it.get("summary", ""),
                "link": it.get("link"),
            })
    return entries_to_signals(entries, source, extractor, geocoder, ctx.now)
