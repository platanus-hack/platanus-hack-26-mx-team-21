from datetime import datetime, timezone
from citycrawl_api.modules.datasets.schema import Signal, RoiParams
from citycrawl_api.modules.datasets.roi.engine import cluster_indices, compute_rois

NOW = datetime(2026, 6, 20, tzinfo=timezone.utc)


def _sig(i, lon, lat, dim="crash", w=1.0, sub="colision"):
    return Signal(signal_id=f"s{i}", source_id="ssc", risk_dimension=dim,
                  event_type="traffic_crash", event_subtype=sub, lon=lon, lat=lat,
                  geom_quality="point", occurred_at=NOW, severity_weight=w)


def test_cluster_indices_groups_dense_separates_far():
    pts = [(-99.1332, 19.4326), (-99.1334, 19.4327), (-99.1331, 19.4325),
           (-99.1333, 19.4328), (-99.1335, 19.4326), (-99.16, 19.35)]
    groups = cluster_indices(pts, eps_m=100, min_points=4)
    assert len(groups) == 1
    assert set(groups[0]) == {0, 1, 2, 3, 4}      # far point is noise


def test_compute_rois_builds_polygon_and_semantics():
    sigs = [_sig(i, -99.1332 + i * 0.0001, 19.4326 + i * 0.0001) for i in range(6)]
    rois = compute_rois(sigs, RoiParams(eps_m=150, min_points=4), NOW)
    assert len(rois) == 1
    r = rois[0]
    assert r.risk_dimension == "crash"
    assert r.signal_count == 6 and r.risk_score > 0
    assert r.dominant_type == "traffic_crash"
    assert r.area_m2 > 0
    assert r.polygon_wkt.startswith("POLYGON")
    assert len(r.contributing_signal_ids) == 6
    assert "crash" in r.description.lower()


def test_compute_rois_excludes_sparse():
    sigs = [_sig(0, -99.1, 19.4), _sig(1, -99.2, 19.5)]
    assert compute_rois(sigs, RoiParams(min_points=4), NOW) == []
