from external_data.config import Settings
from external_data.core.storage import make_store


def test_local_store_roundtrip(tmp_path):
    s = make_store(Settings(storage_backend="local", local_root=str(tmp_path)))
    ref = s.write_text("raw/ssc/2026/f.csv", "a,b\n1,2\n")
    assert s.exists("raw/ssc/2026/f.csv")
    assert s.read_text("raw/ssc/2026/f.csv") == "a,b\n1,2\n"
    assert ref.endswith("raw/ssc/2026/f.csv")
    assert not s.exists("raw/ssc/2026/missing.csv")
