from datetime import datetime, timezone, timedelta
from external_data.core.ids import signal_id
from external_data.core.bbox import in_cdmx, recency_weight


def test_signal_id_deterministic():
    a = signal_id("ssc", "row-1")
    assert a == signal_id("ssc", "row-1")
    assert a != signal_id("ssc", "row-2")
    assert len(a) == 32


def test_in_cdmx():
    assert in_cdmx(-99.13, 19.43)         # Zocalo
    assert not in_cdmx(-100.31, 25.67)    # Monterrey
    assert not in_cdmx(0.0, 0.0)


def test_recency_weight_halves_at_half_life():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    old = now - timedelta(days=365)
    assert recency_weight(now, 365, now) == 1.0
    assert abs(recency_weight(old, 365, now) - 0.5) < 1e-6
    assert recency_weight(None, 365, now) == 0.5
