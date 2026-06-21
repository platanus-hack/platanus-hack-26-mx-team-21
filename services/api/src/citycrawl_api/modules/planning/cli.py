"""Local Typer adapter that warms the traffic cache from TomTom. Run before deploy (or on a
schedule) so /optimize has real traffic weights; /optimize itself never calls TomTom.

Usage:
    citycrawl-planning warm-traffic --from-file locations.csv
where locations.csv has one `lat,lng` per line. `_provider`/`_fetch` are split out so tests
can stub them without real settings or network."""
from __future__ import annotations

import typer

from citycrawl_api.config import get_settings
from citycrawl_api.modules.planning.traffic import TrafficFetch, TrafficProvider, tomtom_fetch

app = typer.Typer(help="Planning maintenance commands.")


def _read_locations(path: str) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            lat, lng = line.split(",")
            out.append((float(lat), float(lng)))
    return out


def _provider() -> TrafficProvider:
    s = get_settings()
    return TrafficProvider(cache_path=s.traffic_cache_path, grid_decimals=s.traffic_grid_decimals)


def _fetch() -> TrafficFetch:
    s = get_settings()
    if not s.tomtom_api_key:
        raise typer.BadParameter("TOMTOM_API_KEY is not set.")
    return tomtom_fetch(s.tomtom_api_key)


@app.command("warm-traffic")
def warm_traffic(
    from_file: str = typer.Option(..., "--from-file", help="CSV of `lat,lng` per line."),
    delay: float = typer.Option(0.25, "--delay", help="Seconds between TomTom calls."),
) -> None:
    locations = _read_locations(from_file)
    written = _provider().warm(locations, _fetch(), delay_s=delay)
    typer.echo(f"Warmed {written} traffic grid cells from {len(locations)} locations.")
