import csv
import io
import os
from datetime import datetime, timezone
from external_data.adapters.ckan_csv import rows_to_signals
from external_data.registry.loader import get_source

NOW = datetime(2026, 6, 20, tzinfo=timezone.utc)
FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "ssc_sample.csv")


def _rows():
    with open(FIXTURE, encoding="utf-8") as fh:
        return list(csv.DictReader(io.StringIO(fh.read())))


def test_rows_to_signals_maps_and_filters():
    src = get_source("ssc_hechos_transito")
    sigs = rows_to_signals(_rows(), src, NOW)
    # 3 rows; the Monterrey row is dropped by the CDMX bbox
    assert len(sigs) == 2
    s = sigs[0]
    assert s.risk_dimension == "crash" and s.event_type == "traffic_crash"
    assert s.geom_quality == "point"
    assert -99.36 <= s.lon <= -98.94 and 19.04 <= s.lat <= 19.59
    # column mapping verified against the real SSC schema
    assert s.event_subtype == "COLISION"            # tipo_evento -> subtype
    assert s.occurred_at is not None and s.occurred_at.year == 2024  # fecha_evento parsed
    assert "alcaldia" in s.attributes


def test_severity_weights_vulnerable_users():
    src = get_source("ssc_hechos_transito")
    sigs = {s.event_subtype: s for s in rows_to_signals(_rows(), src, NOW)}
    assert sigs["ATROPELLADO"].severity_weight == 2.0   # from registry severity table
    assert sigs["COLISION"].severity_weight == 1.0      # default


def test_rows_to_signals_dedup_ids_stable():
    src = get_source("ssc_hechos_transito")
    a = {x.signal_id for x in rows_to_signals(_rows(), src, NOW)}
    b = {x.signal_id for x in rows_to_signals(_rows(), src, NOW)}
    assert a == b and len(a) == 2
