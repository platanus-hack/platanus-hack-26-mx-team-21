#%%
import requests
import time
import gzip
import json
from dotenv import load_dotenv
import os

load_dotenv()  # loads .env from current directory

TOMTOM_API_KEY  = os.getenv("TomTom_API_Key")

# Example:
LAT = 19.3564
LON = -99.1898

#%%

def get_traffic(lat, lon):

    url = (
        "https://api.tomtom.com/traffic/services/4/"
        "flowSegmentData/absolute/10/json"
    )

    params = {
        "point": f"{lat},{lon}",
        "key": TOMTOM_API_KEY
    }

    r = requests.get(url, params=params)
    r.raise_for_status()

    return r.json()["flowSegmentData"]

def get_lanes(tomtom_response):

    FRC_LANE_MAP = {
        "FRC0": (4, 10, 6),
        "FRC1": (4, 8, 6),
        "FRC2": (3, 6, 4),
        "FRC3": (2, 4, 3),
        "FRC4": (2, 2, 2),
        "FRC5": (1, 2, 1.5),
        "FRC6": (1, 1, 1),
    }
    
    return FRC_LANE_MAP.get(tomtom_response.get('frc'), 2)[2]

def estimate_hourly_volume(
    current_speed,
    free_flow_speed,
    lanes
):

    CAPACITY_PER_LANE = 1800

    congestion_factor = (
        current_speed / free_flow_speed
    )

    hourly_volume = (
        lanes *
        CAPACITY_PER_LANE *
        congestion_factor
    )

    return round(hourly_volume)

def estimate_daily_volume(hourly_volume):
    return round(hourly_volume * 12)

def estimate_weekly_volume(daily_volume):
    return round(daily_volume * 7)

#%%

traffic = get_traffic(LAT, LON)

lanes = get_lanes(traffic)

hourly = estimate_hourly_volume(
    traffic["currentSpeed"],
    traffic["freeFlowSpeed"],
    lanes
)

daily = estimate_daily_volume(hourly)

weekly = estimate_weekly_volume(daily)

print("Current speed:", traffic["currentSpeed"])
print("Free flow speed:", traffic["freeFlowSpeed"])
print("Lanes:", lanes)

print("Vehicles/hour:", f"{hourly:,}")
print("Vehicles/day:", f"{daily:,}")
print("Vehicles/week:", f"{weekly:,}")

#%%