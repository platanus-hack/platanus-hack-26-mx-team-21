#%%
"""
Government pothole subsampling under a fixed budget.

Reads the traffic points from `sample_points.csv` (the full universe of
potholes, same data plotted in `traffic_points.html`), then randomly selects
holes grouped into trips. A trip repairs up to `POTHOLES_PER_TRIP` (5) holes
and pays a single fixed `trip_cost`; on top of that each hole costs
`volume_cost * volume`. So a trip costs:

    trip_cost = TRIP_COST + volume_cost * sum(volumes of its holes)

We keep adding holes (in random order) while the running total stays within
`budget`. The first hole of a trip pays the TRIP_COST; the next four only pay
their volume cost. If a hole would push us over budget we skip it and try the
next one, giving up after `MAX_MISSES` consecutive misses. The last trip may
end with fewer than 5 holes.

Velocity (km/h) and flow (cars/week) are looked up per street from the TomTom
flow API (cached by street). Populational discontent of an unrepaired hole =
velocity * flow * volume. `sample_points.csv` is left untouched; the enriched
table is written to a NEW file `gov_traffic_points.csv` with per-hole
velocity / flow / volume / discontent and a `repaired` flag (0 = repaired,
1 = not repaired), and the selected holes are plotted to
`sub_traffic_points.html`.
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
TRIP_COST = 2000        # fixed price per trip (shared by up to 5 holes)
POTHOLES_PER_TRIP = 5   # holes repaired in a single trip
BUDGET = 500_000        # presupuesto: total money available
MAX_MISSES = 50         # consecutive over-budget holes before we give up
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
    """Return (velocity_kmh, flow_cars_per_week) for the street at a point."""
    traffic = get_traffic(lat, lon)
    velocity = traffic["currentSpeed"]
    lanes = get_lanes(traffic)
    hourly = estimate_hourly_volume(
        traffic["currentSpeed"], traffic["freeFlowSpeed"], lanes
    )
    # weekly = hourly * 12 active hours/day * 7 days (matches TomTom_API_test.py)
    weekly = hourly * 12 * 7
    return velocity, weekly


#%%
df = pd.read_csv(HERE / "sample_points.csv", index_col=0)

# volume column (the original file calls it "Volume")
if "volume" not in df.columns:
    df["volume"] = df["Volume"]

# Add velocity / flow per street (TomTom), cached so each street is hit once.
if "velocity" not in df.columns or "flow" not in df.columns:
    if not TOMTOM_API_KEY:
        raise SystemExit(
            "No TomTom_API_Key set. Add it to a .env file to look up "
            "velocity and flow for each street."
        )

    street_cache = {}
    velocities, flows = [], []
    for _, row in df.iterrows():
        street = row["street_name"]
        if street not in street_cache:
            try:
                street_cache[street] = street_velocity_and_flow(
                    row["latitude"], row["longitude"]
                )
            except Exception:
                street_cache[street] = (None, None)
        v, f = street_cache[street]
        velocities.append(v)
        flows.append(f)
    df["velocity"] = velocities
    df["flow"] = flows
    print(f"Streets queried via TomTom: {len(street_cache)}")

#%%
# --- Budget-limited random selection (trip-based) ---
shuffled = df.sample(frac=1, random_state=SEED)

selected_idx = []
total_cost = 0.0
misses = 0      # consecutive holes that didn't fit the remaining budget
trip_fill = 0   # holes already in the trip currently being filled
n_trips = 0     # number of trips opened

for idx, row in shuffled.iterrows():
    starts_new_trip = trip_fill == 0

    # A new trip pays the fixed TRIP_COST; holes added to an already-open
    # trip only pay for their own volume.
    marginal_cost = VOLUME_COST * row["volume"]
    if starts_new_trip:
        marginal_cost += TRIP_COST

    if total_cost + marginal_cost > BUDGET:
        # Doesn't fit: skip it and try the next one, but give up after
        # MAX_MISSES consecutive misses. The trip being filled keeps whatever
        # holes it already has, so it can end with fewer than 5.
        misses += 1
        if misses >= MAX_MISSES:
            break
        continue

    total_cost += marginal_cost
    selected_idx.append(idx)
    misses = 0  # reset the miss streak after a successful pick

    if starts_new_trip:
        n_trips += 1
    trip_fill += 1
    if trip_fill == POTHOLES_PER_TRIP:
        trip_fill = 0  # trip is full; the next pick starts a new trip

# repaired = 0 if the hole was selected/repaired, 1 if it was left unrepaired
df["repaired"] = 1
df.loc[selected_idx, "repaired"] = 0

# Per-hole populational discontent (counts only if left unrepaired).
df["discontent"] = df["velocity"] * df["flow"] * df["volume"]

n_selected = int((df["repaired"] == 0).sum())
print(f"Budget            : {BUDGET:,.2f}")
print(f"Holes selected    : {n_selected} / {len(df)}")
print(f"Trips             : {n_trips} (up to {POTHOLES_PER_TRIP} holes each)")
print(f"Total cost        : {total_cost:,.2f}")
print(f"Remaining budget  : {BUDGET - total_cost:,.2f}")

out_csv = HERE / "gov_traffic_points.csv"
df.to_csv(out_csv)
print(f"Enriched table written to {out_csv}")

#%%
# --- Populational discontent ---
# baseline  -> discontent if we fix NOTHING (every hole)
# remaining -> discontent after our budget-limited repairs (unrepaired holes)
baseline = df["discontent"].sum()
remaining = df.loc[df["repaired"] == 1, "discontent"].sum()
avoided = baseline - remaining

print()
print(f"DISCONTENT if we fix NOTHING   ({len(df)} holes): {baseline:,.2f}")
n_left = int((df['repaired'] == 1).sum())
print(f"DISCONTENT after repairs ({n_left} left): {remaining:,.2f}")
print(f"DISCONTENT avoided by repairs           : {avoided:,.2f} "
      f"({avoided / baseline:.1%})")

#%%
# --- Build HTML map (same style as traffic_points.html) ---
# Green = repaired, red = left unrepaired.
m = folium.Map(location=[19.4326, -99.1332], zoom_start=12)

for _, row in df.iterrows():
    repaired = row["repaired"] == 0
    color = "green" if repaired else "red"

    tooltip = folium.Tooltip(
        f"""
        <div style="font-size:12px">
            <b>Street:</b> {row['street_name']}<br>
            <b>Volume:</b> {row['volume']:,.3f} m^3<br>
            <b>Velocity:</b> {row['velocity']} km/h<br>
            <b>Flow:</b> {row['flow']:,.0f} cars/week<br>
            <b>Discontent:</b> {row['discontent']:,.2f}<br>
            <b>Status:</b> {'repaired' if repaired else 'NOT repaired'}
        </div>
        """,
        sticky=True,
    )

    folium.CircleMarker(
        location=[row["latitude"], row["longitude"]],
        radius=6,
        color=color,
        fill=True,
        fill_color=color,
        fill_opacity=0.9,
        weight=2,
        tooltip=tooltip,
    ).add_to(m)

out_html = HERE / "sub_traffic_points.html"
m.save(str(out_html))
print(f"Map written to {out_html}")
m
#%%
