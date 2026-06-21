import pytest
from citycrawl_api.modules.datasets.schema import Signal, Roi, RoiParams, DIMENSIONS, GEOM_QUALITY_FACTOR


def test_dimensions_set():
    assert DIMENSIONS == {"crash", "violation", "flooding", "road_surface", "crime"}
    assert GEOM_QUALITY_FACTOR["block_centroid"] == 0.5


def test_signal_rejects_bad_dimension():
    with pytest.raises(ValueError):
        Signal(signal_id="a", source_id="s", risk_dimension="nope",
               event_type="x", lon=-99.1, lat=19.4, geom_quality="point")


def test_signal_rejects_out_of_range_lat():
    with pytest.raises(ValueError):
        Signal(signal_id="a", source_id="s", risk_dimension="crash",
               event_type="x", lon=-99.1, lat=200.0, geom_quality="point")


def test_roiparams_for_dimension_override():
    p = RoiParams(eps_m=100, per_dimension={"crash": {"eps_m": 60, "min_points": 8}})
    c = p.for_dimension("crash")
    assert c.eps_m == 60 and c.min_points == 8
    assert p.for_dimension("crime").eps_m == 100
