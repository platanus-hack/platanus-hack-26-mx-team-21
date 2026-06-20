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
