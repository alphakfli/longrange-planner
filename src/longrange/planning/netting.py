"""MPS and MRP netting in monthly buckets.

Items are planned top-down by low-level code, so a parent's planned orders become
its components' dependent demand before the components are planned (the same
logic as an ERP planning worksheet's regenerative run).

For each item and month:
    gross requirement   = independent demand (larger of forecast and sales orders) + dependent demand
    projected available = previous + scheduled receipts + planned receipts - gross requirement
A planned order is created when projected available would fall below safety stock.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from longrange.months import months_between, weeks_to_months


@dataclass
class NettingResult:
    time_phased: pd.DataFrame
    planned_orders: pd.DataFrame
    action_messages: pd.DataFrame
    supply: pd.DataFrame          # every supply the plan relies on: existing (after actions) + planned
    issues: list[str] = field(default_factory=list)


def low_level_codes(items: list[str], bom: pd.DataFrame) -> tuple[dict[str, int], list[str]]:
    """Deepest level at which each item appears (0 = top). Returns (codes, cycle warnings)."""
    children: dict[str, list[str]] = {}
    for p, c in zip(bom["parent_item"], bom["component_item"], strict=False):
        children.setdefault(p, []).append(c)
    llc = dict.fromkeys(items, 0)
    issues: list[str] = []

    def visit(node: str, depth: int, path: tuple[str, ...]):
        if node in path:
            issues.append("BOM loop: " + " > ".join(path + (node,)))
            return
        if depth > llc.get(node, 0):
            llc[node] = depth
        for c in children.get(node, []):
            visit(c, depth + 1, path + (node,))

    for it in items:
        visit(it, 0, ())
    return llc, issues


def lot_size(need: float, min_qty: float, multiple: float) -> float:
    q = max(need, min_qty or 0)
    if multiple and multiple > 0:
        q = math.ceil(q / multiple - 1e-9) * multiple
    return float(q)


def zone(index: int, frozen: int, slushy: int) -> str:
    if index < frozen:
        return "Frozen"
    if index < slushy:
        return "Slushy"
    return "Liquid"


def run_netting(items: pd.DataFrame, bom: pd.DataFrame, independent: dict[str, np.ndarray],
                sales_orders: dict[str, np.ndarray], forecast: dict[str, np.ndarray],
                supply_orders: pd.DataFrame, safety: dict[str, float], months: list[str],
                frozen: int, slushy: int, weeks_per_month: float) -> NettingResult:
    H = len(months)
    start = months[0]
    it = items.set_index("item_id")
    ids = list(it.index)
    llc, issues = low_level_codes(ids, bom)
    comps = {p: g[["component_item", "qty_per", "scrap_pct"]].to_numpy().tolist() for p, g in bom.groupby("parent_item")}
    dep = {i: np.zeros(H) for i in ids}
    lt_months = {i: weeks_to_months(float(it.at[i, "lead_time_weeks"] or 0), weeks_per_month) for i in ids}

    # existing orders, bucketed
    orders = []
    for _, o in supply_orders.iterrows():
        if o["item_id"] not in it.index:
            continue
        d = months_between(start, o["due_month"])
        if d >= H:
            continue
        status = str(o.get("status") or "firm").lower()
        orders.append({"order_id": o["order_id"], "item_id": o["item_id"], "status": status,
                       "order_type": str(o.get("order_type") or "").lower() or ("production" if it.at[o["item_id"], "replenishment"] == "make" else "purchase"),
                       "due_index": max(d, 0), "past_due": d < 0, "qty": float(o["qty"]), "new_qty": float(o["qty"])})

    tp_rows, planned, actions, supply_rows = [], [], [], []
    seq = 1
    for item in sorted(ids, key=lambda i: (llc[i], i)):
        row = it.loc[item]
        ss = float(safety.get(item, 0) or 0)
        on_hand = float(row["on_hand"] or 0)
        minq, mult, maxq = float(row["min_order_qty"] or 0), float(row["order_multiple"] or 0), float(row["max_order_qty"] or 0)
        accum = max(1, int(row["lot_accum_months"] or 1))
        lt = lt_months[item]
        indep = independent.get(item, np.zeros(H))
        gross = indep + dep[item]
        mine = [o for o in orders if o["item_id"] == item]
        sched = np.zeros(H)
        for o in mine:
            sched[o["due_index"]] += o["qty"]

        # Pass 1: existing orders that are no longer needed.
        pab = on_hand + np.cumsum(sched - gross)
        for o in sorted([o for o in mine if o["status"] != "released"], key=lambda o: -o["due_index"]):
            d = o["due_index"]
            window = pab[d:min(H, d + accum)] - ss
            spare = float(window.min()) if len(window) else 0.0
            if spare <= 0:
                continue
            if d < frozen:
                if spare >= o["qty"]:
                    actions.append({"item_id": item, "order_id": o["order_id"], "month": months[d], "action": "Review (frozen)",
                                    "current_qty": o["qty"], "suggested_qty": o["qty"], "zone": "Frozen",
                                    "reason": "Not needed for demand, but inside the frozen zone: kept. Review at S&OP."})
                continue
            if spare >= o["qty"]:
                new_q = 0.0
            else:
                step = mult if mult > 0 else 1
                new_q = max(minq, o["qty"] - math.floor(spare / step) * step)
            if new_q < o["qty"]:
                actions.append({"item_id": item, "order_id": o["order_id"], "month": months[d],
                                "action": "Cancel" if new_q == 0 else "Reduce", "current_qty": o["qty"], "suggested_qty": new_q,
                                "zone": zone(d, frozen, slushy), "reason": "Demand fell; projected stock stays above safety stock without it."})
                sched[d] -= o["qty"] - new_q
                pab[d:] -= o["qty"] - new_q
                o["new_qty"] = new_q

        # Pass 2: new planned orders.
        receipts = np.zeros(H)
        releases = np.zeros(H)
        p = on_hand
        proj = np.zeros(H)
        for m in range(H):
            p += sched[m] - gross[m]
            if p < ss - 1e-9:
                need = ss - p
                for j in range(m + 1, min(H, m + accum)):
                    need += gross[j] - sched[j]
                need = max(need, ss - p)
                qty = lot_size(need, minq, mult)
                parts = []
                if maxq and maxq > 0 and qty > maxq:
                    while qty > 1e-9:
                        parts.append(min(qty, maxq))
                        qty -= parts[-1]
                else:
                    parts = [qty]
                for q in parts:
                    rel = m - lt
                    planned.append({"planned_id": f"PL-{seq:05d}", "item_id": item,
                                    "order_type": "production" if row["replenishment"] == "make" else "purchase",
                                    "release_month": months[max(rel, 0)], "due_month": months[m], "release_index": rel,
                                    "due_index": m, "qty": q, "zone": zone(max(rel, 0), frozen, slushy),
                                    "release_in_past": rel < 0, "vendor": row.get("vendor") or ""})
                    seq += 1
                    receipts[m] += q
                    releases[max(rel, 0)] += q
                    p += q
            proj[m] = p

        # Dependent demand for components, from this item's production supply.
        if row["replenishment"] == "make" and item in comps:
            sources = [(o["due_index"] - lt, o["new_qty"]) for o in mine if o["status"] != "released" and o["new_qty"] > 0]
            sources += [(m - lt, receipts[m]) for m in range(H) if receipts[m] > 0]
            for rel, q in sources:
                r = min(max(rel, 0), H - 1)
                for comp, qty_per, scrap in comps[item]:
                    if comp in dep:
                        dep[comp][r] += q * float(qty_per) * (1 + float(scrap or 0) / 100)

        for o in mine:
            if o["new_qty"] > 0:
                supply_rows.append({"source": o["order_id"], "item_id": item, "status": o["status"].title(),
                                    "order_type": o["order_type"], "start_index": max(o["due_index"] - lt, 0),
                                    "due_index": o["due_index"], "qty": o["new_qty"]})
        for pl in [x for x in planned if x["item_id"] == item]:
            supply_rows.append({"source": pl["planned_id"], "item_id": item, "status": "Planned (new)",
                                "order_type": pl["order_type"], "start_index": max(pl["release_index"], 0),
                                "due_index": pl["due_index"], "qty": pl["qty"]})

        so = sales_orders.get(item, np.zeros(H))
        fc = forecast.get(item, np.zeros(H))
        for m in range(H):
            tp_rows.append({"item_id": item, "month": months[m], "forecast": fc[m], "sales_orders": so[m],
                            "independent_demand": indep[m], "dependent_demand": dep[item][m], "gross_requirement": gross[m],
                            "scheduled_receipts": sched[m], "planned_receipts": receipts[m], "planned_releases": releases[m],
                            "projected_available": proj[m], "safety_stock": ss, "level": llc[item]})

    for o in orders:
        if o["past_due"]:
            issues.append(f"Order {o['order_id']} ({o['item_id']}) is past due; counted in {months[0]}.")
    tp = pd.DataFrame(tp_rows)
    po = pd.DataFrame(planned, columns=["planned_id", "item_id", "order_type", "release_month", "due_month", "release_index",
                                        "due_index", "qty", "zone", "release_in_past", "vendor"])
    am = pd.DataFrame(actions, columns=["item_id", "order_id", "month", "action", "current_qty", "suggested_qty", "zone", "reason"])
    sup = pd.DataFrame(supply_rows, columns=["source", "item_id", "status", "order_type", "start_index", "due_index", "qty"])
    return NettingResult(tp, po, am, sup, issues)
