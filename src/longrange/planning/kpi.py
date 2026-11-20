"""Planning KPIs: plan attainment and capacity utilization."""

from __future__ import annotations

import numpy as np
import pandas as pd


def attainment(actuals: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Net attainment = sum actual / sum plan; absolute = sum min(actual, plan) / sum plan.

    Returns (by month, by item). Absolute gives no credit for over-producing one item
    to cover another's shortfall, so it exposes mix misses.
    """
    cols = ["planned_qty", "actual_qty", "capped_actual", "net_attainment_pct", "absolute_attainment_pct"]
    if actuals.empty:
        return pd.DataFrame(columns=["month", *cols]), pd.DataFrame(columns=["item_id", *cols])
    a = actuals.copy()
    a["capped_actual"] = np.minimum(a["actual_qty"], a["planned_qty"])

    def agg(df, key):
        g = df.groupby(key, as_index=False)[["planned_qty", "actual_qty", "capped_actual"]].sum()
        g["net_attainment_pct"] = g["actual_qty"] / g["planned_qty"].where(g["planned_qty"] > 0) * 100
        g["absolute_attainment_pct"] = g["capped_actual"] / g["planned_qty"].where(g["planned_qty"] > 0) * 100
        return g

    return agg(a, "month"), agg(a, "item_id")


def utilization_summary(load: pd.DataFrame, warn: float, crit: float) -> pd.DataFrame:
    if load.empty:
        return pd.DataFrame(columns=["work_center", "name", "avg_load_pct", "peak_load_pct", "peak_month",
                                     "months_over_warning", "months_over_critical"])
    rows = []
    for wc, g in load.groupby("work_center", sort=False):
        peak = g.loc[g["load_pct"].idxmax()]
        rows.append({"work_center": wc, "name": g["name"].iloc[0], "avg_load_pct": g["load_pct"].mean(),
                     "peak_load_pct": peak["load_pct"], "peak_month": peak["month"],
                     "months_over_warning": int((g["load_pct"] >= warn).sum()),
                     "months_over_critical": int((g["load_pct"] > crit).sum())})
    return pd.DataFrame(rows)
