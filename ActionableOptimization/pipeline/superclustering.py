"""
Capacity-constrained supercluster builder.

Groups clusters into superclusters such that the total number of original
points within a supercluster never exceeds *max_points*.  Proximity is
measured by haversine distance to the current supercluster centroid.

Algorithm (greedy nearest-centroid):
  1. Seed a new supercluster with the first unassigned cluster.
  2. Repeatedly find the nearest unassigned cluster (to the centroid of the
     growing supercluster) that still fits within the point cap.
  3. When nothing fits, seal the supercluster and start the next one.
"""

from math import atan2, cos, radians, sin, sqrt

import numpy as np
import pandas as pd


def _haversine(lat1, lon1, lat2, lon2):
    R = 6_371_000
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlam = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlam / 2) ** 2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))


def build_superclusters(
    clusters_df: pd.DataFrame,
    max_points: int = 12,
) -> pd.DataFrame:
    """
    Add ``supercluster_id``, ``cost``, and ``total_weight`` columns to
    *clusters_df*.

    Parameters
    ----------
    clusters_df:
        Must contain ``num_points``, ``center_lat``, ``center_lon``,
        ``total_volume``, ``weight``.
    max_points:
        Hard cap on the sum of ``num_points`` within a supercluster.

    Returns
    -------
    Copy of *clusters_df* with added columns:
    ``supercluster_id``, ``cost``, ``total_weight``.
    """
    df = clusters_df.copy()
    n = len(df)

    lats = df["center_lat"].to_numpy()
    lons = df["center_lon"].to_numpy()
    pts = df["num_points"].to_numpy()

    assigned = np.zeros(n, dtype=bool)
    sc_ids = np.full(n, -1, dtype=int)
    sc_id = 0

    while True:
        unassigned = np.where(~assigned)[0]
        if len(unassigned) == 0:
            break

        seed = unassigned[0]
        assigned[seed] = True
        sc_ids[seed] = sc_id
        capacity_used = int(pts[seed])

        while capacity_used < max_points:
            members = np.where(sc_ids == sc_id)[0]
            clat = lats[members].mean()
            clon = lons[members].mean()

            remaining = np.where(~assigned)[0]
            fits = remaining[pts[remaining] <= max_points - capacity_used]
            if len(fits) == 0:
                break

            dists = np.array([_haversine(clat, clon, lats[j], lons[j]) for j in fits])
            best = fits[np.argmin(dists)]

            assigned[best] = True
            sc_ids[best] = sc_id
            capacity_used += int(pts[best])

        sc_id += 1

    df["supercluster_id"] = sc_ids

    # Cost: 2000 fixed + 8000 per unit of total volume in the supercluster
    sc_volume = df.groupby("supercluster_id")["total_volume"].sum()
    df = df.merge(
        (2000 + 8000 * sc_volume).rename("cost"),
        on="supercluster_id",
    )

    # Total weight: sum of cluster weights within each supercluster
    sc_weight = df.groupby("supercluster_id")["weight"].sum()
    df = df.merge(sc_weight.rename("total_weight"), on="supercluster_id")

    return df
