"""Inventory health: projected stock, weeks of coverage, value and E&O risk."""

from __future__ import annotations

import numpy as np
import pandas as pd


def inventory_health(time_phased: pd.DataFrame, items: pd.DataFrame, weeks_per_month: float,
                     eo_share: float, max_weeks: float, lookahead: int = 3) -> pd.DataFrame:
    """One row per item and month.

    Weeks of coverage = projected available / average weekly gross requirement of the next
    ``lookahead`` months. The E&O limit is ``eo_share`` of shelf life, or ``max_weeks`` for
    items without shelf life.
    """
    it = items.set_index("item_id")
    rows = []
    for item, g in time_phased.groupby("item_id", sort=False):
        g = g.reset_index(drop=True)
        gross = g["gross_requirement"].to_numpy(float)
        pab = g["projected_available"].to_numpy(float)
        shelf = float(it.at[item, "shelf_life_months"] or 0)
        limit = shelf * weeks_per_month * eo_share if shelf > 0 else max_weeks
        cost = float(it.at[item, "unit_cost"] or 0)
        for m in range(len(g)):
            fut = gross[m + 1:m + 1 + lookahead]
            full_view = len(fut) == lookahead   # near the horizon end, demand beyond it is unknown
            weekly = fut.mean() / weeks_per_month if len(fut) else gross[m] / weeks_per_month
            woc = pab[m] / weekly if weekly > 0 else (np.inf if pab[m] > 0 else 0.0)
            if not full_view:
                woc = np.nan if weekly == 0 else woc
            status = "Shortage" if pab[m] < 0 else "Below safety stock" if pab[m] < g.at[m, "safety_stock"] - 1e-6 \
                else "Healthy" if not full_view \
                else "No demand" if weekly == 0 and pab[m] > 0 else "E&O risk" if woc > limit else "Healthy"
            rows.append({"item_id": item, "month": g.at[m, "month"], "projected_available": pab[m],
                         "safety_stock": g.at[m, "safety_stock"], "weeks_of_coverage": woc, "coverage_limit_weeks": limit,
                         "inventory_value": max(pab[m], 0) * cost, "status": status})
    return pd.DataFrame(rows)
