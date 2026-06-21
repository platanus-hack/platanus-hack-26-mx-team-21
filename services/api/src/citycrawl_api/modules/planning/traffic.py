"""Cached traffic layer for the optimization engine.

`lookup` is read-only and never touches the network — `/optimize` runs on every debounced
budget-slider tick, so TomTom (rate-limited) is called only from the offline `warm` path.
On a cache miss `lookup` returns a neutral fallback so the criticality weight stays
well-defined. The TomTom math (FRC→lanes, current/free-flow speed → hourly → weekly volume)
is ported from ActionableOptimization/pipeline/traffic.py."""
from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import httpx

TrafficFetch = Callable[[float, float], "TrafficSample"]


@dataclass(frozen=True)
class TrafficSample:
    vehicles_week: float
    free_flow_speed: float


# Neutral citywide stand-in: ~3 lanes at 60% of free flow → ~272k veh/week, 50 km/h.
DEFAULT_TRAFFIC = TrafficSample(vehicles_week=250_000.0, free_flow_speed=50.0)

_FRC_LANE_MAP = {"FRC0": 6.0, "FRC1": 6.0, "FRC2": 4.0, "FRC3": 3.0, "FRC4": 2.0, "FRC5": 1.5, "FRC6": 1.0}
_CAPACITY_PER_LANE = 1800
_DAILY_HOURS = 12
_DAYS_PER_WEEK = 7


class TrafficProvider:
    def __init__(
        self,
        cache_path: str,
        grid_decimals: int = 3,
        fallback: TrafficSample = DEFAULT_TRAFFIC,
    ) -> None:
        self._path = Path(cache_path)
        self._decimals = grid_decimals
        self._fallback = fallback
        self._cache: dict[str, TrafficSample] = self._load()

    def _key(self, lat: float, lng: float) -> str:
        return f"{round(lat, self._decimals)},{round(lng, self._decimals)}"

    def _load(self) -> dict[str, TrafficSample]:
        if not self._path.exists():
            return {}
        raw = json.loads(self._path.read_text())
        return {k: TrafficSample(**v) for k, v in raw.items()}

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        serializable = {k: {"vehicles_week": s.vehicles_week, "free_flow_speed": s.free_flow_speed}
                        for k, s in self._cache.items()}
        self._path.write_text(json.dumps(serializable))

    def lookup(self, lat: float, lng: float) -> TrafficSample:
        return self._cache.get(self._key(lat, lng), self._fallback)

    def warm(
        self, locations: Iterable[tuple[float, float]], fetch: TrafficFetch, delay_s: float = 0.0
    ) -> int:
        written = 0
        seen: set[str] = set()
        for lat, lng in locations:
            key = self._key(lat, lng)
            if key in seen:
                continue
            seen.add(key)
            self._cache[key] = fetch(lat, lng)
            written += 1
            if delay_s:
                time.sleep(delay_s)
        self._persist()
        return written


def tomtom_fetch(api_key: str, *, client: httpx.Client | None = None) -> TrafficFetch:
    url = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"

    def fetch(lat: float, lng: float) -> TrafficSample:
        owns = client is None
        c = client or httpx.Client(timeout=10.0)
        try:
            resp = c.get(url, params={"point": f"{lat},{lng}", "key": api_key})
            resp.raise_for_status()
            seg = resp.json()["flowSegmentData"]
            lanes = _FRC_LANE_MAP.get(seg.get("frc", "FRC3"), 3.0)
            hourly = round(lanes * _CAPACITY_PER_LANE * (seg["currentSpeed"] / seg["freeFlowSpeed"]))
            weekly = round(hourly * _DAILY_HOURS * _DAYS_PER_WEEK)
            return TrafficSample(vehicles_week=float(weekly), free_flow_speed=float(seg["freeFlowSpeed"]))
        finally:
            if owns:
                c.close()

    return fetch
