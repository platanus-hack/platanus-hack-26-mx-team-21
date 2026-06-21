"""Cost model (2000 + 8000·volume) and greedy budget selection."""
from citycrawl_api.modules.planning.optimization.cost import (
    TRIP_COST,
    VOLUME_COST,
    select_within_budget,
    supercluster_cost,
)


def test_cost_formula():
    assert supercluster_cost(0) == TRIP_COST
    assert supercluster_cost(3) == TRIP_COST + VOLUME_COST * 3
    assert (TRIP_COST, VOLUME_COST) == (2000.0, 8000.0)


def test_selection_descending_weight_within_budget():
    weights = [10.0, 50.0, 30.0]
    costs = [3000.0, 4000.0, 5000.0]
    # Budget 9000: pick 1 (w50,c4000) then 2 (w30,c5000)=9000; then 0 (c3000) busts.
    assert select_within_budget(weights, costs, 9000.0) == [1, 2]


def test_selection_skips_unaffordable_but_keeps_going():
    weights = [10.0, 50.0, 30.0]
    costs = [3000.0, 8000.0, 1000.0]
    # Budget 5000: 1 (c8000) skipped, 2 (c1000) taken, 0 (c3000) taken → [2, 0].
    assert select_within_budget(weights, costs, 5000.0) == [2, 0]


def test_zero_budget_selects_nothing():
    assert select_within_budget([1.0], [2000.0], 0.0) == []
