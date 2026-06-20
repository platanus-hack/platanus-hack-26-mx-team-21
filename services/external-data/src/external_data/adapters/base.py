from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Callable
import httpx
from external_data.core.storage import ObjectStore


@dataclass
class ExtractContext:
    store: ObjectStore
    now: datetime
    http_get: Callable[[str], httpx.Response] | None = None

    def get(self, url: str) -> httpx.Response:
        if self.http_get:
            return self.http_get(url)
        return httpx.get(url, timeout=60, follow_redirects=True)
