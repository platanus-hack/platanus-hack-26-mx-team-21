from __future__ import annotations
import csv
import hashlib
import io
import json
import re
from datetime import datetime
from dateutil import parser as dtparse
from external_data.adapters.base import ExtractContext
from external_data.core.bbox import in_cdmx
from external_data.core.ids import signal_id
from external_data.core.manifest import Manifest
from external_data.registry.models import SourceConfig
from external_data.schema import Signal


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return dtparse.parse(value)
    except (ValueError, OverflowError, TypeError):
        return None


def _passes_subset(row: dict, subset: dict | None) -> bool:
    if not subset:
        return True
    for col, allowed in subset.items():
        val = (row.get(col) or "").strip().upper()
        if val not in {a.upper() for a in allowed}:
            return False
    return True


def _native_id(row: dict, source: SourceConfig) -> str:
    cm = source.column_map
    if cm and cm.native_id and row.get(cm.native_id):
        return str(row[cm.native_id])
    return hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()[:16]


def rows_to_signals(rows: list[dict], source: SourceConfig, now: datetime) -> list[Signal]:
    cm = source.column_map
    out: list[Signal] = []
    for row in rows:
        if not _passes_subset(row, source.subset):
            continue
        try:
            lon = float(row[cm.lon])
            lat = float(row[cm.lat])
        except (KeyError, TypeError, ValueError):
            continue
        if not in_cdmx(lon, lat):
            continue
        subtype = row.get(cm.event_subtype) if cm.event_subtype else None
        weight = source.severity.get((subtype or "").upper(), source.default_severity)
        out.append(Signal(
            signal_id=signal_id(source.id, _native_id(row, source)),
            source_id=source.id,
            risk_dimension=source.risk_dimension,
            event_type=source.event_type,
            event_subtype=subtype,
            lon=lon, lat=lat,
            geom_quality=source.geom_quality,
            occurred_at=_parse_dt(row.get(cm.occurred_at)) if cm.occurred_at else None,
            reported_at=_parse_dt(row.get(cm.reported_at)) if cm.reported_at else None,
            severity_weight=weight,
            attributes={k: row.get(k) for k in (cm.attributes or [])},
            license=source.license,
            fetched_at=now,
        ))
    return out


def resolve_resource_url(slug: str, resource_match: str | None, ctx: ExtractContext) -> tuple[str, str]:
    api = f"https://datos.cdmx.gob.mx/api/3/action/package_show?id={slug}"
    resources = ctx.get(api).json()["result"]["resources"]
    csvs = [r for r in resources if (r.get("format") or "").upper() == "CSV"]
    if resource_match:
        rx = re.compile(resource_match)
        matched = [r for r in csvs if rx.search(r.get("name") or "")]
        csvs = matched or csvs
    csvs.sort(key=lambda r: r.get("created") or "", reverse=True)
    if not csvs:
        raise RuntimeError(f"no CSV resource for {slug}")
    return csvs[0]["id"], csvs[0]["url"]


def extract(source: SourceConfig, ctx: ExtractContext) -> list[Signal]:
    _, url = resolve_resource_url(source.ckan_slug, source.resource_match, ctx)
    body = ctx.get(url).content
    sha = hashlib.sha256(body).hexdigest()
    stamp = ctx.now.strftime("%Y%m%dT%H%M%SZ")
    raw_path = f"raw/{source.id}/{stamp}/{url.rsplit('/', 1)[-1]}"
    ctx.store.write_bytes(raw_path, body)
    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8-sig", errors="replace"))))
    ctx.store.write_text(
        f"raw/{source.id}/{stamp}/manifest.json",
        Manifest(
            source_id=source.id, source_url=url, sha256=sha, byte_size=len(body),
            row_count=len(rows), license=source.license, fetched_at=ctx.now, adapter="ckan_csv",
        ).model_dump_json(),
    )
    signals = rows_to_signals(rows, source, ctx.now)
    for s in signals:
        s.source_object_ref = raw_path
    return signals
