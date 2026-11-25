"""Rough-cut capacity: hours required vs hours available per work center and month.

The planning run assumes infinite capacity (as ERP planning worksheets do), so this
check shows where the plan is not feasible and which items drive each overload.
"""

from __future__ import annotations

import pandas as pd


def available_hours(work_centers: pd.DataFrame, calendar: pd.DataFrame, months: list[str],
                    shifts_override: dict[str, float] | None = None,
                    efficiency_override: dict[str, float] | None = None) -> pd.DataFrame:
    shifts_override = shifts_override or {}
    efficiency_override = efficiency_override or {}
    cal = {(r.work_center, r.month): r.working_days for r in calendar.itertuples()} if not calendar.empty else {}
    rows = []
    for wc in work_centers.itertuples():
        shifts = float(shifts_override.get(wc.work_center, wc.shifts))
        eff = float(efficiency_override.get(wc.work_center, wc.efficiency_pct))
        for m in months:
            days = float(cal.get((wc.work_center, m), wc.working_days_per_month))
            rows.append({"work_center": wc.work_center, "name": wc.name, "month": m, "shifts": shifts,
                         "working_days": days, "efficiency_pct": eff,
                         "available_hours": shifts * float(wc.hours_per_shift) * days * eff / 100})
    return pd.DataFrame(rows)


def pick_routings(routings: pd.DataFrame, routing_override: dict[str, str] | None = None) -> pd.DataFrame:
    """One routing per item: the override's work center if given, else the lowest priority number."""
    if routings.empty:
        return routings
    r = routings.sort_values(["item_id", "priority"])
    chosen = r.groupby("item_id").head(1).set_index("item_id")
    for item, wc in (routing_override or {}).items():
        alt = r[(r["item_id"] == item) & (r["work_center"] == wc)]
        if not alt.empty:
            chosen.loc[item] = alt.iloc[0].drop("item_id")
    return chosen.reset_index()


def capacity_load(supply: pd.DataFrame, routings: pd.DataFrame, avail: pd.DataFrame, months: list[str],
                  routing_override: dict[str, str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (load by work center and month, detail by item and order)."""
    chosen = pick_routings(routings, routing_override)
    detail = []
    if not chosen.empty and not supply.empty:
        prod = supply[supply["order_type"] == "production"].merge(chosen, on="item_id", how="inner")
        for r in prod.itertuples():
            idx = min(max(int(r.start_index), 0), len(months) - 1)
            hours = float(r.qty) / float(r.units_per_hour) + float(r.setup_hours or 0)
            detail.append({"work_center": r.work_center, "month": months[idx], "item_id": r.item_id,
                           "source": r.source, "status": r.status, "qty": float(r.qty), "hours": hours})
    det = pd.DataFrame(detail, columns=["work_center", "month", "item_id", "source", "status", "qty", "hours"])
    req = det.groupby(["work_center", "month"], as_index=False)["hours"].sum().rename(columns={"hours": "required_hours"})
    load = avail.merge(req, on=["work_center", "month"], how="left")
    load["required_hours"] = pd.to_numeric(load["required_hours"], errors="coerce").fillna(0.0).astype(float)
    load["load_pct"] = (load["required_hours"] / load["available_hours"].where(load["available_hours"] > 0) * 100).fillna(0)
    load["spare_hours"] = load["available_hours"] - load["required_hours"]
    return load, det
