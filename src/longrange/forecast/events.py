"""Demand events: promotions, launches and delistings laid on top of the forecast.

The consensus forecast is the baseline. Events are kept separately so the plan can
show what each one adds, and so proposed events can be tried as a what-if before
S&OP approves them.

Per affected month:  forecast with event = baseline x (1 + lift_pct / 100) + extra_qty  (never below 0).
"""

from __future__ import annotations

import pandas as pd

from longrange.months import months_between

IMPACT_COLUMNS = ["event_id", "event_type", "status", "applied", "item_id", "month", "baseline_qty", "event_qty",
                  "note"]


def _months_for(ev, months: list[str]) -> list[str]:
    start = ev["start_month"]
    end = ev.get("end_month")
    if end is None or (isinstance(end, float) and pd.isna(end)) or str(end).strip() == "":
        end = months[-1] if str(ev.get("event_type", "")).lower() == "delist" else start
    return [m for m in months if start <= m <= end]


def is_applied(ev, include_proposed: bool, excluded: set[str]) -> bool:
    if ev["event_id"] in excluded:
        return False
    status = str(ev.get("status") or "approved").strip().lower()
    return status != "proposed" or include_proposed


def apply_events(forecast: pd.DataFrame, events: pd.DataFrame, fg_items: list[str], months: list[str],
                 include_proposed: bool = False, excluded: list[str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (forecast with applied events, impact table for every event).

    ``forecast`` has item_id, month, qty for one version. The impact table lists every
    event and month, applied or not, so the planner can see what a proposed event would add.
    """
    fc = forecast[["item_id", "month", "qty"]].copy()
    if events is None or events.empty:
        return fc, pd.DataFrame(columns=IMPACT_COLUMNS)
    excluded_set = set(excluded or [])
    base = fc.groupby(["item_id", "month"])["qty"].sum()
    current = base.to_dict()
    rows = []
    for _, ev in events.iterrows():
        items = fg_items if str(ev["item_id"]).strip().upper() == "ALL" else [ev["item_id"]]
        applied = is_applied(ev, include_proposed, excluded_set)
        lift = float(ev.get("lift_pct") or 0) / 100
        extra = float(ev.get("extra_qty") or 0)
        for item in items:
            for m in _months_for(ev, months):
                before = current.get((item, m), 0.0)
                after = max(before * (1 + lift) + extra, 0.0)
                rows.append([ev["event_id"], ev.get("event_type") or "other", ev.get("status") or "approved", applied,
                             item, m, before, after - before, ev.get("note") or ""])
                if applied:
                    current[(item, m)] = after
    impact = pd.DataFrame(rows, columns=IMPACT_COLUMNS)
    out = pd.DataFrame([(i, m, q) for (i, m), q in current.items()], columns=["item_id", "month", "qty"])
    return out, impact


def event_summary(impact: pd.DataFrame, months: list[str], frozen_months: int) -> pd.DataFrame:
    """One row per event: total units, months, and whether it starts inside the frozen zone."""
    cols = ["event_id", "event_type", "status", "applied", "items", "first_month", "last_month", "units",
            "in_frozen_zone", "note"]
    if impact.empty:
        return pd.DataFrame(columns=cols)
    g = impact.groupby("event_id", sort=False)
    out = pd.DataFrame({
        "event_type": g["event_type"].first(),
        "status": g["status"].first(),
        "applied": g["applied"].first(),
        "items": g["item_id"].nunique(),
        "first_month": g["month"].min(),
        "last_month": g["month"].max(),
        "units": g["event_qty"].sum().round(),
        "note": g["note"].first(),
    }).reset_index()
    out["in_frozen_zone"] = out["first_month"].map(lambda m: months_between(months[0], m) < frozen_months)
    return out[cols]
