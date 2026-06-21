from citycrawl_api.modules.datasets.registry.loader import load_registry, get_source
from citycrawl_api.modules.datasets.schema import DIMENSIONS


def test_registry_loads_and_validates():
    sources = load_registry()
    ids = {s.id for s in sources}
    assert {"ssc_hechos_transito", "fgj_carpetas", "infracciones_ee",
            "sacmex_encharcamientos", "news_nota_roja"} <= ids
    for s in sources:
        assert s.risk_dimension in DIMENSIONS
        assert s.kind in ("ckan_csv", "news_geocode")
        if s.kind == "ckan_csv":
            assert s.ckan_slug and s.column_map


def test_get_source():
    s = get_source("ssc_hechos_transito")
    assert s.risk_dimension == "crash"
    assert s.column_map.lat == "latitud" and s.column_map.lon == "longitud"
