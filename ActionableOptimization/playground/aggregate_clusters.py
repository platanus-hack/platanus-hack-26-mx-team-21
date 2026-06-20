import pandas as pd
from pathlib import Path

HERE = Path(__file__).parent


def main():
    df = pd.read_csv(HERE / "clustered_points.csv", index_col=0)

    aggregated = (
        df.groupby("cluster_id")
        .agg(
            street_name=("street_name", "first"),
            total_volume=("Volume", "sum"),
            num_points=("Volume", "count"),
            center_lat=("latitude", "mean"),
            center_lon=("longitude", "mean"),
        )
        .reset_index()
    )

    aggregated.to_csv(HERE / "cluster_summary.csv", index=False)

    print(f"Clusters aggregated : {len(aggregated)}")
    print(f"Total volume        : {aggregated['total_volume'].sum():.4f}")
    print()
    print(aggregated.sort_values("total_volume", ascending=False).head(10).to_string(index=False))
    print()
    print("Output written to cluster_summary.csv")


if __name__ == "__main__":
    main()
