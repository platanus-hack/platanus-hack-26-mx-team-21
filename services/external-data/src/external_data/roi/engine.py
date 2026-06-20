from __future__ import annotations
from collections import Counter
from datetime import datetime
import numpy as np
from pyproj import Transformer
from shapely.geometry import MultiPoint
from shapely.ops import transform as shp_transform
from sklearn.cluster import DBSCAN
from external_data.core.bbox import recency_weight
from external_data.schema import Roi, RoiParams, Signal, GEOM_QUALITY_FACTOR

_TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32614", always_xy=True)
_TO_WGS = Transformer.from_crs("EPSG:32614", "EPSG:4326", always_xy=True)

_HYPOTHESES = {
    "crash": "signal timing, lane geometry, lighting, road surface",
    "violation": "signage clarity, signal timing, speed calming",
    "flooding": "drainage capacity, road grade, blocked inlets",
    "road_surface": "pavement condition, recurring potholes",
    "crime": "lighting, sightlines, activation of the space",
}


def cluster_indices(lonlats: list[tuple[float, float]], eps_m: float, min_points: int) -> list[list[int]]:
    if len(lonlats) < min_points:
        return []
    xs, ys = _TO_UTM.transform([p[0] for p in lonlats], [p[1] for p in lonlats])
    coords = np.column_stack([xs, ys])
    labels = DBSCAN(eps=eps_m, min_samples=min_points).fit_predict(coords)
    groups: dict[int, list[int]] = {}
    for idx, lab in enumerate(labels):
        if lab == -1:
            continue
        groups.setdefault(int(lab), []).append(idx)
    return list(groups.values())


def describe_roi(dimension: str, breakdown: dict, n: int, occurred_to) -> str:
    parts = ", ".join(f"{v}x {k}" for k, v in sorted(breakdown.items(), key=lambda kv: -kv[1]))
    upto = f" through {occurred_to.date()}" if occurred_to else ""
    return (f"{dimension.replace('_', ' ').title()} hotspot: {n} signals ({parts}){upto}. "
            f"Candidate root causes to inspect: {_HYPOTHESES.get(dimension, 'on-site review')}.")


def _to_wgs_polygon(geom_utm):
    return shp_transform(lambda x, y, z=None: _TO_WGS.transform(x, y), geom_utm)


def compute_rois(signals: list[Signal], params: RoiParams, now: datetime) -> list[Roi]:
    if not signals:
        return []
    lonlats = [(s.lon, s.lat) for s in signals]
    rois: list[Roi] = []
    for grp in cluster_indices(lonlats, params.eps_m, params.min_points):
        members = [signals[i] for i in grp]
        ux, uy = _TO_UTM.transform([m.lon for m in members], [m.lat for m in members])
        hull_utm = MultiPoint(list(zip(ux, uy))).convex_hull.buffer(params.buffer_m)
        poly_wgs = _to_wgs_polygon(hull_utm)
        centroid = poly_wgs.centroid
        subtypes = Counter(m.event_subtype or m.event_type for m in members)
        occ = [m.occurred_at for m in members if m.occurred_at]
        score = sum(
            m.severity_weight
            * recency_weight(m.occurred_at, params.half_life_days, now)
            * GEOM_QUALITY_FACTOR[m.geom_quality]
            for m in members
        )
        recency = (sum(recency_weight(m.occurred_at, params.half_life_days, now) for m in members)
                   / len(members))
        rois.append(Roi(
            risk_dimension=members[0].risk_dimension,
            polygon_wkt=poly_wgs.wkt,
            centroid_lon=centroid.x, centroid_lat=centroid.y,
            area_m2=float(hull_utm.area),
            risk_score=round(float(score), 4),
            signal_count=len(members),
            dominant_type=Counter(m.event_type for m in members).most_common(1)[0][0],
            risk_breakdown=dict(subtypes),
            occurred_from=min(occ) if occ else None,
            occurred_to=max(occ) if occ else None,
            recency_score=round(float(recency), 4),
            description=describe_roi(members[0].risk_dimension, dict(subtypes), len(members),
                                     max(occ) if occ else None),
            contributing_signal_ids=[m.signal_id for m in members],
            source_object_refs=sorted({m.source_object_ref for m in members if m.source_object_ref}),
        ))
    return rois
