"""Turn plan results into a prioritized list of alerts, each with a suggested action."""

from __future__ import annotations

import pandas as pd

from longrange.months import label

SEVERITY_ORDER = {"Critical": 0, "Warning": 1, "Info": 2}
COLUMNS = ["severity", "category", "ref", "month", "message", "suggested_action"]


def build_alerts(*, items, inventory, load, planned_orders, action_messages, forecast_bridge, attainment_by_month,
                 safety, issues, settings, events=None, event_impact=None, bias_summary=None, stockouts=None) -> pd.DataFrame:
    a: list[dict] = []

    def add(sev, cat, ref, month, msg, act):
        a.append(dict(zip(COLUMNS, [sev, cat, ref, month, msg, act], strict=True)))

    names = dict(zip(items["item_id"], items["description"], strict=False))
    fg = set(items.loc[items["item_type"] == "FG", "item_id"])

    # Shortages and safety stock, first month per item only
    for item, g in inventory.groupby("item_id", sort=False):
        short = g[g["status"] == "Shortage"]
        if not short.empty:
            m = short.iloc[0]["month"]
            add("Critical", "Shortage", item, m, f"{item} {names.get(item, '')}: projected stock is negative in {label(m)} ({short.iloc[0]['projected_available']:,.0f}).",
                "Expedite supply, firm an earlier order, or agree an allocation with Commercial.")
            continue
        low = g[g["status"] == "Below safety stock"]
        if not low.empty:
            m = low.iloc[0]["month"]
            add("Warning", "Safety stock", item, m, f"{item}: projected stock falls below safety stock in {label(m)}.",
                "Check lead time and lot size; consider pulling the next order in.")

    # Orders that should already have been released
    if not planned_orders.empty:
        late = planned_orders[planned_orders["release_in_past"]]
        for item, g in late.groupby("item_id"):
            add("Critical", "Late release", item, g["due_month"].iloc[0],
                f"{item}: {len(g)} planned order(s) needed by {label(g['due_month'].iloc[0])} should have been released already (lead time too long).",
                "Expedite, use a faster source, or accept a later date.")
        now = planned_orders[(planned_orders["zone"] == "Frozen") & ~planned_orders["release_in_past"]]
        if not now.empty:
            add("Info", "Release now", f"{len(now)} orders", now["release_month"].min(),
                f"{len(now)} new planned orders start inside the frozen zone ({settings.frozen_months} months).",
                "Review and firm them this cycle.")

    # Capacity
    for r in load.itertuples():
        if r.load_pct > settings.capacity_critical_pct:
            add("Critical", "Capacity", r.work_center, r.month,
                f"{r.work_center} {r.name} is at {r.load_pct:.0f}% in {label(r.month)} ({-r.spare_hours:,.0f} hours short).",
                "Pull ahead, move items to another line, add a shift, or outsource.")
        elif r.load_pct >= settings.capacity_warning_pct:
            add("Warning", "Capacity", r.work_center, r.month,
                f"{r.work_center} {r.name} is at {r.load_pct:.0f}% in {label(r.month)}.", "Watch closely; little room for upside.")

    # E&O risk (finished goods and others), first month per item
    for item, g in inventory.groupby("item_id", sort=False):
        eo = g[g["status"].isin(["E&O risk", "No demand"])]
        if not eo.empty:
            r = eo.iloc[0]
            woc = "no demand ahead" if r["status"] == "No demand" else f"{r['weeks_of_coverage']:.0f} weeks of coverage vs {r['coverage_limit_weeks']:.0f}-week limit"
            add("Warning", "E&O risk", item, r["month"], f"{item} {names.get(item, '')}: {woc} in {label(r['month'])}.",
                "Stop or reduce supply, and plan a sell-through or rework with Commercial and Finance.")

    # Existing orders the plan suggests changing
    for r in action_messages.itertuples():
        sev = "Info" if r.action.startswith("Review") else "Warning"
        add(sev, "Order change", r.item_id, r.month,
            f"{r.action} {r.order_id} ({r.item_id}): {r.current_qty:,.0f} → {r.suggested_qty:,.0f}. {r.reason}",
            "Confirm with Production and Supply Planning before changing.")

    # Forecast changes
    if forecast_bridge is not None and not forecast_bridge.empty:
        for r in forecast_bridge.itertuples():
            if pd.notna(r.change_pct) and abs(r.change_pct) >= settings.forecast_change_alert_pct:
                add("Info", "Forecast change", r.item_id, "",
                    f"{r.item_id}: forecast {'up' if r.change > 0 else 'down'} {abs(r.change_pct):.0f}% vs previous version ({r.change:+,.0f}).",
                    "Ask Demand Planning for the reason; explain it in the S&OP bridge.")

    # Demand events
    if events is not None and not events.empty:
        for r in events.itertuples():
            note = f" ({r.note})" if r.note else ""
            if r.applied and r.in_frozen_zone:
                add("Warning", "Event", r.event_id, r.first_month,
                    f"{r.event_id} {r.event_type}{note} starts in {label(r.first_month)}, inside the frozen zone: "
                    f"{r.units:+,.0f} units on orders that are already firm.",
                    "Check that firm orders and stock cover it, or agree a later start with Marketing.")
            if r.applied and str(r.event_type).lower() == "delist" and event_impact is not None:
                its = event_impact.loc[event_impact["event_id"] == r.event_id, "item_id"].unique()
                for item in its:
                    inv = inventory[(inventory["item_id"] == item) & (inventory["month"] == r.first_month)]
                    if inv.empty or inv.iloc[0]["projected_available"] <= 0:
                        continue
                    left = inv.iloc[0]
                    add("Warning", "Event", r.event_id, r.first_month,
                        f"{r.event_id} delists {item} {names.get(item, '')} from {label(r.first_month)} with "
                        f"{left['projected_available']:,.0f} units (${left['inventory_value']:,.0f}) still projected in stock.",
                        "Cancel or reduce open orders, sell through before the date, or plan the write-off with Finance.")
            elif not r.applied and str(r.status).lower() == "proposed":
                add("Info", "Event", r.event_id, r.first_month,
                    f"Proposed {r.event_type} {r.event_id}{note}: {r.units:+,.0f} units from {label(r.first_month)}, not in the plan yet.",
                    "Tick 'Include proposed events' in the what-if to see the supply impact before S&OP decides.")

    # Forecast bias (lag 1)
    if bias_summary is not None and not bias_summary.empty:
        for r in bias_summary[bias_summary["flag"]].itertuples():
            act = ("Ask Demand Planning to re-base the forecast to recent actuals; the plan is building too much stock."
                   if r.bias > 0 else
                   "Ask Demand Planning whether demand has stepped up; check for stock-outs that hid demand.")
            add("Warning", "Forecast bias", r.item_id, "",
                f"{r.item_id} {names.get(r.item_id, '')}: {r.direction} by {r.bias:+.0%} over the last {r.months} months "
                f"(lag 1, limit ±{settings.bias_alert_pct:.0f}%).", act)

    # Stock-outs in sales history
    if stockouts is not None and not stockouts.empty:
        for r in stockouts.itertuples():
            if r.capped:
                add("Warning", "Stock-out", r.item_id, r.month,
                    f"{r.item_id} {names.get(r.item_id, '')}: out of stock {r.stockout_days:.0f} of {r.days_in_month} days in "
                    f"{label(r.month)}; demand estimate capped at {r.estimated_qty:,.0f} (recorded {r.recorded_qty:,.0f}).",
                    "Too few selling days for a reliable rate: enter a manual demand estimate with Demand Planning.")
            else:
                add("Info", "Stock-out", r.item_id, r.month,
                    f"{r.item_id} {names.get(r.item_id, '')}: out of stock {r.stockout_days:.0f} days in {label(r.month)}. "
                    f"Demand estimated at {r.estimated_qty:,.0f} vs {r.recorded_qty:,.0f} sold (about {r.lost_qty:,.0f} lost).",
                    "Planning, the baseline and bias use the estimate. Find the supply cause so it does not repeat.")

    # Attainment
    if attainment_by_month is not None and not attainment_by_month.empty:
        last = attainment_by_month.sort_values("month").iloc[-1]
        if pd.notna(last["absolute_attainment_pct"]) and last["absolute_attainment_pct"] < settings.attainment_target_pct:
            add("Warning", "Attainment", "Production", last["month"],
                f"Absolute attainment was {last['absolute_attainment_pct']:.1f}% in {label(last['month'])} (target {settings.attainment_target_pct:.0f}%).",
                "Find the items behind the miss and check run rates and material availability.")

    # Data and setup
    for item in safety.loc[safety["method"].str.startswith("None"), "item_id"]:
        if item in fg:
            add("Info", "Data", item, "", f"{item}: no safety stock and not enough history to calculate one.",
                "Enter safety_stock or a service level and sales history.")
    for msg in issues:
        add("Warning", "Data", "", "", msg, "Fix in the source data.")

    df = pd.DataFrame(a, columns=COLUMNS)
    if df.empty:
        return df
    df["_s"] = df["severity"].map(SEVERITY_ORDER)
    df["_m"] = df["month"].replace("", "9999-99")
    return df.sort_values(["_s", "_m", "category"]).drop(columns=["_s", "_m"]).reset_index(drop=True)
