"""Stock-out correction: estimate true demand in months when an item was out of stock.

When an item is out of stock, recorded sales understate demand. Planning on them teaches
the forecast and the safety stock a false low. For a month with ``stockout_days`` the
planner estimates demand at the rate it sold on the days it was available:

    estimated demand = recorded qty x days in month / (days in month - stockout days)

The uplift is capped (``max_uplift``, default 3x): with most of the month out of stock the
rate is too uncertain, and the month is flagged for a manual estimate instead.
"""

from __future__ import annotations

import calendar

import pandas as pd

COLUMNS = ["item_id", "month", "recorded_qty", "stockout_days", "days_in_month", "estimated_qty", "lost_qty", "capped"]


def days_in_month(month: str) -> int:
    y, m = int(month[:4]), int(month[5:7])
    return calendar.monthrange(y, m)[1]


def correct_history(history: pd.DataFrame, max_uplift: float = 3.0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (history with qty replaced by estimated demand, one row per corrected month)."""
    if history.empty or "stockout_days" not in history.columns:
        return history, pd.DataFrame(columns=COLUMNS)
    h = history.copy()
    out = pd.to_numeric(h["stockout_days"], errors="coerce").fillna(0)
    rows = []
    for i in h.index[out > 0]:
        m, rec = h.at[i, "month"], float(h.at[i, "qty"])
        dim = days_in_month(m)
        d = min(float(out[i]), dim)
        factor = dim / (dim - d) if d < dim else float("inf")
        capped = factor > max_uplift
        est = rec * min(factor, max_uplift)
        h.at[i, "qty"] = est
        rows.append([h.at[i, "item_id"], m, rec, d, dim, round(est), round(est - rec), capped])
    return h, pd.DataFrame(rows, columns=COLUMNS)
