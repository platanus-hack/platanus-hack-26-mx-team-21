"""Qwen2.5-VL client via an OpenAI-compatible endpoint (vLLM by default).

Swap base_url to a TensorRT-LLM/Triton OpenAI endpoint with no code change.
"""
from __future__ import annotations

import base64
import json
import re

import httpx

PROMPT = (
    "An automatic detector flagged a possible POTHOLE in this street photo; verify it. "
    "Reply STRICT JSON only: "
    '{"pothole_present": true/false (real pavement cavity, NOT manhole cover/drain grate/'
    'speed bump/shadow/marking), "what_it_is": short phrase, '
    '"road_condition": "good"|"fair"|"poor"|"very_poor", "scene": one short sentence}.'
)


def _parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        return json.loads(m.group(0)) if m else {"_raw": text[:300]}
    except json.JSONDecodeError:
        return {"_raw": text[:300]}


class VLMClient:
    def __init__(self, base_url: str = "http://localhost:8000/v1",
                 model: str = "Qwen/Qwen2.5-VL-7B-Instruct", max_tokens: int = 160):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.max_tokens = max_tokens
        self.http = httpx.Client(timeout=120)

    def verify(self, jpeg_bytes: bytes) -> dict:
        b64 = base64.b64encode(jpeg_bytes).decode()
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": 0.0,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": PROMPT},
            ]}],
        }
        r = self.http.post(self.url, json=payload)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
        v = _parse(text)
        v["final_label"] = "POTHOLE" if v.get("pothole_present") is True else "ANOMALY"
        return v
