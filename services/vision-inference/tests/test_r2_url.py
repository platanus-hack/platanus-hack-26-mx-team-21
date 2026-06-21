"""Smoke tests for r2 URL parsing — no network, no boto credentials."""
import pytest

from vision_inference.r2 import parse_s3_url


def test_parse_observation_url():
    url = "s3://observation-thumbnails/observations/0b711262-abcd/report.jpg"
    bucket, key = parse_s3_url(url)
    assert bucket == "observation-thumbnails"
    assert key == "observations/0b711262-abcd/report.jpg"


def test_parse_simple():
    assert parse_s3_url("s3://bucket/key") == ("bucket", "key")


@pytest.mark.parametrize("bad", [
    "https://example.com/x.jpg",   # not s3://
    "s3://bucket-only",            # no key
    "s3:///key",                   # empty bucket
    "s3://bucket/",                # empty key
])
def test_rejects_bad_urls(bad):
    with pytest.raises(ValueError):
        parse_s3_url(bad)
