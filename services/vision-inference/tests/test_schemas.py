"""Smoke tests for request/response schemas and the guided-decoding JSON schemas."""
import pytest
from pydantic import ValidationError

from vision_inference.schemas import (
    FLASH_SCHEMA,
    THINKING_SCHEMA,
    Anomaly,
    AnalyzeRequest,
    AnalyzeResponse,
)


def test_request_defaults():
    req = AnalyzeRequest(image_url="s3://b/k.jpg")
    assert req.mode == "fast"          # default mode
    assert req.task == "vlm"
    assert req.id is None


def test_request_rejects_bad_mode():
    with pytest.raises(ValidationError):
        AnalyzeRequest(image_url="x", mode="turbo")


def test_anomaly_severity_validated():
    assert Anomaly(type="pothole", severity="high").severity == "high"
    with pytest.raises(ValidationError):
        Anomaly(type="pothole", severity="catastrophic")


def test_response_roundtrip():
    resp = AnalyzeResponse(
        id="row-1", model="Qwen2.5-VL-7B", mode="fast", latency_ms=1300,
        description="un bache en el carril derecho",
        anomalies=[Anomaly(type="pothole", severity="high")],
        pothole_present=True,
    )
    dumped = resp.model_dump()
    assert dumped["pothole_present"] is True
    assert dumped["anomalies"][0]["type"] == "pothole"


@pytest.mark.parametrize("schema", [FLASH_SCHEMA, THINKING_SCHEMA])
def test_guided_schemas_wellformed(schema):
    assert schema["type"] == "object"
    assert "anomalies" in schema["properties"]
    assert "description" in schema["required"]
