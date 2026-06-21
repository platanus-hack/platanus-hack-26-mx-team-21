#%%
import osmnx as ox

#%%
import geopandas as gpd
import numpy as np
from shapely.geometry import Point

import osmnx as ox
import geopandas as gpd
import numpy as np

def generate_street_points(
    place=["Mexico City, Mexico"],
    n_points=230_000,
    seed=42
):
    np.random.seed(seed)

    G = ox.graph_from_place(place, network_type="drive")

    edges = ox.graph_to_gdfs(G, nodes=False)

    edges = edges.to_crs(edges.estimate_utm_crs())

    edges["seg_length"] = edges.geometry.length

    probs = edges["seg_length"] / edges["seg_length"].sum()

    sampled_idx = np.random.choice(
        edges.index,
        size=n_points,
        replace=True,
        p=probs
    )

    results = []

    for idx in sampled_idx:

        edge = edges.loc[idx]
        line = edge.geometry

        # Random point along street segment
        d = np.random.uniform(0, line.length)
        p = line.interpolate(d)

        # Get street name
        street = edge.get("name", "Unknown")

        # OSM can sometimes store multiple names as a list
        if isinstance(street, list):
            street = ", ".join(map(str, street))

        results.append({
            "geometry": p,
            "street_name": street
        })

    gdf = gpd.GeoDataFrame(results, crs=edges.crs)

    gdf = gdf.to_crs(4326)

    gdf["latitude"] = gdf.geometry.y
    gdf["longitude"] = gdf.geometry.x

    return gdf[["latitude", "longitude", "street_name"]]

# Example
pts = generate_street_points(
    n_points=230_000
)

print(pts[:5])


#%%

import numpy as np
from scipy.stats import truncnorm

# Desired parameters
mu = 0.03575
min_val = 0.0045
max_val = 0.12

# Assume minimum is mu - 3σ
sigma = (mu - min_val) / 3

# Truncated normal limits in standard units
a = (min_val - mu) / sigma
b = (max_val - mu) / sigma

# Generate sample
n = 230_000

sample = truncnorm.rvs(
    a, b,
    loc=mu,
    scale=sigma,
    size=n,
    random_state=42
)

print("Mean:", sample.mean())
print("Min :", sample.min())
print("Max :", sample.max())
print("Std :", sample.std())

pts['Volume'] = sample


#%%
import folium

m = folium.Map(
    location=[19.4326, -99.1332],
    zoom_start=12
)

for _, row in pts.iterrows():

    tooltip = folium.Tooltip(
        f"""
        <div style="font-size:12px">
            <b>Street:</b> {row['street_name']}<br>
            <b>Volume:</b> {row['Volume']:,.3f} m^3
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

m.save("traffic_points_cdmx.html")
m
#%%

pts.to_csv('sample_points_cdmx.csv')

#%%