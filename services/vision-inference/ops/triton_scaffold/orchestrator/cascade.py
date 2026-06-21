"""Cascade policy: decide when the VLM should run.

The detector runs on every frame. The VLM is expensive, so it runs at most once per
"event" (a physical anomaly seen across consecutive frames). We dedup by spatial +
temporal proximity of the best on-floor detection.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Event:
    event_id: str
    last_seen: float
    last_frame: int
    cx: float
    cy: float
    vlm_dispatched: bool = False


@dataclass
class CascadePolicy:
    # an event is "the same" if a new best box center is within this fraction of image
    # diagonal and within cooldown_frames of the last sighting
    dist_frac: float = 0.15
    cooldown_frames: int = 30
    cooldown_secs: float = 3.0
    _events: dict = field(default_factory=dict)
    _counter: int = 0

    def _center(self, box):
        return (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0

    def assign_event(self, frame_id: int, best_box, img_w: int, img_h: int) -> tuple[str, bool]:
        """Return (event_id, should_run_vlm). should_run_vlm is True once per new event."""
        now = time.time()
        cx, cy = self._center(best_box)
        diag = (img_w ** 2 + img_h ** 2) ** 0.5
        thr = self.dist_frac * diag
        # match to an existing recent event
        for ev in list(self._events.values()):
            if frame_id - ev.last_frame > self.cooldown_frames and now - ev.last_seen > self.cooldown_secs:
                continue
            if ((cx - ev.cx) ** 2 + (cy - ev.cy) ** 2) ** 0.5 <= thr:
                ev.last_seen = now
                ev.last_frame = frame_id
                ev.cx, ev.cy = cx, cy
                run = not ev.vlm_dispatched
                ev.vlm_dispatched = True
                return ev.event_id, run
        # new event
        self._counter += 1
        eid = f"evt-{self._counter:04d}"
        self._events[eid] = Event(eid, now, frame_id, cx, cy, vlm_dispatched=True)
        return eid, True  # first sighting -> run VLM once

    def gc(self):
        """Drop stale events to bound memory."""
        now = time.time()
        for eid in [e for e, ev in self._events.items() if now - ev.last_seen > 60]:
            self._events.pop(eid, None)
