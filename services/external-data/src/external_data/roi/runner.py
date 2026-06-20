from __future__ import annotations
from datetime import datetime
from external_data.roi.engine import compute_rois
from external_data.roi.store import RoiStore
from external_data.schema import RoiParams, RoiRun, Signal


def compute_and_store(signals_by_dim: dict[str, list[Signal]], store: RoiStore,
                      params: RoiParams, now: datetime) -> RoiRun:
    dimensions = sorted(signals_by_dim)
    run_id = store.start_run(dimensions, params.model_dump())
    total = 0
    for dim in dimensions:
        rois = compute_rois(signals_by_dim[dim], params.for_dimension(dim), now)
        store.write_rois(run_id, rois)
        total += len(rois)
    store.supersede(run_id, dimensions)
    store.complete_run(run_id, total)
    return RoiRun(run_id=run_id, dimensions=dimensions, params=params.model_dump(), roi_count=total)
