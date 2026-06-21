#%%
"""
Strategy comparison: Government (random trips) vs Optimised (weight-ordered superclusters).

Government
----------
  Randomly shuffles all potholes, fills trips of up to 5, stops at $500k.
  Selection already computed in run_government_strategy.py and saved to
  outputs/gov_enriched_points.csv.

Optimised
---------
  Sorts superclusters by total_weight descending (highest traffic-impact first)
  and greedily selects them until the remaining discontent is <= the government
  remaining discontent.  Reports how much that costs vs the government.

Discontent per point = currentSpeed (velocity) x vehicles/week (flow) x volume (m^3)
"""

import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
TESTS_DIR = HERE.parent
OUTPUTS_DIR = TESTS_DIR / "outputs"

# Must match run_government_strategy.py
VOLUME_COST = 8_000
TRIP_COST = 2_000
POTHOLES_PER_TRIP = 5
BUDGET = 500_000
MAX_MISSES = 50
SEED = 42


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_gov_results(seed: int = SEED) -> tuple[pd.DataFrame, float, int]:
    """
    Re-run the government selection on gov_enriched_points.csv so we get the
    exact cost and trip count without calling the API again.
    """
    sys.path.insert(0, str(HERE))
    from run_government_strategy import _run_selection

    df = pd.read_csv(OUTPUTS_DIR / "gov_enriched_points.csv")

    selected_idx, total_cost, n_trips = _run_selection(df, seed=seed)
    df["repaired"] = 1
    df.loc[selected_idx, "repaired"] = 0

    return df, total_cost, n_trips


def _load_optimised_points() -> pd.DataFrame:
    """
    Load step_03_superclusters.csv which already contains current_speed and
    vehicles_week as plain columns — no cache file or JSON parsing needed.
    """
    df = pd.read_csv(OUTPUTS_DIR / "step_03_superclusters.csv")
    df["discontent"] = df["current_speed"] * df["vehicles_week"] * df["volume"]
    return df


def _build_supercluster_table(opt_df: pd.DataFrame) -> pd.DataFrame:
    """
    One row per supercluster with weight, cost, and its share of total
    discontent. Sorted by total_weight descending.
    """
    sc_df = (
        opt_df.groupby("supercluster_id")
        .agg(
            total_weight=("total_weight", "first"),
            cost=("cost", "first"),
            sc_discontent=("discontent", "sum"),
            n_points=("volume", "count"),
        )
        .sort_values("total_weight", ascending=False)
        .reset_index()
    )

    # Cumulative cost (top-N superclusters selected in weight order)
    sc_df["cum_cost"] = sc_df["cost"].cumsum()

    # Cumulative discontent AVOIDED (sum of top-N superclusters' discontent)
    sc_df["cum_discontent_avoided"] = sc_df["sc_discontent"].cumsum()

    # Remaining discontent if we take the top-N (reverse cumsum)
    total_discontent = opt_df["discontent"].sum()
    sc_df["remaining_discontent"] = total_discontent - sc_df["cum_discontent_avoided"]

    return sc_df


def _find_optimised_cutoff(
    sc_df: pd.DataFrame, gov_remaining: float
) -> tuple[pd.DataFrame, float, float]:
    """
    Return the rows of sc_df that need to be selected to reach remaining
    discontent <= gov_remaining, plus the cost and actual remaining discontent.
    """
    mask = sc_df["remaining_discontent"] <= gov_remaining
    if not mask.any():
        # Need all superclusters
        selected = sc_df
    else:
        cutoff = mask.idxmax()          # first index where condition is met
        selected = sc_df.loc[:cutoff]

    opt_cost = selected["cost"].sum()
    opt_remaining = sc_df.loc[selected.index[-1], "remaining_discontent"]
    return selected, opt_cost, opt_remaining


# ── Main ──────────────────────────────────────────────────────────────────────

