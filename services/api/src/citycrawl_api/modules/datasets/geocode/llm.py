from __future__ import annotations
import json
import anthropic
from citycrawl_api.modules.datasets.geocode.base import ExtractedEvent

_PROMPT = (
    "You extract road-incident facts from a Spanish news headline+summary about "
    "Mexico City. Return JSON only: {\"is_incident\": bool, \"location_text\": str, "
    "\"occurred_hint\": str}. is_incident=true only for crashes/collisions/road "
    "hazards. location_text = the most specific street/intersection/colonia named, "
    "or \"\" if none."
)


class ClaudeExtractor:
    def __init__(self, api_key: str, model: str = "claude-opus-4-8"):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def extract(self, title: str, summary: str) -> ExtractedEvent | None:
        msg = self.client.messages.create(
            model=self.model, max_tokens=300,
            system=_PROMPT,
            messages=[{"role": "user", "content": f"TITLE: {title}\nSUMMARY: {summary}"}],
        )
        try:
            data = json.loads(msg.content[0].text)
        except (json.JSONDecodeError, IndexError, AttributeError):
            return None
        return ExtractedEvent(
            native_id=title,
            location_text=data.get("location_text", ""),
            occurred_at=None,
            is_incident=bool(data.get("is_incident")),
        )
