"""
Visual integration test for the ActionableOptimization pipeline.

Produces three HTML maps in tests/maps/:

  map_01_input_points.html  – raw input points, coloured green→red by volume
  map_02_clusters.html      – points coloured by cluster_id
  map_03_superclusters.html – points coloured by supercluster_id;
                               tooltip shows weight, cost, point count

Traffic data is loaded from a local cache (tests/cache/) so no API calls are
made on repeat runs.  On the very first run the cache is seeded from the
pre-fetched playground/cluster_traffic.csv if it exists; otherwise the
TomTom API is called (requires TomTom_API_Key in .env).

Usage
-----
    python tests/generate_maps.py          # from ActionableOptimization/
"""

import json
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

# ── Path setup ────────────────────────────────────────────────────────────────
HERE = Path(__file__).parent                        # ActionableOptimization/tests/
ACTION_ROOT = HERE.parent                           # ActionableOptimization/
REPO_ROOT = ACTION_ROOT.parent                      # Platanus_Hackathon_2026/
PLAYGROUND = ACTION_ROOT / "playground"

sys.path.insert(0, str(ACTION_ROOT))

from pipeline.clustering import assign_clusters
from pipeline.traffic import fetch_traffic_for_clusters
from pipeline.superclustering import build_superclusters
from tests.visualization import map_input_points, map_clusters, map_superclusters

CACHE_DIR = HERE / "cache"
MAPS_DIR = HERE / "maps"
OUTPUTS_DIR = HERE / "outputs"
CACHE_FILE = CACHE_DIR / "cluster_traffic_cache.csv"
PLAYGROUND_TRAFFIC = PLAYGROUND / "cluster_traffic.csv"

CACHE_DIR.mkdir(exist_ok=True)
MAPS_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)

load_dotenv(REPO_ROOT / ".env")
TOMTOM_KEY = os.getenv("TomTom_API_Key")

# Traffic columns produced by fetch_traffic_for_clusters that we need
_TRAFFIC_COLS = [
    "cluster_id", "street_name", "total_volume", "num_points",
    "center_lat", "center_lon",
    "vehicles_hour", "vehicles_week", "free_flow_speed",
    "weight", "tomtom_response",
]


def _load_or_build_traffic(cluster_summary: pd.DataFrame) -> pd.DataFrame:
    """Return cluster-level traffic DataFrame, using cache when available."""

    if CACHE_FILE.exists():
        print(f"  Using cache: {CACHE_FILE.name}")
        return pd.read_csv(CACHE_FILE)

    # Seed cache from playground data (same points → same clusters)
    if PLAYGROUND_TRAFFIC.exists():
        print(f"  Seeding cache from playground/{PLAYGROUND_TRAFFIC.name} …")
        traffic = pd.read_csv(PLAYGROUND_TRAFFIC)[_TRAFFIC_COLS]
        traffic.to_csv(CACHE_FILE, index=False)
        return traffic

    # Last resort: hit the API
    print("  No cache found — calling TomTom API (this takes ~2 min) …")
    if not TOMTOM_KEY:
        raise RuntimeError("TomTom_API_Key not set in .env and no cache available.")
    traffic = fetch_traffic_for_clusters(cluster_summary, api_key=TOMTOM_KEY)
    traffic[_TRAFFIC_COLS].to_csv(CACHE_FILE, index=False)
    return traffic


def main() -> None:
    # ── Load input points ─────────────────────────────────────────────────────
    print("Loading input points …")
    points = pd.read_csv(PLAYGROUND / "sample_points.csv", index_col=0)
    points.columns = [c.lower() for c in points.columns]
    print(f"  {len(points)} points loaded\n")

    # ── Step 1: save + map ───────────────────────────────────────────────────
    print("Generating step 1 outputs …")
    points.to_csv(OUTPUTS_DIR / "step_01_input_points.csv", index=False)
    map_input_points(points).save(str(MAPS_DIR / "map_01_input_points.html"))

    # ── Step 2: clustering ────────────────────────────────────────────────────
    print("\nClustering points …")
    clustered = assign_clusters(points)
    n_clusters = clustered["cluster_id"].nunique()
    print(f"  {n_clusters} clusters")

    print("Generating step 2 outputs …")
    clustered.to_csv(OUTPUTS_DIR / "step_02_clusters.csv", index=False)
    map_clusters(clustered).save(str(MAPS_DIR / "map_02_clusters.html"))

    # ── Step 3: traffic data ──────────────────────────────────────────────────
    print("\nLoading traffic data …")
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
    cluster_traffic = _load_or_build_traffic(cluster_summary)

    # ── Step 4: superclusters ─────────────────────────────────────────────────
    print("\nBuilding superclusters …")
    cluster_traffic["current_speed"] = cluster_traffic["tomtom_response"].apply(
        lambda s: json.loads(s)["currentSpeed"]
    )
    enriched = build_superclusters(cluster_traffic)
    n_sc = enriched["supercluster_id"].nunique()
    print(f"  {n_sc} superclusters")

    # Join cluster-level traffic + supercluster info back to original points
    point_enrichment = enriched[[
        "cluster_id", "supercluster_id", "total_weight", "cost",
        "vehicles_hour", "vehicles_week", "free_flow_speed", "current_speed", "weight",
        "total_volume", "num_points", "center_lat", "center_lon",
    ]]
    result = (
        clustered
        .merge(point_enrichment, on="cluster_id", how="left")
        .sort_values("total_weight", ascending=False)
        .reset_index(drop=True)
    )

    print("Generating step 3 outputs …")
    result.to_csv(OUTPUTS_DIR / "step_03_superclusters.csv", index=False)
    map_superclusters(result).save(str(MAPS_DIR / "map_03_superclusters.html"))

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"""
Outputs saved to tests/outputs/
  step_01_input_points.csv  — {len(points)} rows  (latitude, longitude, street_name, volume)
  step_02_clusters.csv      — {len(clustered)} rows  (+ cluster_id)
  step_03_superclusters.csv — {len(result)} rows  (+ supercluster_id, weight, cost, traffic)

Maps saved to tests/maps/
  map_01_input_points.html  — coloured by volume
  map_02_clusters.html      — {n_clusters} clusters
  map_03_superclusters.html — {n_sc} superclusters
""")


if __name__ == "__main__":
    main()
