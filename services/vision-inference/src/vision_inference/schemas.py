"""Request/response + the JSON schema used for guided decoding (structured output)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    image_url: str
    task: Literal["vlm", "potholes", "potholes_verified"] = "vlm"
    mode: Literal["fast", "thinking", "reason"] = "fast"   # reason = pendiente
    id: Optional[str] = None            # row id (Stage 2: which Supabase row to update)


class Anomaly(BaseModel):
    type: str
    severity: Literal["low", "medium", "high"] = "low"
    where: Optional[str] = None
    evidence: Optional[str] = None
    confidence: float = 0.0


class AnalyzeResponse(BaseModel):
    id: Optional[str]
    model: str
    mode: str
    latency_ms: int
    description: str                     # natural-language output (-> Supabase 'description')
    anomalies: list[Anomaly] = []
    road_condition: Optional[str] = None
    tags: list[str] = []
    pothole_present: bool = False


# JSON schema handed to vLLM `guided_json` so the model returns valid, parseable output.
FLASH_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "pothole_present": {"type": "boolean"},
        "anomalies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "severity": {"enum": ["low", "medium", "high"]},
                    "confidence": {"type": "number"},
                },
                "required": ["type", "severity"],
            },
        },
    },
    "required": ["description", "pothole_present", "anomalies"],
}

THINKING_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "pothole_present": {"type": "boolean"},
        "road_condition": {"enum": ["good", "fair", "poor", "very_poor"]},
        "tags": {"type": "array", "items": {"type": "string"}},
        "anomalies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "severity": {"enum": ["low", "medium", "high"]},
                    "where": {"type": "string"},
                    "evidence": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["type", "severity", "where"],
            },
        },
    },
    "required": ["description", "pothole_present", "road_condition", "anomalies"],
}
