"""
Main pipeline orchestrator.

Usage
-----
    from pipeline import run_pipeline

    result = run_pipeline(points_df, api_key="YOUR_KEY", budget=500_000)

Input
-----
A DataFrame with at least these columns:
    latitude    float
    longitude   float
    street_name str
    volume      float

Output
------
A DataFrame with one row per original point, sorted by supercluster
total_weight descending, containing:

    latitude, longitude, street_name, volume
    cluster_id
    supercluster_id
    total_weight    – sum of cluster weights in the supercluster
    cost            – 2000 + 8000 × total volume of the supercluster
    within_budget   – True if the point's supercluster fits within the budget
                      (always True when budget=None)
"""

import pandas as pd

from .clustering import assign_clusters
from .traffic import fetch_traffic_for_clusters
from .superclustering import build_superclusters


def _mark_within_budget(result: pd.DataFrame, budget: float) -> pd.DataFrame:
    """
    Add a ``within_budget`` boolean column.

    Superclusters are selected greedily in descending ``total_weight`` order
    until adding the next one would exceed *budget*.  All points belonging to
    selected superclusters are marked True.
    """
    # One row per supercluster, preserving weight order (already sorted).
    sc_costs = (
        result[["supercluster_id", "total_weight", "cost"]]
        .drop_duplicates("supercluster_id")
        .sort_values("total_weight", ascending=False)
    )

    spent = 0.0
    selected = set()
    for _, row in sc_costs.iterrows():
        if spent + row["cost"] <= budget:
            spent += row["cost"]
            selected.add(row["supercluster_id"])

    result = result.copy()
    result["within_budget"] = result["supercluster_id"].isin(selected)
    return result


def run_pipeline(
    points_df: pd.DataFrame,
    api_key: str,
    budget: float = None,
    near_thresh: float = 100,
    far_thresh: float = 20,
    max_points_per_supercluster: int = 12,
    request_delay: float = 0.25,
) -> pd.DataFrame:
    """
    Run the full clustering pipeline.

    Parameters
    ----------
    points_df:
        Input points. Required columns: ``latitude``, ``longitude``,
        ``street_name``, ``volume``.
    api_key:
        TomTom Traffic Flow API key.
    budget:
        Total repair budget in dollars.  Superclusters are selected greedily
        in descending weight order until the budget is exhausted.  Each point
        gets a ``within_budget`` boolean column.  Pass ``None`` to skip
        budget filtering (all points marked ``within_budget=True``).
    near_thresh:
        Distance (m) from cluster anchor for automatic cluster inclusion.
    far_thresh:
        Distance (m) from previous point once anchor threshold is exceeded.
    max_points_per_supercluster:
        Hard cap on original points per supercluster.
    request_delay:
        Seconds between TomTom API calls.

    Returns
    -------
    DataFrame with all original points enriched with cluster and supercluster
    information, sorted by ``total_weight`` descending.
    """
    # ── 1. Normalise column names ────────────────────────────────────────────
    df = points_df.copy()
    df.columns = [c.lower() for c in df.columns]
    if "volume" not in df.columns:
        raise ValueError("Input DataFrame must have a 'volume' column.")

    # ── 2. Assign clusters ───────────────────────────────────────────────────
    print("Step 1/4 — Clustering points along streets …")
    clustered = assign_clusters(df, near_thresh=near_thresh, far_thresh=far_thresh)
    n_clusters = clustered["cluster_id"].nunique()
    print(f"          {len(clustered)} points → {n_clusters} clusters\n")

    # ── 3. Aggregate to cluster level ────────────────────────────────────────
    cluster_summary = (
        clustered.groupby("cluster_id")
        .agg(
            street_name=("street_name", "first"),
            total_volume=("volume", "sum"),
            num_points=("volume", "count"),
            center_lat=("latitude", "mean"),
            center_lon=("longitude", "mean"),
        )
        .reset_index()
    )

    # ── 4. Fetch TomTom traffic data ─────────────────────────────────────────
    print("Step 2/4 — Fetching TomTom traffic data …")
    cluster_traffic = fetch_traffic_for_clusters(
        cluster_summary, api_key=api_key, request_delay=request_delay
    )
    ok = cluster_traffic["vehicles_hour"].notna().sum()
    print(f"\n          {ok}/{n_clusters} API calls succeeded\n")

    # ── 5. Build superclusters ───────────────────────────────────────────────
    print("Step 3/4 — Building superclusters …")
    enriched_clusters = build_superclusters(
        cluster_traffic, max_points=max_points_per_supercluster
    )
    n_sc = enriched_clusters["supercluster_id"].nunique()
    print(f"          {n_clusters} clusters → {n_sc} superclusters\n")

    # ── 6. Join back to original points ─────────────────────────────────────
    print("Step 4/4 — Joining results back to original points …")
    point_cols = ["cluster_id", "supercluster_id", "total_weight", "cost"]
    result = clustered.merge(
        enriched_clusters[["cluster_id"] + point_cols[1:]],
        on="cluster_id",
        how="left",
    )

    output_cols = [
        "latitude", "longitude", "street_name", "volume",
        "cluster_id", "supercluster_id", "total_weight", "cost",
    ]
    result = (
        result[output_cols]
        .sort_values("total_weight", ascending=False)
        .reset_index(drop=True)
    )

    # ── 7. Budget selection ──────────────────────────────────────────────────
    if budget is not None:
        result = _mark_within_budget(result, budget)
        n_in = result["within_budget"].sum()
        n_sc_in = result.loc[result["within_budget"], "supercluster_id"].nunique()
        spent = result.loc[result["within_budget"], "cost"] \
                      .groupby(result["supercluster_id"]).first().sum()
        print(f"          Budget ${budget:,.0f}: {n_sc_in} superclusters, "
              f"{n_in} points, ${spent:,.0f} spent\n")
    else:
        result["within_budget"] = True

    print(f"          Done. Output has {len(result)} rows.\n")
    return result
