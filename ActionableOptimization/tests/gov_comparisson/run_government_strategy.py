"""
Government pothole selection strategy — test using cached API data.

Mirrors the logic in playground/government_pothole_subsample.py but draws
velocity and flow from cluster_traffic_cache.csv (the same API snapshot used
by the pipeline tests) so both strategies are evaluated on identical data.

Algorithm
---------
Shuffle all points randomly (seed=42), then greedily pick holes one by one
within a fixed budget.  Holes are grouped into trips of up to POTHOLES_PER_TRIP:
  - Opening a new trip pays TRIP_COST once.
  - Each hole pays VOLUME_COST × volume.
  - If a hole would bust the budget, skip it (up to MAX_MISSES consecutive
    misses before giving up).

Discontent per hole = velocity × flow × volume  (= currentSpeed × cars/week × m³)

Outputs
-------
  outputs/gov_enriched_points.csv  — all points with velocity, flow,
                                     discontent, repaired flag
  maps/gov_map.html                — green = repaired, red = not repaired
"""

from pathlib import Path

import folium
import pandas as pd

HERE = Path(__file__).parent.parent
OUTPUTS_DIR = HERE / "outputs"
MAPS_DIR = HERE / "maps"

# Same constants as government_pothole_subsample.py
VOLUME_COST = 8_000
TRIP_COST = 2_000
POTHOLES_PER_TRIP = 5
BUDGET = 500_000
MAX_MISSES = 50
SEED = 42


def _load_enriched_points() -> pd.DataFrame:
    """
    Load step_03_superclusters.csv which already contains current_speed
    (extracted from the TomTom response during the pipeline run) and
    vehicles_week, so no cache file or JSON parsing is needed.
    """
    df = pd.read_csv(OUTPUTS_DIR / "step_03_superclusters.csv")
    return df.rename(columns={"current_speed": "velocity", "vehicles_week": "flow"})


def _run_selection(df: pd.DataFrame, seed: int = SEED) -> tuple[list, float, int]:
    """
    Return (selected_indices, total_cost, n_trips) for the budget-limited
    random selection.
    """
    shuffled = df.sample(frac=1, random_state=seed)

    selected: list = []
    total_cost = 0.0
    misses = 0
    trip_fill = 0
    n_trips = 0

    for idx, row in shuffled.iterrows():
        starts_new_trip = trip_fill == 0
        marginal = VOLUME_COST * row["volume"]
        if starts_new_trip:
            marginal += TRIP_COST

        if total_cost + marginal > BUDGET:
            misses += 1
            if misses >= MAX_MISSES:
                break
            continue

        total_cost += marginal
        selected.append(idx)
        misses = 0

        if starts_new_trip:
            n_trips += 1
        trip_fill = (trip_fill + 1) % POTHOLES_PER_TRIP

    return selected, total_cost, n_trips


def _print_summary(df: pd.DataFrame, total_cost: float, n_trips: int) -> None:
    n_repaired = int((df["repaired"] == 0).sum())
    baseline = df["discontent"].sum()
    remaining = df.loc[df["repaired"] == 1, "discontent"].sum()
    avoided = baseline - remaining

    print(f"Budget              : ${BUDGET:>12,.2f}")
    print(f"Total cost          : ${total_cost:>12,.2f}")
    print(f"Remaining budget    : ${BUDGET - total_cost:>12,.2f}")
    print(f"Trips opened        :  {n_trips:>11,}")
    print(f"Holes repaired      :  {n_repaired:>11,} / {len(df)}")
    print()
    print(f"Discontent (nothing fixed) : {baseline:>15,.2f}")
    print(f"Discontent (after repairs) : {remaining:>15,.2f}")
    print(f"Discontent avoided         : {avoided:>15,.2f}  ({avoided / baseline:.1%})")


def _build_map(df: pd.DataFrame) -> folium.Map:
    m = folium.Map(location=[19.415, -99.163], zoom_start=15)

    for _, row in df.iterrows():
        repaired = row["repaired"] == 0
        color = "green" if repaired else "red"
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=5,
            color=color,
            fill=True, fill_color=color, fill_opacity=0.9, weight=1,
            tooltip=folium.Tooltip(
                f"<div style='font-size:12px'>"
                f"<b>Street:</b> {row['street_name']}<br>"
                f"<b>Volume:</b> {row['volume']:.4f} m³<br>"
                f"<b>Velocity:</b> {row['velocity']} km/h<br>"
                f"<b>Flow:</b> {row['flow']:,.0f} cars/week<br>"
                f"<b>Discontent:</b> {row['discontent']:,.2f}<br>"
                f"<b>Status:</b> {'✔ repaired' if repaired else '✘ not repaired'}"
                f"</div>",
                sticky=True,
            ),
        ).add_to(m)
    return m


def main() -> None:
    print("Loading points and traffic data from cache …")
    df = _load_enriched_points()
    df["discontent"] = df["velocity"] * df["flow"] * df["volume"]
    print(f"  {len(df)} points loaded\n")

    print("Running government selection …")
    selected_idx, total_cost, n_trips = _run_selection(df)

    df["repaired"] = 1
    df.loc[selected_idx, "repaired"] = 0

    print()
    _print_summary(df, total_cost, n_trips)

    out_csv = OUTPUTS_DIR / "gov_enriched_points.csv"
    df.to_csv(out_csv, index=False)
    print(f"\nCSV  -> outputs/gov_enriched_points.csv")

    out_html = MAPS_DIR / "gov_map.html"
    _build_map(df).save(str(out_html))
    print(f"Map  -> maps/gov_map.html")


if __name__ == "__main__":
    main()
