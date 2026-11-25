"""Planning data governance: checks on the master and transaction data the plan depends on, with a health score.

Each check says what is wrong, how many records, why it matters for the plan, how to fix it in SAP / IBP, and who
usually owns the fix. Score = share of checks passed, weighted by severity (High 3, Medium 2, Low 1).
"""

from __future__ import annotations

import pandas as pd

WEIGHT = {"High": 3, "Medium": 2, "Low": 1}
COLUMNS = ["check_id", "area", "check", "severity", "records", "status", "examples", "why_it_matters", "fix", "owner"]


def data_health(data, r, orders=None) -> tuple[pd.DataFrame, dict]:
    items = r.items
    fg = items[items["item_type"] == "FG"]
    makes = items[items["replenishment"] == "make"]
    buys = items[items["replenishment"] == "buy"]
    rows: list[dict] = []

    def check(cid, area, text, sev, bad: list, why, fix, owner):
        bad = [str(b) for b in bad]
        rows.append(dict(check_id=cid, area=area, check=text, severity=sev, records=len(bad),
                         status="Pass" if not bad else "Fix", examples=", ".join(bad[:6]) + (" …" if len(bad) > 6 else ""),
                         why_it_matters=why, fix=fix, owner=owner))

    # ---- material master
    routed = set(data.routings["item_id"]) if not data.routings.empty else set()
    check("D01", "Material master", "Made finished goods without a routing", "Medium",
          [i for i in makes.loc[makes["item_type"] == "FG", "item_id"] if i not in routed],
          "Their production hours are not counted, so capacity looks better than it is.",
          "SAP: create the routing or production version (CA01, C223). IBP: assign the resource in the production source.",
          "Production planning")
    parents = set(data.bom["parent_item"])
    check("D02", "Material master", "Made items without a BOM", "High",
          [i for i in makes.loc[makes["item_type"].isin(["FG", "BULK"]), "item_id"] if i not in parents],
          "No dependent demand: components are not planned or bought.",
          "SAP: create the BOM (CS01). IBP: maintain the production source item / component.", "Engineering / master data")
    check("D03", "Material master", "Bought items without a vendor", "Medium", buys.loc[buys["vendor"].fillna("") == "", "item_id"].tolist(),
          "Purchase requisitions cannot become orders, and supplier risk is invisible.",
          "SAP: source list (ME01) or info record (ME11). IBP: external procurement source.", "Procurement")
    check("D04", "Material master", "Items with no lead time", "Medium", items.loc[items["lead_time_weeks"] <= 0, "item_id"].tolist(),
          "Supply is planned to arrive the month it is needed: plans look feasible when they are not.",
          "SAP: MRP 2 view, planned delivery time / in-house production time (MM02). IBP: lead time in the source.",
          "Supply planning")
    check("D05", "Material master", "Items with no standard cost", "Low", items.loc[items["unit_cost"] <= 0, "item_id"].tolist(),
          "Inventory value, E&O risk and order value are understated.", "SAP: costing run (CK11N / CK40N).", "Cost accounting")
    check("D06", "Material master", "Made items with no lot-size rule", "Low",
          makes.loc[(makes["min_order_qty"] <= 0) & (makes["order_multiple"] <= 0), "item_id"].tolist(),
          "Lot-for-lot orders of any size: unrealistic batches and setups.",
          "SAP: MRP 1 view lot size, minimum and rounding value (MM02).", "Supply planning")
    sf = r.safety
    man = items[items["safety_stock"].notna()][["item_id", "safety_stock"]]
    calc = sf[["item_id", "sigma", "lead_time_months"]] if len(sf) else pd.DataFrame(columns=["item_id", "sigma", "lead_time_months"])
    diff = []
    if len(man) and len(calc):
        m = man.merge(calc, on="item_id")
        m = m[m["sigma"].notna() & (m["sigma"] > 0)]
        from math import sqrt
        z = 1.645
        for x in m.itertuples():
            rec = z * x.sigma * sqrt(max(x.lead_time_months, 0) + 1)
            if rec > 0 and abs(x.safety_stock - rec) / rec > 0.5:
                diff.append(x.item_id)
    check("D07", "Planning parameters", "Fixed safety stock more than 50% off the calculated level (95%)", "Low", diff,
          "Too much buffer ties up cash; too little risks service.",
          "Review with the ABC / XYZ policy; SAP MRP 2 safety stock (MM02); IBP safety-stock planning.", "Supply planning")

    # ---- demand data
    fc = data.forecast[data.forecast["version"] == r.version]
    in_fc = set(fc["item_id"])
    active = set(fg.loc[fg["on_hand"] > 0, "item_id"]) | (set(data.sales_history["item_id"]) & set(fg["item_id"]))
    check("D08", "Demand", f"Active finished goods missing from forecast {r.version}", "High", sorted(active - in_fc),
          "No demand is planned for an item that is selling: stock-outs ahead.",
          "IBP: consensus demand key figure for the product; check the planning-level release to SAP.", "Demand planning")
    dup = fc[fc.duplicated(["item_id", "month"], keep=False)]
    check("D09", "Demand", "Duplicate forecast rows (same item and month)", "High",
          sorted(set(dup["item_id"] + " " + dup["month"])),
          "Demand is counted twice: double production and purchasing.", "Remove duplicates before loading; one row per item and month.",
          "Demand planning")
    months = set(r.months)
    gaps = []
    for item in sorted(in_fc & set(fg["item_id"])):
        have = set(fc.loc[fc["item_id"] == item, "month"]) & months
        if 0 < len(have) < len(months):
            gaps.append(item)
    check("D10", "Demand", "Forecast with gaps inside the horizon", "Medium", gaps,
          "Months with no demand make the plan stop and restart.", "IBP: extend the forecast to the full horizon.", "Demand planning")
    bs = r.bias_summary
    check("D11", "Demand", "Items with forecast bias outside the limit", "Medium",
          bs.loc[bs["flag"], "item_id"].tolist() if len(bs) else [],
          "A biased forecast builds excess or causes shortages month after month.",
          "Review the statistical model and the consensus overrides with Demand Planning (IBP demand sensing / FVA).",
          "Demand planning")

    # ---- supply and orders
    so = data.supply_orders
    pdue = so[so["due_month"] < r.months[0]]["order_id"].tolist() if not so.empty else []
    check("D12", "Supply orders", "Production or purchase orders due before the plan start", "Medium", pdue,
          "Past-due receipts are counted as available now: the plan may rely on stock that is not coming.",
          "SAP: reschedule or close the order (MD04, CO02, ME22N); confirm with the supplier.", "Supply planning / procurement")
    if orders is not None:
        op = orders.open_lines
        check("D13", "Customer orders", "Open order lines without a confirmed date", "Medium",
              op.loc[op["confirmed_date"].isna(), "order_id"].tolist(),
              "Customer service cannot give a date and OTIF cannot be measured against a commitment.",
              "SAP: run the availability check and confirm the schedule line (VA02, CO09).", "Customer service")
        check("D14", "Customer orders", "Open order lines more than 30 days past due", "Medium",
              op.loc[op["days_past_due"] > 30, "order_id"].tolist(),
              "Stale lines inflate the backlog and the demand the plan covers.",
              "Ship, re-date or cancel with the customer (VA02); clear blocks (V23).", "Customer service")
        ol = orders.lines
        badd = ol[(ol["confirmed_date"].notna()) & (ol["order_date"].notna()) & (ol["confirmed_date"] < ol["order_date"])]
        check("D15", "Customer orders", "Lines confirmed for a date before they were ordered", "Low", badd["order_id"].tolist(),
              "Impossible dates distort OTIF and lead-time analysis.", "Correct the schedule line dates (VA02).", "Customer service")
    sh = data.sales_history
    hist_gaps = []
    if not sh.empty:
        last12 = sorted(sh["month"].unique())[-12:]
        for item in sorted(set(fg["item_id"]) & set(sh["item_id"])):
            have = set(sh.loc[sh["item_id"] == item, "month"])
            if len(set(last12) - have):
                hist_gaps.append(item)
    check("D16", "Demand", "Finished goods with missing months in the last 12 months of sales history", "Medium", hist_gaps,
          "The statistical baseline, accuracy and safety stock are calculated on incomplete history.",
          "Reload history from SAP (sales by month, VBRP / S001) or mark true zero months as 0.", "Demand planning")

    df = pd.DataFrame(rows, columns=COLUMNS)
    df = df.assign(_f=df["status"].eq("Pass"), _w=-df["severity"].map(WEIGHT)).sort_values(
        ["_f", "_w", "check_id"]).drop(columns=["_f", "_w"]).reset_index(drop=True)
    w = df["severity"].map(WEIGHT)
    score = 100 * float(w[df["status"] == "Pass"].sum()) / float(w.sum()) if len(df) else 100.0
    kpis = dict(score=score, checks=len(df), passed=int((df["status"] == "Pass").sum()),
                failed_high=int(((df["status"] == "Fix") & (df["severity"] == "High")).sum()),
                records=int(df["records"].sum()))
    return df, kpis
