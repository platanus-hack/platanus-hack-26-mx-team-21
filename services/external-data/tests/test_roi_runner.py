from datetime import datetime, timezone
from external_data.schema import Signal, RoiParams
from external_data.roi.store import InMemoryRoiStore
from external_data.roi.runner import compute_and_store

NOW = datetime(2026, 6, 20, tzinfo=timezone.utc)


def _cluster(dim, n=6, base=(-99.1332, 19.4326)):
    return [Signal(signal_id=f"{dim}-{i}", source_id="x", risk_dimension=dim,
                   event_type=f"{dim}_evt", lon=base[0] + i * 0.0001, lat=base[1] + i * 0.0001,
                   geom_quality="point", occurred_at=NOW, severity_weight=1.0) for i in range(n)]


def test_first_run_creates_current_rois():
    store = InMemoryRoiStore()
    run = compute_and_store({"crash": _cluster("crash")}, store, RoiParams(eps_m=150, min_points=4), NOW)
    assert run.roi_count == 1
    assert len(store.current()) == 1
    assert len(store.current("crash")) == 1


def test_recompute_supersedes_only_that_dimension():
    store = InMemoryRoiStore()
    compute_and_store({"crash": _cluster("crash"), "crime": _cluster("crime")},
                      store, RoiParams(eps_m=150, min_points=4), NOW)
    assert len(store.current()) == 2
    compute_and_store({"crash": _cluster("crash")}, store,
                      RoiParams(eps_m=150, min_points=4), NOW)
    cur = store.current()
    assert len(cur) == 2                       # 1 fresh crash + 1 untouched crime
    assert len(store.current("crash")) == 1
    assert len(store.current("crime")) == 1
    assert len(store.all_rois()) == 3          # history retained