def compare_gov_vs_optimized(seed: int = SEED) -> dict:
    print("Loading government results ...")
    gov_df, gov_cost, gov_n_trips = _load_gov_results(seed=seed)

    baseline          = gov_df["discontent"].sum()
    gov_remaining     = gov_df.loc[gov_df["repaired"] == 1, "discontent"].sum()
    gov_avoided       = baseline - gov_remaining
    gov_n_repaired    = int((gov_df["repaired"] == 0).sum())

    print("Loading optimised results ...")
    opt_df = _load_optimised_points()
    sc_df  = _build_supercluster_table(opt_df)

    selected_scs, opt_cost, opt_remaining = _find_optimised_cutoff(sc_df, gov_remaining)
    opt_avoided    = baseline - opt_remaining
    opt_n_scs      = len(selected_scs)
    opt_n_repaired = int(opt_df["supercluster_id"].isin(selected_scs["supercluster_id"]).sum())

    cost_savings   = gov_cost - opt_cost
    savings_pct    = cost_savings / gov_cost

    # ── Print comparison table ────────────────────────────────────────────────
    W = 62
    print()
    print("=" * W)
    print(f"{'STRATEGY COMPARISON':^{W}}")
    print("=" * W)
    print(f"{'Metric':<36} {'Government':>12} {'Optimised':>12}")
    print("-" * W)
    print(f"{'Baseline discontent':<36} {baseline:>24,.0f}")
    print(f"{'Discontent avoided':<36} {gov_avoided:>12,.0f} {opt_avoided:>12,.0f}")
    print(f"{'Discontent avoided (%)':<36} {gov_avoided/baseline:>11.1%} {opt_avoided/baseline:>11.1%}")
    print(f"{'Remaining discontent':<36} {gov_remaining:>12,.0f} {opt_remaining:>12,.0f}")
    print("-" * W)
    print(f"{'Total cost ($)':<36} {gov_cost:>12,.0f} {opt_cost:>12,.0f}")
    print(f"{'Cost savings vs government ($)':<36} {'':>12} {cost_savings:>12,.0f}")
    print(f"{'Cost savings vs government (%)':<36} {'':>12} {savings_pct:>11.1%}")
    print("-" * W)
    print(f"{'Holes / points repaired':<36} {gov_n_repaired:>12,} {opt_n_repaired:>12,}")
    print(f"{'Trips / superclusters used':<36} {gov_n_trips:>12,} {opt_n_scs:>12,}")
    print("=" * W)

    # ── Save supercluster selection table ─────────────────────────────────────
    out = sc_df.copy()
    out["selected"] = out["supercluster_id"].isin(selected_scs["supercluster_id"])
    out.to_csv(OUTPUTS_DIR / "comparison_sc_table.csv", index=False)
    print(f"\nSupercluster table -> outputs/comparison_sc_table.csv")

    return {
        "baseline":           baseline,
        "gov_remaining":      gov_remaining,
        "gov_cost":           gov_cost,
        "gov_n_trips":        gov_n_trips,
        "opt_remaining":      opt_remaining,
        "opt_cost":           opt_cost,
        "opt_n_superclusters": opt_n_scs,
        "cost_savings":       cost_savings,
        "savings_pct":        savings_pct,
    }

def run_simulations(n: int = 30) -> pd.DataFrame:
    """
    Run the government strategy with n different random seeds (0..n-1) and
    compare each against the fixed optimised strategy.  Prints per-run rows
    and a summary of averages.

    Returns a DataFrame with one row per simulation.
    """
    # Compute optimised metrics once — they don't depend on the random seed.
    opt_df = _load_optimised_points()
    opt_df_baseline = opt_df["discontent"].sum()

    rows = []
    print(f"Running {n} simulations ...\n")
    print(f"{'Seed':>4}  {'Gov cost':>10}  {'Opt cost':>10}  {'Savings %':>9}  "
          f"{'Gov disc %':>10}  {'Opt disc %':>10}")
    print("-" * 62)

    for seed in range(n):
        gov_df, gov_cost, gov_n_trips = _load_gov_results(seed=seed)

        baseline      = gov_df["discontent"].sum()
        gov_remaining = gov_df.loc[gov_df["repaired"] == 1, "discontent"].sum()
        gov_avoided   = baseline - gov_remaining
        gov_n_rep     = int((gov_df["repaired"] == 0).sum())

        sc_df = _build_supercluster_table(opt_df)
        selected_scs, opt_cost, opt_remaining = _find_optimised_cutoff(sc_df, gov_remaining)
        opt_avoided  = baseline - opt_remaining
        opt_n_rep    = int(opt_df["supercluster_id"].isin(selected_scs["supercluster_id"]).sum())

        savings_pct  = (gov_cost - opt_cost) / gov_cost

        print(f"{seed:>4}  {gov_cost:>10,.0f}  {opt_cost:>10,.0f}  "
              f"{savings_pct:>9.1%}  {gov_avoided/baseline:>10.1%}  "
              f"{opt_avoided/baseline:>10.1%}")

        rows.append({
            "seed":             seed,
            "gov_cost":         gov_cost,
            "gov_n_trips":      gov_n_trips,
            "gov_n_repaired":   gov_n_rep,
            "gov_avoided_pct":  gov_avoided / baseline,
            "opt_cost":         opt_cost,
            "opt_n_scs":        len(selected_scs),
            "opt_n_repaired":   opt_n_rep,
            "opt_avoided_pct":  opt_avoided / baseline,
            "cost_savings":     gov_cost - opt_cost,
            "savings_pct":      savings_pct,
        })

    results = pd.DataFrame(rows)

    W = 62
    print()
    print("=" * W)
    print(f"{'SIMULATION AVERAGES  (n=' + str(n) + ')':^{W}}")
    print("=" * W)
    print(f"{'Metric':<38} {'Government':>11} {'Optimised':>11}")
    print("-" * W)
    print(f"{'Avg cost ($)':<38} {results['gov_cost'].mean():>11,.0f} "
          f"{results['opt_cost'].mean():>11,.0f}")
    print(f"{'Avg discontent avoided (%)':<38} "
          f"{results['gov_avoided_pct'].mean():>10.1%} "
          f"{results['opt_avoided_pct'].mean():>10.1%}")
    print(f"{'Avg cost savings ($)':<38} {'':>11} "
          f"{results['cost_savings'].mean():>11,.0f}")
    print(f"{'Avg cost savings (%)':<38} {'':>11} "
          f"{results['savings_pct'].mean():>10.1%}")
    print(f"{'Avg holes / superclusters used':<38} "
          f"{results['gov_n_repaired'].mean():>11.0f} "
          f"{results['opt_n_repaired'].mean():>11.0f}")
    print("=" * W)

    results.to_csv(OUTPUTS_DIR / "simulation_results.csv", index=False)
    print(f"\nPer-simulation results -> outputs/simulation_results.csv")

    return results


if __name__ == "__main__":
    run_simulations(30)

# %%
