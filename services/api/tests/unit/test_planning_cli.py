"""warm-traffic CLI: reads lat,lng pairs and warms the provider without live TomTom."""
from typer.testing import CliRunner

from citycrawl_api.modules.planning import cli
from citycrawl_api.modules.planning.traffic import TrafficProvider, TrafficSample

runner = CliRunner()


def test_read_locations(tmp_path):
    f = tmp_path / "loc.csv"
    f.write_text("19.40,-99.10\n19.41,-99.11\n\n")  # blank line ignored
    assert cli._read_locations(str(f)) == [(19.40, -99.10), (19.41, -99.11)]


def test_warm_traffic_command(tmp_path, monkeypatch):
    loc = tmp_path / "loc.csv"
    loc.write_text("19.40,-99.10\n")
    cache = tmp_path / "cache.json"

    # Avoid real settings/network: stub the fetch factory and force the cache path.
    monkeypatch.setattr(cli, "_provider", lambda: TrafficProvider(cache_path=str(cache)))
    monkeypatch.setattr(cli, "_fetch", lambda: (lambda la, lo: TrafficSample(123.0, 45.0)))

    result = runner.invoke(cli.app, ["--from-file", str(loc)])
    assert result.exit_code == 0, result.output
    assert "1" in result.output  # reports cells written
    assert TrafficProvider(cache_path=str(cache)).lookup(19.40, -99.10) == TrafficSample(123.0, 45.0)
