"""Video service — capabilities only. No processing, storage writes, or observation
creation happen here; that is explicitly out of scope until a processor design exists."""
from __future__ import annotations

from citycrawl_api.modules.video.models import VideoCapabilities


def capabilities() -> VideoCapabilities:
    return VideoCapabilities(implemented=False, operations=[])
