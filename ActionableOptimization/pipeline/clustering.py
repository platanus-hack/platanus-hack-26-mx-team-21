"""
Point clustering along streets.

Takes a DataFrame of GPS points (each tagged with a street name) and assigns
every point a cluster_id such that:
  - Points are always on the same street within a cluster.
  - Points are sorted along the street's main axis (PCA projection).
  - From the cluster anchor (first point), any point within near_thresh metres
    joins the cluster.
  - Once a point exceeds near_thresh from the anchor, the next point must be
    within far_thresh metres of the previous point to stay in the cluster;
    otherwise a new cluster starts.
"""

from math import atan2, cos, radians, sin, sqrt

import numpy as np
import pandas as pd


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in metres between two GPS coordinates."""
    R = 6_371_000
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlam = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlam / 2) ** 2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))


def _sort_along_street(group: pd.DataFrame) -> pd.DataFrame:
    """Order points by projection onto the street's principal axis."""
    if len(group) <= 1:
        return group
    coords = group[["latitude", "longitude"]].values
    centered = coords - coords.mean(axis=0)
    _, _, Vt = np.linalg.svd(centered, full_matrices=False)
    projections = centered @ Vt[0]
    return group.iloc[np.argsort(projections)]


def _cluster_street(
    points: pd.DataFrame, near_thresh: float, far_thresh: float
) -> list[list]:
    """Return a list of clusters; each cluster is a list of DataFrame indices."""
    clusters: list[list] = []
    current: list = []
    anchor_lat = anchor_lon = prev_lat = prev_lon = None

    for _, row in points.iterrows():
        lat, lon = row["latitude"], row["longitude"]

        if anchor_lat is None:
            anchor_lat, anchor_lon = lat, lon
            prev_lat, prev_lon = lat, lon
            current = [row.name]
            continue

        dist_anchor = haversine(anchor_lat, anchor_lon, lat, lon)
        dist_prev = haversine(prev_lat, prev_lon, lat, lon)

        if dist_anchor <= near_thresh:
            current.append(row.name)
        elif dist_prev <= far_thresh:
            current.append(row.name)
        else:
            clusters.append(current)
            current = [row.name]
            anchor_lat, anchor_lon = lat, lon

        prev_lat, prev_lon = lat, lon

    if current:
        clusters.append(current)
    return clusters


def assign_clusters(
    df: pd.DataFrame,
    near_thresh: float = 100,
    far_thresh: float = 20,
) -> pd.DataFrame:
    """
    Add a ``cluster_id`` column to *df*.

    Parameters
    ----------
    df:
        Must contain columns ``latitude``, ``longitude``, ``street_name``.
        Rows with a null ``street_name`` are dropped.
    near_thresh:
        Maximum distance (m) from the cluster anchor for automatic inclusion.
    far_thresh:
        Maximum distance (m) from the previous point once the anchor threshold
        has been exceeded.

    Returns
    -------
    DataFrame with the same columns as *df* plus ``cluster_id`` (int).
    Rows without a street name are excluded.
    """
    df = df.dropna(subset=["street_name"]).copy()
    cluster_col = pd.Series(index=df.index, dtype="Int64", name="cluster_id")
    cluster_id = 0

    for _, group in df.groupby("street_name"):
        sorted_group = _sort_along_street(group)
        for indices in _cluster_street(sorted_group, near_thresh, far_thresh):
            cluster_col.loc[indices] = cluster_id
            cluster_id += 1

    df["cluster_id"] = cluster_col
    return df
