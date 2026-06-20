import colorsys

import folium
import pandas as pd
import numpy as np
from math import radians, sin, cos, sqrt, atan2
from pathlib import Path

HERE = Path(__file__).parent

def haversine(lat1, lon1, lat2, lon2):
    """Return distance in meters between two GPS coordinates."""
    R = 6_371_000
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlam = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlam / 2) ** 2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))


def sort_along_street(group: pd.DataFrame) -> pd.DataFrame:
    """Sort points along the street's main axis using PCA on lat/lon."""
    if len(group) <= 1:
        return group

    coords = group[["latitude", "longitude"]].values
    centroid = coords.mean(axis=0)
    centered = coords - centroid

    # PCA: first principal component = main street direction
    _, _, Vt = np.linalg.svd(centered, full_matrices=False)
    axis = Vt[0]  # shape (2,)

    projections = centered @ axis
    order = np.argsort(projections)
    return group.iloc[order]


def cluster_street(points: pd.DataFrame, near_thresh=100, far_thresh=20):
    """
    Apply the chaining rule to a single street's sorted points.

    While dist(anchor, current) <= near_thresh  → extend current cluster.
    Once dist(anchor, current) > near_thresh:
        dist(prev, current) <= far_thresh → still extend (chain mode).
        dist(prev, current) >  far_thresh → start new cluster.
    """
    clusters = []
    current_cluster_indices = []

    anchor_lat = anchor_lon = None
    prev_lat = prev_lon = None

    for _, row in points.iterrows():
        lat, lon = row["latitude"], row["longitude"]

        if anchor_lat is None:
            # First point of the street → start first cluster
            anchor_lat, anchor_lon = lat, lon
            prev_lat, prev_lon = lat, lon
            current_cluster_indices = [row.name]
            continue

        dist_anchor = haversine(anchor_lat, anchor_lon, lat, lon)
        dist_prev = haversine(prev_lat, prev_lon, lat, lon)

        if dist_anchor <= near_thresh:
            current_cluster_indices.append(row.name)
        elif dist_prev <= far_thresh:
            # Still within chaining distance of the previous point
            current_cluster_indices.append(row.name)
        else:
            # Too far from both anchor and previous point → new cluster
            clusters.append(current_cluster_indices)
            current_cluster_indices = [row.name]
            anchor_lat, anchor_lon = lat, lon

        prev_lat, prev_lon = lat, lon

    if current_cluster_indices:
        clusters.append(current_cluster_indices)

    return clusters


def main():
    df = pd.read_csv(HERE / "sample_points.csv", index_col=0)

    # Drop rows without a street name
    df_named = df.dropna(subset=["street_name"]).copy()

    cluster_id = 0
    cluster_col = pd.Series(index=df_named.index, dtype="Int64", name="cluster_id")

    for street, group in df_named.groupby("street_name"):
        sorted_group = sort_along_street(group)
        street_clusters = cluster_street(sorted_group)

        for point_indices in street_clusters:
            cluster_col.loc[point_indices] = cluster_id
            cluster_id += 1

    df_named["cluster_id"] = cluster_col

    df_named.to_csv(HERE / "clustered_points.csv")

    # Summary
    n_streets = df_named["street_name"].nunique()
    n_clusters = df_named["cluster_id"].nunique()
    print(f"Streets processed : {n_streets}")
    print(f"Total clusters    : {n_clusters}")
    print()

    summary = (
        df_named.groupby("street_name")["cluster_id"]
        .nunique()
        .rename("num_clusters")
        .reset_index()
        .sort_values("num_clusters", ascending=False)
    )
    print(summary.to_string(index=False))
    print()
    print("Output written to clustered_points.csv")

    # --- Build HTML map ---
    # Assign a visually distinct color to each cluster using the golden-ratio
    # hue trick so that nearby cluster IDs look different from each other.
    GOLDEN = 0.618033988749895
    unique_ids = sorted(df_named["cluster_id"].dropna().unique())

    def cluster_color(cid):
        hue = (cid * GOLDEN) % 1.0
        r, g, b = colorsys.hsv_to_rgb(hue, 0.75, 0.92)
        return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))

    color_map = {cid: cluster_color(int(cid)) for cid in unique_ids}

    center_lat = df_named["latitude"].mean()
    center_lon = df_named["longitude"].mean()
    m = folium.Map(location=[center_lat, center_lon], zoom_start=15)

    for _, row in df_named.iterrows():
        cid = row["cluster_id"]
        color = color_map.get(cid, "#888888")
        tooltip = folium.Tooltip(
            f"""
            <div style="font-size:12px">
                <b>Street:</b> {row['street_name']}<br>
                <b>Cluster:</b> {int(cid)}
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

    out_html = HERE / "clustered_points_map.html"
    m.save(str(out_html))
    print(f"Map written to  {out_html}")


if __name__ == "__main__":
    main()
