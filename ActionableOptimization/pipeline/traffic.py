"""
TomTom Traffic Flow API wrapper.

Given a cluster-level DataFrame (with center_lat, center_lon, total_volume),
fetches flow data for every cluster centre and enriches the DataFrame with:
  - vehicles_hour
  - vehicles_week
  - free_flow_speed
  - weight  (total_volume × vehicles_week × free_flow_speed)
  - tomtom_response  (raw JSON string, kept for auditability)
"""

import json
import time

import pandas as pd
import requests

_FRC_LANE_MAP = {
    "FRC0": 6.0,
    "FRC1": 6.0,
    "FRC2": 4.0,
    "FRC3": 3.0,
    "FRC4": 2.0,
    "FRC5": 1.5,
    "FRC6": 1.0,
}
_CAPACITY_PER_LANE = 1800
_DAILY_HOURS = 12
_DAYS_PER_WEEK = 7


def _get_traffic(lat: float, lon: float, api_key: str) -> dict:
    url = (
        "https://api.tomtom.com/traffic/services/4/"
        "flowSegmentData/absolute/10/json"
    )
    r = requests.get(url, params={"point": f"{lat},{lon}", "key": api_key}, timeout=10)
    r.raise_for_status()
    return r.json()["flowSegmentData"]


def _lanes(response: dict) -> float:
    return _FRC_LANE_MAP.get(response.get("frc", "FRC3"), 3.0)


def _hourly_volume(current_speed: float, free_flow_speed: float, lanes: float) -> int:
    return round(lanes * _CAPACITY_PER_LANE * (current_speed / free_flow_speed))


def _weekly_volume(hourly: int) -> int:
    return round(hourly * _DAILY_HOURS * _DAYS_PER_WEEK)


def fetch_traffic_for_clusters(
    clusters_df: pd.DataFrame,
    api_key: str,
    request_delay: float = 0.25,
) -> pd.DataFrame:
    """
    Enrich *clusters_df* with traffic data from the TomTom Flow API.

    Parameters
    ----------
    clusters_df:
        Must contain ``cluster_id``, ``center_lat``, ``center_lon``,
        ``total_volume``.
    api_key:
        TomTom API key.
    request_delay:
        Seconds to sleep between requests (respects free-tier rate limit).

    Returns
    -------
    Copy of *clusters_df* with added columns:
    ``vehicles_hour``, ``vehicles_week``, ``free_flow_speed``,
    ``weight``, ``tomtom_response``.
    Failed rows get null values for traffic columns.
    """
    rows = []
    total = len(clusters_df)

    for i, (_, cluster) in enumerate(clusters_df.iterrows(), start=1):
        try:
            traffic = _get_traffic(cluster["center_lat"], cluster["center_lon"], api_key)
            lanes = _lanes(traffic)
            v_hour = _hourly_volume(traffic["currentSpeed"], traffic["freeFlowSpeed"], lanes)
            v_week = _weekly_volume(v_hour)
            ffs = traffic["freeFlowSpeed"]

            rows.append({
                **cluster.to_dict(),
                "vehicles_hour": v_hour,
                "vehicles_week": v_week,
                "free_flow_speed": ffs,
                "weight": cluster["total_volume"] * v_week * ffs,
                "tomtom_response": json.dumps(traffic),
            })
            print(f"  [{i:>3}/{total}] cluster {cluster['cluster_id']:>4} "
                  f"— {v_hour:>6,} veh/h  {cluster['street_name']}")

        except Exception as exc:
            print(f"  [{i:>3}/{total}] cluster {cluster['cluster_id']:>4} — ERROR: {exc}")
            rows.append({
                **cluster.to_dict(),
                "vehicles_hour": None,
                "vehicles_week": None,
                "free_flow_speed": None,
                "weight": None,
                "tomtom_response": None,
            })

        time.sleep(request_delay)

    return pd.DataFrame(rows)
