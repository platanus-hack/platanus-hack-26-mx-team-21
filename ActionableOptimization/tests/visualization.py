"""
Folium map builders for each pipeline stage.
"""

import colorsys

import folium
import pandas as pd

_GOLDEN = 0.618033988749895
_CENTER = [19.415, -99.163]
_ZOOM = 15


def _id_color(cid: int) -> str:
    hue = (int(cid) * _GOLDEN) % 1.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.75, 0.92)
    return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))


def _volume_color(volume: float, vmin: float, vmax: float) -> str:
    """Continuous green → yellow → red scale."""
    t = (volume - vmin) / (vmax - vmin) if vmax > vmin else 0.5
    t = max(0.0, min(1.0, t))
    if t < 0.5:
        r, g = int(510 * t), 200
    else:
        r, g = 255, int(200 * (1 - (t - 0.5) * 2))
    return "#{:02x}{:02x}00".format(r, g)


def _base_map() -> folium.Map:
    return folium.Map(location=_CENTER, zoom_start=_ZOOM)


def map_input_points(df: pd.DataFrame) -> folium.Map:
    """
    One marker per input point, coloured green→red by volume.

    Required columns: latitude, longitude, street_name, volume.
    """
    m = _base_map()
    vmin, vmax = df["volume"].min(), df["volume"].max()

    for _, row in df.iterrows():
        color = _volume_color(row["volume"], vmin, vmax)
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=5,
            color=color,
            fill=True, fill_color=color, fill_opacity=0.9, weight=1,
            tooltip=folium.Tooltip(
                f"<div style='font-size:12px'>"
                f"<b>Street:</b> {row['street_name']}<br>"
                f"<b>Volume:</b> {row['volume']:.4f}"
                f"</div>",
                sticky=True,
            ),
        ).add_to(m)
    return m


def map_clusters(df: pd.DataFrame) -> folium.Map:
    """
    One marker per point, coloured by cluster_id.

    Required columns: latitude, longitude, street_name, volume, cluster_id.
    """
    m = _base_map()

    for _, row in df.iterrows():
        color = _id_color(int(row["cluster_id"]))
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=5,
            color=color,
            fill=True, fill_color=color, fill_opacity=0.9, weight=1,
            tooltip=folium.Tooltip(
                f"<div style='font-size:12px'>"
                f"<b>Street:</b> {row['street_name']}<br>"
                f"<b>Cluster:</b> {int(row['cluster_id'])}<br>"
                f"<b>Volume:</b> {row['volume']:.4f}"
                f"</div>",
                sticky=True,
            ),
        ).add_to(m)
    return m


def map_superclusters(df: pd.DataFrame) -> folium.Map:
    """
    One marker per point, coloured by supercluster_id.
    Tooltip shows supercluster-level stats.

    Required columns: latitude, longitude, street_name, volume,
                      cluster_id, supercluster_id, total_weight, cost.
    """
    m = _base_map()

    # Pre-compute supercluster-level num_points for the tooltip
    sc_pts = df.groupby("supercluster_id")["cluster_id"].transform("count")

    for (_, row), sc_count in zip(df.iterrows(), sc_pts):
        color = _id_color(int(row["supercluster_id"]))
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=5,
            color=color,
            fill=True, fill_color=color, fill_opacity=0.9, weight=1,
            tooltip=folium.Tooltip(
                f"<div style='font-size:12px'>"
                f"<b>Street:</b> {row['street_name']}<br>"
                f"<b>Volume:</b> {row['volume']:.4f}<br>"
                f"<hr style='margin:3px 0'>"
                f"<b>Cluster:</b> {int(row['cluster_id'])}<br>"
                f"<hr style='margin:3px 0'>"
                f"<b>Supercluster:</b> {int(row['supercluster_id'])}<br>"
                f"<b>SC points:</b> {sc_count}<br>"
                f"<b>SC weight:</b> {row['total_weight']:,.0f}<br>"
                f"<b>SC cost:</b> ${row['cost']:,.0f}"
                f"</div>",
                sticky=True,
            ),
        ).add_to(m)
    return m
