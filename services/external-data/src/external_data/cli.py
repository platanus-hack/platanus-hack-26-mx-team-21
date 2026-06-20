from __future__ import annotations
import json
from datetime import datetime, timezone
import typer
from external_data.config import get_settings
from external_data.core.storage import make_store
from external_data.registry.loader import load_registry, get_source
from external_data.adapters.base import ExtractContext
from external_data.adapters import ckan_csv
from external_data.roi.runner import compute_and_store
from external_data.roi.store import InMemoryRoiStore, PgRoiStore
from external_data.schema import RoiParams, Signal

app = typer.Typer(help="CDMX external-signal ROI pipeline")


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


if __name__ == "__main__":
    app()
