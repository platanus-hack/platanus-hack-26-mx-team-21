from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Callable
import httpx
from citycrawl_api.modules.datasets.core.storage import ObjectStore
from citycrawl_api.modules.datasets.net import safe_get


@dataclass
class ExtractContext:
    store: ObjectStore
    now: datetime
    http_get: Callable[[str], httpx.Response] | None = None

    def get(self, url: str) -> httpx.Response:
        # Tests/callers may inject http_get; the default goes through the SSRF guard
        # (https + host allowlist + private-IP + no-redirects + body cap).
        if self.http_get:
            return self.http_get(url)
        return safe_get(url, timeout=60)
