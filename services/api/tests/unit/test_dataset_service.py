"""DatasetRefreshService orchestration: stage order, source filter, summary, and terminal
failure. Extraction is replaced with a fake so no network/data files are needed; downstream
load (in-memory, no DB) and ROI recompute run for real on the fake signals."""
import pytest

from citycrawl_api.config import Settings
from citycrawl_api.modules.datasets.adapters import ckan_csv
from citycrawl_api.modules.datasets.schema import Signal
from citycrawl_api.modules.datasets.service import DatasetRefreshService

SOURCE = "ssc_hechos_transito"  # an enabled ckan_csv source in the registry


def _settings(tmp_path) -> Settings:
    return Settings(storage_backend="local", local_root=str(tmp_path), db_url=None)


def _fake_signals(n=2):
    return [
        Signal(
            signal_id=f"s{i}",
            source_id=SOURCE,
            risk_dimension="crash",
            event_type="traffic_crash",
            lon=-99.13 + i * 0.001,
            lat=19.43 + i * 0.001,
            geom_quality="point",
        )
        for i in range(n)
    ]


def test_stage_order_and_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(ckan_csv, "extract", lambda s, ctx: _fake_signals(2))
    svc = DatasetRefreshService(_settings(tmp_path))
    records = list(svc.run(source_ids=[SOURCE]))

    stages = [(r["type"], r.get("stage")) for r in records]
    assert ("progress", "extract") in stages
    assert ("progress", "load") in stages
    # extract precedes load precedes complete
    assert stages.index(("progress", "extract")) < stages.index(("progress", "load"))
    assert stages[-1][0] == "complete"
    complete = records[-1]
    assert complete["signalCount"] == 2
    assert complete["dimensions"] == ["crash"]


def test_source_filter_excludes_others(tmp_path, monkeypatch):
    calls = []

    def fake_extract(s, ctx):
        calls.append(s.id)
        return _fake_signals(1)

    monkeypatch.setattr(ckan_csv, "extract", fake_extract)
    svc = DatasetRefreshService(_settings(tmp_path))
    list(svc.run(source_ids=[SOURCE]))
    assert calls == [SOURCE]


def test_terminal_failure_on_extract(tmp_path, monkeypatch):
    def boom(s, ctx):
        raise RuntimeError("extract exploded")

    monkeypatch.setattr(ckan_csv, "extract", boom)
    svc = DatasetRefreshService(_settings(tmp_path))
    records = list(svc.run(source_ids=[SOURCE], request_id="rid-1"))
    err = records[-1]
    assert err["type"] == "error"
    assert err["stage"] == "extract"
    assert err["error"]["code"] == "dataset_extract_failed"
    assert err["error"]["requestId"] == "rid-1"


def test_error_message_does_not_leak_exception_detail(tmp_path, monkeypatch):
    # #7: the post-stream NDJSON error must NOT serialize str(exc) (could leak DSN/host/path).
    # It must be a static per-stage message; the detail goes to the server logger instead.
    secret = "postgresql://user:pw@internal-host:5432/db SECRET-DETAIL"

    def boom(s, ctx):
        raise RuntimeError(secret)

    monkeypatch.setattr(ckan_csv, "extract", boom)
    svc = DatasetRefreshService(_settings(tmp_path))
    records = list(svc.run(source_ids=[SOURCE], request_id="rid-2"))
    err = records[-1]
    assert err["error"]["message"] == "extract failed"
    assert secret not in err["error"]["message"]
    assert "SECRET-DETAIL" not in str(err)


def test_init_failure_message_is_static(tmp_path, monkeypatch):
    # The pre-stream init failure path also uses the static message (no str(exc) leak).
    import citycrawl_api.modules.datasets.service as svc_mod

    def boom_store(settings):
        raise RuntimeError("internal-dsn LEAK-XYZ")

    monkeypatch.setattr(
        "citycrawl_api.modules.datasets.core.storage.make_store", boom_store
    )
    svc = DatasetRefreshService(_settings(tmp_path))
    records = list(svc.run(source_ids=[SOURCE], request_id="rid-3"))
    err = records[-1]
    assert err["type"] == "error"
    assert err["stage"] == "init"
    assert err["error"]["message"] == "init failed"
    assert "LEAK-XYZ" not in str(err)
