"""Pydantic models for the planning contract. Wire shapes use the frontend's camelCase
convention (via alias) while Python internals stay snake_case. These mirror the
AnalysisRequest / PlanResult / ClusteredPriority / AnalysisPoint types in lib/types.ts."""
from __future__ import annotations
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

# Mock planning constants — ported from lib/types.ts. Tuned only so the budget slider
# visibly bounds the selection; NOT a cost model (the real optimizer computes cost).
DEFAULT_SQUADS = 3
MAX_SQUADS = 8
MOCK_UNIT_COST = 150_000

SQUAD_COLORS = [
    "#2f64e6",
    "#e5484d",
    "#0f9b8e",
    "#f5a623",
    "#7c3aed",
    "#d6409f",
    "#1d7a4d",
    "#c2410c",
]


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class LatLngModel(_Camel):
    lat: float
    lng: float


class AnalysisPoint(_Camel):
    id: str
    lat: float
    lng: float
    slug: str
    volume: float
    zone: str | None = None
    district_cve: str | None = None


class AnalysisRequest(_Camel):
    issue_type: str
    budget: float
    region_filter: list[str] = []
    squad_count: int | None = None
    costs: dict[str, float] = {}
    points: list[AnalysisPoint] = []


class ClusterPrioritiesRequest(_Camel):
    """priorities:cluster depends only on the visible points (and optional k)."""
    points: list[AnalysisPoint] = []
    squad_count: int | None = None


class TopCritical(_Camel):
    id: str
    slug: str
    lat: float
    lng: float
    volume: float
    cost: float
    zone: str | None = None
    rank: int


class Squad(_Camel):
    idx: int
    color: str
    weight: float
    members: list[str]
    polygon: list[list[float]]
    centroid: LatLngModel
    cost: float
    count: int


class PlanStats(_Camel):
    spent: float
    count: int
    squads: int
    regions: int
    volume: float
    budget_pct: int


class PlanResult(_Camel):
    issue_type: str
    budget: float
    region_filter: list[str]
    squad_count_used: int
    top_critical: list[TopCritical]
    squads: list[Squad]
    stats: PlanStats


class ClusteredPriority(_Camel):
    id: str
    weight: float
    polygon: list[list[float]]
    centroid: LatLngModel
    count: int
