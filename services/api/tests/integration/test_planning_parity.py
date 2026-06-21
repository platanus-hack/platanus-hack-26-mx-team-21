"""Parity: MockPlanningEngine must reproduce the captured TypeScript outputs byte-for-byte.

The fixture planning_parity.json is generated from the live frontend functions via
capture_ts_planning.mts. Regenerate it (and review the diff) if the frontend mock ever
changes before it is deleted:

    node ... or: npx -y tsx tests/integration/capture_ts_planning.mts
"""
import json
from pathlib import Path

import pytest

from citycrawl_api.modules.planning.mock import MockPlanningEngine
from citycrawl_api.modules.planning.models import AnalysisPoint, AnalysisRequest

FIXTURE = Path(__file__).parent / "fixtures" / "planning_parity.json"
DATA = json.loads(FIXTURE.read_text())
ENGINE = MockPlanningEngine()


def _dump(model) -> dict:
    return model.model_dump(by_alias=True)


@pytest.mark.parametrize("case", DATA["requests"], ids=[c["name"] for c in DATA["requests"]])
def test_optimize_parity(case):
    req = AnalysisRequest.model_validate(case["input"])
    got = _dump(ENGINE.optimize(req))
    assert got == case["plan"]


@pytest.mark.parametrize("case", DATA["clusters"], ids=[c["name"] for c in DATA["clusters"]])
def test_cluster_priorities_parity(case):
    points = [AnalysisPoint.model_validate(p) for p in case["points"]]
    k = case["k"]
    got = [_dump(c) for c in ENGINE.cluster_priorities(points, k)]
    assert got == case["result"]
