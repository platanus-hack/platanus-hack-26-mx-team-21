#%%
"""
Government pothole subsampling under a fixed budget.

Reads the synthetic street points from `sample_points.csv`, then randomly
selects potholes grouped into trips. A trip repairs up to
`POTHOLES_PER_TRIP` (5) potholes and pays a single fixed `trip_cost`; on top
of that each pothole costs `volume_cost * pothole_volume`. So a trip costs:

    trip_cost = TRIP_COST + volume_cost * sum(volumes of its potholes)

We keep adding potholes (in random order) while the running total stays
within `budget`. The first pothole of a trip pays the TRIP_COST; the next
four only pay their volume cost. If a pothole would push us over budget we
skip it and try the next one, giving up after `MAX_MISSES` consecutive
potholes that don't fit. The last trip may end with fewer than 5 potholes
(4, 3, ...) if no cheap-enough pothole is found before we stop. The selected
subset is written to `sub_sample_points.csv` and plotted to
`sub_traffic_points.html` (same style as `traffic_points.html`).
"""

import os

import folium
import pandas as pd
import requests
from dotenv import load_dotenv
from pathlib import Path

HERE = Path(__file__).parent
load_dotenv()  # loads .env (expects TomTom_API_Key) if present

TOMTOM_API_KEY = os.getenv("TomTom_API_Key")

# --- Constants ---
VOLUME_COST = 8000      # price per m^3 of pothole repaired
TRIP_COST = 2000        # fixed price per trip (shared by up to 5 potholes)
POTHOLES_PER_TRIP = 5   # potholes repaired in a single trip
BUDGET = 500_000        # presupuesto: total money available
MAX_MISSES = 50         # consecutive over-budget potholes before we give up
SEED = 42               # for reproducible random selection


# --- Traffic helpers (TomTom Flow Segment API), mirrors TomTom_API_test.py ---
def get_traffic(lat, lon):
    url = (
        "https://api.tomtom.com/traffic/services/4/"
        "flowSegmentData/absolute/10/json"
    )
    params = {"point": f"{lat},{lon}", "key": TOMTOM_API_KEY}
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
    entry = FRC_LANE_MAP.get(tomtom_response.get("frc"))
    return entry[2] if entry else 2


def estimate_hourly_volume(current_speed, free_flow_speed, lanes):
    CAPACITY_PER_LANE = 1800
    congestion_factor = current_speed / free_flow_speed
    return round(lanes * CAPACITY_PER_LANE * congestion_factor)


def street_velocity_and_flow(lat, lon):
    """Return (velocity_kmh, flow_cars_per_hour) for the street at a point."""
    traffic = get_traffic(lat, lon)
    velocity = traffic["currentSpeed"]
    lanes = get_lanes(traffic)
    flow = estimate_hourly_volume(
        traffic["currentSpeed"], traffic["freeFlowSpeed"], lanes
    )
    return velocity, flow

#%%
df = pd.read_csv(HERE / "sample_points.csv", index_col=0)

# Random order of all candidate potholes
shuffled = df.sample(frac=1, random_state=SEED)

selected_rows = []
total_cost = 0.0
misses = 0      # consecutive potholes that didn't fit the remaining budget
trip_fill = 0   # potholes already in the trip currently being filled
n_trips = 0     # number of trips opened

for _, row in shuffled.iterrows():
    starts_new_trip = trip_fill == 0

    # A new trip pays the fixed TRIP_COST; potholes added to an already-open
    # trip only pay for their own volume.
    marginal_cost = VOLUME_COST * row["Volume"]
    if starts_new_trip:
        marginal_cost += TRIP_COST

    if total_cost + marginal_cost > BUDGET:
        # Doesn't fit: skip it and try the next one, but give up after
        # MAX_MISSES consecutive misses. The trip being filled keeps whatever
        # potholes it already has, so it can end with fewer than 5.
        misses += 1
        if misses >= MAX_MISSES:
            break
        continue

    total_cost += marginal_cost
    selected_rows.append(row)
    misses = 0  # reset the miss streak after a successful pick

    if starts_new_trip:
        n_trips += 1
    trip_fill += 1
    if trip_fill == POTHOLES_PER_TRIP:
        trip_fill = 0  # trip is full; the next pick starts a new trip

selected = pd.DataFrame(selected_rows)

print(f"Budget            : {BUDGET:,.2f}")
print(f"Potholes selected : {len(selected)} / {len(df)}")
print(f"Trips             : {n_trips} (up to {POTHOLES_PER_TRIP} potholes each)")
print(f"Total cost        : {total_cost:,.2f}")
print(f"Remaining budget  : {BUDGET - total_cost:,.2f}")

selected.to_csv(HERE / "sub_sample_points.csv")

#%%
# --- Populational discontent ---
# Discontent comes from the potholes we did NOT repair. For each unselected
# pothole, discontent = street velocity * street flow (cars/hour) * pothole
# volume. We sum it over every unrepaired pothole for a single final number.
not_selected = df.drop(index=selected.index)

print()
print(f"Unrepaired potholes : {len(not_selected)}")

if not TOMTOM_API_KEY:
    print("No TomTom_API_Key set -> skipping discontent calculation.")
    print("Add it to a .env file to compute populational discontent.")
else:
    total_discontent = 0.0
    n_scored = 0
    n_failed = 0

    # Velocity and flow are street-level, so look up each street once and
    # reuse the result for every unrepaired pothole on it.
    street_cache = {}

    for _, row in not_selected.iterrows():
        street = row["street_name"]
        if street not in street_cache:
            try:
                street_cache[street] = street_velocity_and_flow(
                    row["latitude"], row["longitude"]
                )
            except Exception:
                street_cache[street] = None

        vf = street_cache[street]
        if vf is None:
            n_failed += 1
            continue

        velocity, flow = vf
        total_discontent += velocity * flow * row["Volume"]
        n_scored += 1

    print(f"  streets queried   : {len(street_cache)}")
    print(f"  potholes scored   : {n_scored}")
    if n_failed:
        print(f"  skipped (API err) : {n_failed}")
    print(
        "POPULATIONAL DISCONTENT (velocity x flow x volume): "
        f"{total_discontent:,.2f}"
    )

#%%
# --- Build HTML map (same style as traffic_points.html) ---
m = folium.Map(
    location=[19.4326, -99.1332],
    zoom_start=12
)

for _, row in selected.iterrows():

    repair_cost = VOLUME_COST * row["Volume"]  # trip cost is shared, not per-pothole

    tooltip = folium.Tooltip(
        f"""
        <div style="font-size:12px">
            <b>Street:</b> {row['street_name']}<br>
            <b>Volume:</b> {row['Volume']:,.3f} m^3<br>
            <b>Repair cost:</b> {repair_cost:,.2f}
        </div>
        """,
        sticky=True
    )

    folium.CircleMarker(
        location=[row["latitude"], row["longitude"]],
        radius=6,
        color="red",
        fill=True,
        fill_color="yellow",
        fill_opacity=1,
        weight=3,
        tooltip=tooltip
    ).add_to(m)

out_html = HERE / "sub_traffic_points.html"
m.save(str(out_html))
print(f"Map written to {out_html}")
m
#%%
