import pytest

from citycrawl_api.modules.datasets.config import Settings
from citycrawl_api.modules.datasets.core.storage import make_store


def test_local_store_roundtrip(tmp_path):
    s = make_store(Settings(storage_backend="local", local_root=str(tmp_path)))
    ref = s.write_text("raw/ssc/2026/f.csv", "a,b\n1,2\n")
    assert s.exists("raw/ssc/2026/f.csv")
    assert s.read_text("raw/ssc/2026/f.csv") == "a,b\n1,2\n"
    assert ref.endswith("raw/ssc/2026/f.csv")
    assert not s.exists("raw/ssc/2026/missing.csv")


def test_r2_store_is_s3_rooted_at_bucket():
    s = make_store(Settings(
        storage_backend="r2",
        r2_s3_endpoint="https://acct.r2.cloudflarestorage.com",
        r2_access_key="k", r2_secret="x",
        external_data_bucket="external-data",
    ))
    assert s.root == "external-data"
    assert "s3" in s.fs.protocol  # s3fs filesystem, no network on construction


def test_r2_store_requires_endpoint():
    # A missing R2 endpoint would silently target AWS S3 — fail loud instead.
    with pytest.raises(ValueError, match="r2_s3_endpoint"):
        make_store(Settings(storage_backend="r2", r2_access_key="k", r2_secret="x"))
