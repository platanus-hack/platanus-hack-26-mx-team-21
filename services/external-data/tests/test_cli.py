import json
from typer.testing import CliRunner
from external_data.cli import app

runner = CliRunner()


def test_status_lists_sources():
    res = runner.invoke(app, ["status"])
    assert res.exit_code == 0
    assert "ssc_hechos_transito" in res.stdout
    assert "crash" in res.stdout


def test_help():
    assert runner.invoke(app, ["--help"]).exit_code == 0


def test_roi_compute_writes_geojson(tmp_path, monkeypatch):
    from external_data.config import get_settings, Settings
    from external_data.core.storage import make_store
    from external_data.schema import Signal

    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_ROOT", str(tmp_path))
    get_settings.cache_clear()
    store = make_store(get_settings())

    # a dense cluster (>=6 pts within 40m) so an ROI is produced
    sigs = [Signal(signal_id=f"s{i}", source_id="ssc_hechos_transito", risk_dimension="crash",
                   event_type="traffic_crash", lon=-99.1332 + i * 0.00004, lat=19.4326 + i * 0.00004,
                   geom_quality="point") for i in range(8)]
    store.write_text("staging/ssc_hechos_transito/signals.jsonl",
                     "\n".join(s.model_dump_json() for s in sigs))

    res = runner.invoke(app, ["roi-compute", "--dimension", "crash"])
    assert res.exit_code == 0, res.output
    gj = json.loads(store.read_text("staging/rois/current.geojson"))
    assert gj["type"] == "FeatureCollection" and len(gj["features"]) >= 1
    assert gj["features"][0]["properties"]["risk_dimension"] == "crash"
    get_settings.cache_clear()
