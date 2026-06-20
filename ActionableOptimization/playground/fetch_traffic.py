import json
import os
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent.parent  # …/Platanus_Hackathon_2026

load_dotenv(REPO_ROOT / ".env")
TOMTOM_API_KEY = os.getenv("TomTom_API_Key")


# ── TomTom helpers (copied from TomTom_API_test.py) ──────────────────────────

FRC_LANE_MAP = {
    "FRC0": (4, 10, 6),
    "FRC1": (4, 8, 6),
    "FRC2": (3, 6, 4),
    "FRC3": (2, 4, 3),
    "FRC4": (2, 2, 2),
    "FRC5": (1, 2, 1.5),
    "FRC6": (1, 1, 1),
}


def get_traffic(lat, lon):
    url = (
        "https://api.tomtom.com/traffic/services/4/"
        "flowSegmentData/absolute/10/json"
    )
    r = requests.get(url, params={"point": f"{lat},{lon}", "key": TOMTOM_API_KEY})
    r.raise_for_status()
    return r.json()["flowSegmentData"]


def get_lanes(tomtom_response):
    return FRC_LANE_MAP.get(tomtom_response.get("frc"), (2, 2, 2))[2]


def estimate_hourly_volume(current_speed, free_flow_speed, lanes):
    congestion_factor = current_speed / free_flow_speed
    return round(lanes * 1800 * congestion_factor)


def estimate_weekly_volume(hourly_volume):
    daily = hourly_volume * 12
    return round(daily * 7)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    clusters = pd.read_csv(HERE / "cluster_summary.csv")
    total = len(clusters)

    rows = []
    for i, (_, cluster) in enumerate(clusters.iterrows(), start=1):
        cid = cluster["cluster_id"]
        lat = cluster["center_lat"]
        lon = cluster["center_lon"]

        try:
            traffic = get_traffic(lat, lon)
            lanes = get_lanes(traffic)
            vehicles_hour = estimate_hourly_volume(
                traffic["currentSpeed"], traffic["freeFlowSpeed"], lanes
            )
            vehicles_week = estimate_weekly_volume(vehicles_hour)

            rows.append({
                "cluster_id": cid,
                "street_name": cluster["street_name"],
                "total_volume": cluster["total_volume"],
                "num_points": cluster["num_points"],
                "center_lat": lat,
                "center_lon": lon,
                "vehicles_hour": vehicles_hour,
                "vehicles_week": vehicles_week,
                "tomtom_response": json.dumps(traffic),
            })
            print(f"[{i:>3}/{total}] cluster {cid:>4} — {vehicles_hour:>6,} veh/h  {cluster['street_name']}")

        except Exception as e:
            print(f"[{i:>3}/{total}] cluster {cid:>4} — ERROR: {e}")
            rows.append({
                "cluster_id": cid,
                "street_name": cluster["street_name"],
                "total_volume": cluster["total_volume"],
                "num_points": cluster["num_points"],
                "center_lat": lat,
                "center_lon": lon,
                "vehicles_hour": None,
                "vehicles_week": None,
                "tomtom_response": None,
            })

        # Respect TomTom free-tier rate limit (~5 req/s)
        time.sleep(0.25)

    result = pd.DataFrame(rows)
    result.to_csv(HERE / "cluster_traffic.csv", index=False)
    print(f"\nDone. Output written to cluster_traffic.csv")
    print(f"Successful calls : {result['vehicles_hour'].notna().sum()} / {total}")


if __name__ == "__main__":
    main()
