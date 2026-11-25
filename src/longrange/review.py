"""Cross-functional supply review: an agenda for each function, built from the plan, the order book and the
data-health checks, so the meeting discusses decisions rather than numbers."""

from __future__ import annotations

import pandas as pd

from longrange.months import label

GROUPS = ["Manufacturing", "Procurement", "Logistics", "Customer service", "Business management", "Supply chain"]
COLUMNS = ["group", "topic", "detail", "decision_needed", "ref"]


def supply_review(r, orders=None, health=None) -> pd.DataFrame:
    rows: list[dict] = []
    s = r.settings

    def add(g, topic, detail, ask, ref=""):
        rows.append(dict(zip(COLUMNS, [g, topic, detail, ask, ref], strict=True)))

    al = r.alerts
    cap = r.capacity
    # Manufacturing
    hot = cap[cap["load_pct"] > s.capacity_warning_pct].sort_values("month").head(5) if len(cap) else cap
    for x in hot.itertuples():
        add("Manufacturing", f"{x.work_center} at {x.load_pct:.0f}% in {label(x.month)}",
            f"{x.required_hours:,.0f} h needed vs {x.available_hours:,.0f} h available",
            "Extra shift, pre-build in an earlier month, move items to another line, or outsource?", x.work_center)
    am = r.action_messages
    for x in am[am["action"].str.startswith("Review")].itertuples() if len(am) else []:
        add("Manufacturing", f"Frozen order {x.order_id} ({x.item_id})", x.reason, "Keep the order or change it, and who absorbs the cost?",
            x.order_id)
    att = al[al["category"] == "Attainment"] if len(al) else al
    for x in att.itertuples():
        add("Manufacturing", "Plan attainment", x.message, "What stopped production, and the recovery plan?", x.ref)

    # Procurement
    for x in al[al["category"].isin(["Late release", "Release now"])].itertuples() if len(al) else []:
        add("Procurement", f"{x.category}: {x.ref}", x.message, x.suggested_action, x.ref)
    buys = set(r.items.loc[r.items["replenishment"] == "buy", "item_id"])
    for x in al[(al["category"] == "Shortage") & al["ref"].isin(buys)].itertuples() if len(al) else []:
        add("Procurement", f"Shortage {x.ref}", x.message, x.suggested_action, x.ref)

    # Logistics: what must ship, and contract-manufactured supply due in
    if orders is not None:
        op = orders.open_lines
        soon = op[(op["confirmed_date"].fillna(op["requested_date"]) <= orders.as_of + pd.Timedelta(days=14))]
        if len(soon):
            by = soon.groupby("customer")["open_qty"].sum().sort_values(ascending=False)
            add("Logistics", f"Ship in the next 14 days: {len(soon)} lines, {soon['open_qty'].sum():,.0f} units",
                ", ".join(f"{c} {q:,.0f}" for c, q in by.items()), "Trucks and dock slots booked? Any carrier constraints?")
    so = r.supply
    cm = so[(so["order_type"] == "purchase") & so["item_id"].isin(set(r.items.loc[r.items["item_type"] == "FG", "item_id"]))
            & (so["due_index"] <= 1)] if len(so) else so
    for x in cm.itertuples() if len(cm) else []:
        add("Logistics", f"Inbound finished goods {x.item_id}", f"{x.qty:,.0f} units due {label(r.months[int(x.due_index)])} ({x.source})",
            "Confirm pickup and arrival with the contract manufacturer.", x.source)

    # Customer service
    if orders is not None:
        k = orders.kpis
        op = orders.open_lines
        for x in op[op["at_risk"]].itertuples():
            add("Customer service", f"At risk: {x.order_id} {x.customer}",
                f"{x.item_id} {x.open_qty:,.0f} confirmed {x.confirmed_date:%d %b}; on firm supply it can ship "
                f"{label(x.promise_month) if x.promise_month else 'after the horizon'}",
                x.action, x.order_id)
        pd_ = op[op["past_due"]]
        if len(pd_):
            add("Customer service", f"Past-due backlog: {len(pd_)} lines", f"{k['past_due_value']:,.0f} in value; oldest "
                f"{int(pd_['days_past_due'].max())} days", "Ship, re-date or cancel each line this week.")
        bc = orders.by_customer
        low = bc[bc["otif_confirmed_pct"] < s.otif_target_pct].sort_values("otif_confirmed_pct").head(3) if len(bc) else bc
        for x in low.itertuples():
            add("Customer service", f"OTIF {x.customer} {x.otif_confirmed_pct:.0f}%",
                f"{s.otif_months}-month OTIF vs confirmed date; target {s.otif_target_pct:.0f}%", "Root cause and recovery plan for this customer?",
                x.customer)

    # Business management
    S = r.summary()
    add("Business management", "Inventory value", f"{S['inventory_value_start']:,.0f} now, {S['inventory_value_end']:,.0f} at the end "
        f"of the horizon; {S['eo_risk_items']} items with E&O risk", "Agree the inventory target and the E&O actions.")
    for x in al[al["category"].isin(["Forecast change", "Forecast bias", "Baseline gap"])].itertuples() if len(al) else []:
        add("Business management", f"{x.category}: {x.ref}", x.message, "Accept the forecast, or send it back to Demand Planning?", x.ref)
    for x in al[al["category"] == "Event"].itertuples() if len(al) else []:
        add("Business management", f"Proposed event {x.ref}", x.message, "Approve, move or reject?", x.ref)

    # Supply chain (planning integrity)
    if health is not None:
        hdf, hk = health
        add("Supply chain", f"Planning data health {hk['score']:.0f}%", f"{hk['passed']} of {hk['checks']} checks pass; "
            f"{hk['records']} records to fix", "Owners and dates for each failed check.")
        for x in hdf[(hdf["status"] == "Fix") & (hdf["severity"] == "High")].itertuples():
            add("Supply chain", f"{x.check_id} {x.check}", f"{x.records} records: {x.examples}", x.fix, x.check_id)
    return pd.DataFrame(rows, columns=COLUMNS)


def agenda_markdown(agenda: pd.DataFrame, title: str) -> str:
    out = [f"# {title}"]
    for g in [g for g in GROUPS if g in set(agenda["group"])]:
        out.append(f"\n## {g}\n")
        for x in agenda[agenda["group"] == g].itertuples():
            out.append(f"- **{x.topic}**: {x.detail}. *Decision:* {x.decision_needed}")
    return "\n".join(out)
