from __future__ import annotations
import json
from datetime import datetime, timezone
import typer
from citycrawl_api.modules.datasets.config import get_settings
from citycrawl_api.modules.datasets.core.storage import make_store
from citycrawl_api.modules.datasets.registry.loader import load_registry, get_source
from citycrawl_api.modules.datasets.adapters.base import ExtractContext
from citycrawl_api.modules.datasets.adapters import ckan_csv
from citycrawl_api.modules.datasets.roi.runner import compute_and_store
from citycrawl_api.modules.datasets.roi.store import InMemoryRoiStore, PgRoiStore
from citycrawl_api.modules.datasets.schema import Roi, RoiParams, Signal

app = typer.Typer(help="CDMX external-signal ROI pipeline")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def rois_to_geojson(rois: list[Roi]) -> str:
    """A FeatureCollection of ROI polygons with their risk semantics — the
    consumable artifact for the map / Priority Engine when no DB is configured."""
    from shapely import wkt as _wkt
    from shapely.geometry import mapping
    feats = []
    for r in rois:
        feats.append({
            "type": "Feature",
            "geometry": mapping(_wkt.loads(r.polygon_wkt)),
            "properties": {
                "risk_dimension": r.risk_dimension, "risk_score": r.risk_score,
                "signal_count": r.signal_count, "dominant_type": r.dominant_type,
                "risk_breakdown": r.risk_breakdown, "description": r.description,
                "recency_score": r.recency_score,
                "occurred_to": r.occurred_to.isoformat() if r.occurred_to else None,
                "contributing_signal_ids": r.contributing_signal_ids,
                "source_object_refs": r.source_object_refs,
            },
        })
    return json.dumps({"type": "FeatureCollection", "features": feats})


@app.command()
def status():
    """List configured sources and their risk dimensions."""
    for s in load_registry():
        flag = "on" if s.enabled else "off"
        typer.echo(f"{s.id:28} {s.risk_dimension:13} {s.kind:12} [{flag}]")


@app.command()
def extract(source: str = typer.Option(None), all: bool = typer.Option(False, "--all")):
    """Extract a source (or --all ckan_csv sources) into staging signals.jsonl."""
    settings = get_settings()
    store = make_store(settings)
    ctx = ExtractContext(store=store, now=_now())
    targets = load_registry() if all else [get_source(source)]
    for s in targets:
        if s.kind != "ckan_csv" or not s.enabled:
            continue
        sigs = ckan_csv.extract(s, ctx)
        lines = "\n".join(sig.model_dump_json() for sig in sigs)
        store.write_text(f"staging/{s.id}/signals.jsonl", lines)
        typer.echo(f"{s.id}: {len(sigs)} signals")


@app.command(name="roi-compute")
def roi_compute(dimension: str = typer.Option(None), all: bool = typer.Option(False, "--all")):
    """Compute ROIs from staged signals and persist them with supersession."""
    settings = get_settings()
    store = make_store(settings)
    by_dim: dict[str, list[Signal]] = {}
    for s in load_registry():
        path = f"staging/{s.id}/signals.jsonl"
        if not store.exists(path):
            continue
        for line in store.read_text(path).splitlines():
            if not line.strip():
                continue
            sig = Signal(**json.loads(line))
            if dimension and sig.risk_dimension != dimension:
                continue
            by_dim.setdefault(sig.risk_dimension, []).append(sig)
    roi_store = PgRoiStore(settings.db_url) if settings.db_url else InMemoryRoiStore()
    run = compute_and_store(by_dim, roi_store, RoiParams(), _now())
    typer.echo(f"run {run.run_id}: {run.roi_count} ROIs across {run.dimensions}")
    if isinstance(roi_store, InMemoryRoiStore):
        out = store.write_text("staging/rois/current.geojson", rois_to_geojson(roi_store.current()))
        typer.echo(f"wrote ROI GeoJSON -> {out}")


@app.command(name="load-db")
def load_db():
    """Upsert staged signals into priority.external_signals (requires DB_URL)."""
    settings = get_settings()
    if not settings.db_url:
        typer.echo("DB_URL not set; cannot load to Postgres", err=True)
        raise typer.Exit(1)
    from citycrawl_api.modules.datasets.core.signal_store import PgSignalStore
    store = make_store(settings)
    sig_store = PgSignalStore(settings.db_url)
    total = 0
    for s in load_registry():
        path = f"staging/{s.id}/signals.jsonl"
        if not store.exists(path):
            continue
        sigs = [Signal(**json.loads(line)) for line in store.read_text(path).splitlines() if line.strip()]
        total += sig_store.upsert(sigs)
        typer.echo(f"{s.id}: upserted {len(sigs)}")
    typer.echo(f"total upserted into priority.external_signals: {total}")


@app.command()
def refresh(
    source: list[str] = typer.Option(None, "--source", help="Repeat to select sources; omit for all enabled."),
):
    """Run the full extract -> load -> ROI pipeline through DatasetRefreshService (the same
    callable the HTTP /v1/datasets/refresh endpoint uses), printing NDJSON progress."""
    from citycrawl_api.modules.datasets.service import DatasetRefreshService

    svc = DatasetRefreshService(get_settings())
    failed = False
    for record in svc.run(source_ids=list(source) if source else []):
        typer.echo(json.dumps(record))
        if record.get("type") == "error":
            failed = True
    if failed:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
