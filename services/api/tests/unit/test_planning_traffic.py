"""TrafficProvider: read-only cache with fallback; warm populates from a fetch callable."""
from citycrawl_api.modules.planning.traffic import (
    DEFAULT_TRAFFIC,
    TrafficProvider,
    TrafficSample,
)


def test_lookup_miss_returns_fallback(tmp_path):
    prov = TrafficProvider(cache_path=str(tmp_path / "c.json"))
    assert prov.lookup(19.4, -99.1) == DEFAULT_TRAFFIC


def test_warm_then_lookup_hits_cache(tmp_path):
    prov = TrafficProvider(cache_path=str(tmp_path / "c.json"), grid_decimals=3)
    sample = TrafficSample(vehicles_week=999.0, free_flow_speed=42.0)
    calls: list[tuple[float, float]] = []

    def fake_fetch(lat: float, lng: float) -> TrafficSample:
        calls.append((lat, lng))
        return sample

    written = prov.warm([(19.4001, -99.1002), (19.4002, -99.1001)], fake_fetch)
    # Both round to (19.4, -99.1) at 3 decimals → one grid cell, one fetch.
    assert written == 1
    assert len(calls) == 1
    assert prov.lookup(19.4, -99.1) == sample


def test_warm_persists_across_instances(tmp_path):
    path = str(tmp_path / "c.json")
    TrafficProvider(cache_path=path).warm(
        [(19.42, -99.13)], lambda la, lo: TrafficSample(7.0, 8.0)
    )
    # A fresh instance reads the same file.
    assert TrafficProvider(cache_path=path).lookup(19.42, -99.13) == TrafficSample(7.0, 8.0)


def test_lookup_makes_no_network_call(tmp_path, monkeypatch):
    import httpx

    def boom(*a, **k):
        raise AssertionError("lookup must not hit the network")

    monkeypatch.setattr(httpx, "get", boom)
    prov = TrafficProvider(cache_path=str(tmp_path / "c.json"))
    assert prov.lookup(1.0, 2.0) == DEFAULT_TRAFFIC
