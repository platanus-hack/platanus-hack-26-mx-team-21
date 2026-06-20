from external_data.core.signal_store import InMemorySignalStore
from external_data.schema import Signal


def _s(i):
    return Signal(signal_id=f"x{i}", source_id="s", risk_dimension="crash",
                  event_type="t", lon=-99.1, lat=19.4, geom_quality="point")


def test_upsert_idempotent():
    st = InMemorySignalStore()
    assert st.upsert([_s(1), _s(2)]) == 2
    st.upsert([_s(1)])                # same deterministic id
    assert len(st.rows) == 2          # no duplicate row
