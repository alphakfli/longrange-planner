"""A realistic, fully fictional sample dataset: 'Northfield Skincare', a cosmetics plant.

It is built so that the first plan shows real planning problems to work through:
a filling line overloaded at the April sale peaks and in the December shutdown,
raw materials whose lead time is too long for the first months, an eye serum with
falling demand and excess stock (E&O risk), forecast changes between two monthly
versions, sales history whose peak moved from November to April, and four proposed demand
events (promotions, a new listing and a delisting) to try as what-ifs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from longrange.models import PlanningData, Settings
from longrange.months import add_months, month_range

PLAN_START = "2026-12"
HISTORY_START = "2024-06"

# Seasonality by calendar month. The big sale moved from November (old) to April (new) in 2026.
SEASON_OLD = {1: .92, 2: .88, 3: .95, 4: .98, 5: 1.0, 6: .97, 7: .95, 8: .96, 9: 1.0, 10: 1.05, 11: 1.45, 12: 1.12}
SEASON_NEW = {1: .95, 2: .92, 3: 1.12, 4: 1.45, 5: .98, 6: .96, 7: .94, 8: .95, 9: .98, 10: 1.02, 11: 1.0, 12: 1.1}

FG = [
    # id, description, base monthly units, growth per month, abc, shelf life, unit cost
    ("FG-1001", "Niacinamide 10% Serum 30 ml", 68000, .006, "A", 36, 2.10),
    ("FG-1002", "Hyaluronic Acid 2% Serum 30 ml", 46000, .004, "A", 30, 2.40),
    ("FG-1003", "Retinol 0.5% Serum 30 ml", 24000, .015, "B", 24, 3.20),
    ("FG-1004", "Moisturizing Cream 100 ml", 40000, .003, "B", 30, 2.90),
    ("FG-1005", "Squalane Cleanser 50 ml", 30000, .004, "B", 30, 2.60),
    ("FG-1006", "Peptide Eye Serum 15 ml", 9000, -.025, "C", 24, 3.80),
]


def _season(month: str, new: bool) -> float:
    return (SEASON_NEW if new else SEASON_OLD)[int(month[5:7])]


def build_sample() -> PlanningData:
    rng = np.random.default_rng(42)
    items = pd.DataFrame([
        # FG
        ["FG-1001", "Niacinamide 10% Serum 30 ml", "FG", "make", "EA", 70000, 30000, None, 2, 1, 20000, 5000, 0, 1, 36, 2.10, "", ""],
        ["FG-1002", "Hyaluronic Acid 2% Serum 30 ml", "FG", "make", "EA", 52000, None, None, 2, 1, 15000, 5000, 0, 1, 30, 2.40, "", ""],
        ["FG-1003", "Retinol 0.5% Serum 30 ml", "FG", "make", "EA", 8000, None, None, 2, 1, 10000, 5000, 0, 1, 24, 3.20, "", ""],
        ["FG-1004", "Moisturizing Cream 100 ml", "FG", "make", "EA", 38000, 18000, None, 2, 1, 15000, 5000, 0, 1, 30, 2.90, "", ""],
        ["FG-1005", "Squalane Cleanser 50 ml", "FG", "buy", "EA", 30000, 15000, None, 6, 1, 25000, 5000, 0, 1, 30, 2.60, "NorthPak Contract Manufacturing", ""],
        ["FG-1006", "Peptide Eye Serum 15 ml", "FG", "make", "EA", 120000, 4000, None, 2, 1, 5000, 1000, 0, 1, 24, 3.80, "", ""],
        # Bulk (kg)
        ["BLK-2001", "Niacinamide serum bulk", "BULK", "make", "KG", 2600, 500, None, 1, 0, 2000, 1000, 6000, 2, 12, 18, "", ""],
        ["BLK-2002", "Hyaluronic serum bulk", "BULK", "make", "KG", 1900, 400, None, 1, 0, 2000, 1000, 6000, 2, 12, 22, "", ""],
        ["BLK-2003", "Retinol serum bulk", "BULK", "make", "KG", 300, 200, None, 1, 0, 1000, 500, 3000, 2, 9, 41, "", ""],
        ["BLK-2004", "Moisturizing cream bulk", "BULK", "make", "KG", 3800, 800, None, 1, 0, 3000, 1000, 8000, 2, 12, 15, "", ""],
        ["BLK-2006", "Peptide eye serum bulk", "BULK", "make", "KG", 500, 100, None, 1, 0, 500, 250, 2000, 2, 9, 55, "", ""],
        # Packaging
        ["PKG-3001", "Glass dropper bottle 30 ml", "PKG", "buy", "EA", 240000, 40000, None, 10, 2, 150000, 10000, 0, 3, 0, .38, "Lumen Glass Packaging", ""],
        ["PKG-3002", "Carton 30 ml", "PKG", "buy", "EA", 310000, 40000, None, 6, 1, 250000, 20000, 0, 3, 0, .06, "Cartonex Print", ""],
        ["PKG-3003", "Jar 100 ml with lid", "PKG", "buy", "EA", 95000, 20000, None, 8, 2, 80000, 10000, 0, 3, 0, .42, "Lumen Glass Packaging", ""],
        ["PKG-3004", "Airless bottle 15 ml", "PKG", "buy", "EA", 120000, 10000, None, 8, 2, 40000, 10000, 0, 3, 0, .55, "Lumen Glass Packaging", ""],
        # Raw materials (kg)
        ["RAW-4001", "Niacinamide powder", "RAW", "buy", "KG", 450, 100, None, 6, 1, 250, 25, 0, 2, 24, 28, "ChemSource Ltd", ""],
        ["RAW-4002", "Sodium hyaluronate", "RAW", "buy", "KG", 30, 10, None, 8, 1, 25, 5, 0, 2, 24, 950, "ChemSource Ltd", ""],
        ["RAW-4003", "Retinol 10% solution", "RAW", "buy", "KG", 12, 5, None, 10, 2, 20, 5, 0, 2, 12, 620, "Actives Global", ""],
        ["RAW-4005", "Glycerin", "RAW", "buy", "KG", 3500, 800, None, 3, 1, 2000, 200, 0, 2, 36, 2.2, "ChemSource Ltd", ""],
    ], columns=["item_id", "description", "item_type", "replenishment", "uom", "on_hand", "safety_stock", "service_level",
                "lead_time_weeks", "safety_lead_time_weeks", "min_order_qty", "order_multiple", "max_order_qty",
                "lot_accum_months", "shelf_life_months", "unit_cost", "vendor", "abc"])
    items["safety_stock"] = items["safety_stock"].astype("float64")
    items["service_level"] = items["service_level"].astype("float64")

    bom = pd.DataFrame([
        ["FG-1001", "BLK-2001", .031, 2], ["FG-1001", "PKG-3001", 1, .5], ["FG-1001", "PKG-3002", 1, .5],
        ["FG-1002", "BLK-2002", .031, 2], ["FG-1002", "PKG-3001", 1, .5], ["FG-1002", "PKG-3002", 1, .5],
        ["FG-1003", "BLK-2003", .031, 2], ["FG-1003", "PKG-3001", 1, .5], ["FG-1003", "PKG-3002", 1, .5],
        ["FG-1004", "BLK-2004", .102, 2], ["FG-1004", "PKG-3003", 1, .5],
        ["FG-1006", "BLK-2006", .016, 2], ["FG-1006", "PKG-3004", 1, .5],
        ["BLK-2001", "RAW-4001", .10, 0], ["BLK-2001", "RAW-4005", .05, 0],
        ["BLK-2002", "RAW-4002", .02, 0], ["BLK-2002", "RAW-4005", .05, 0],
        ["BLK-2003", "RAW-4003", .05, 0], ["BLK-2003", "RAW-4005", .05, 0],
        ["BLK-2004", "RAW-4005", .12, 0], ["BLK-2006", "RAW-4005", .05, 0],
    ], columns=["parent_item", "component_item", "qty_per", "scrap_pct"])

    work_centers = pd.DataFrame([
        ["CMP", "Compounding", 1, 8, 21, 90],
        ["FL1", "Filling line 1 (30 ml droppers)", 2, 8, 21, 85],
        ["FL2", "Filling line 2 (jars and small bottles)", 2, 8, 21, 85],
    ], columns=["work_center", "name", "shifts", "hours_per_shift", "working_days_per_month", "efficiency_pct"])

    cal_rows = []
    for m in month_range(PLAN_START, 18):
        days = {1: 20, 2: 19, 3: 22, 4: 20, 5: 21, 6: 21, 7: 21, 8: 21, 9: 21, 10: 21, 11: 20, 12: 15}[int(m[5:7])]
        for wc in ["CMP", "FL1", "FL2"]:
            cal_rows.append([wc, m, days])
    calendar = pd.DataFrame(cal_rows, columns=["work_center", "month", "working_days"])

    routings = pd.DataFrame([
        ["FG-1001", "FL1", 640, 2, 1], ["FG-1002", "FL1", 640, 2, 1], ["FG-1003", "FL1", 600, 2, 1],
        ["FG-1001", "FL2", 480, 3, 2], ["FG-1002", "FL2", 480, 3, 2], ["FG-1003", "FL2", 460, 3, 2],
        ["FG-1004", "FL2", 420, 2, 1], ["FG-1006", "FL2", 380, 2, 1],
        ["BLK-2001", "CMP", 260, 2, 1], ["BLK-2002", "CMP", 260, 2, 1], ["BLK-2003", "CMP", 200, 3, 1],
        ["BLK-2004", "CMP", 300, 2, 1], ["BLK-2006", "CMP", 150, 3, 1],
    ], columns=["item_id", "work_center", "units_per_hour", "setup_hours", "priority"])

    # Sales history: old seasonality until Oct 2025, new (April peak) from 2026.
    hist_rows = []
    hist_months = month_range(HISTORY_START, 30)  # Jun 2024 .. Nov 2026
    for item, _desc, base, growth, _abc, _sl, _c in FG:
        for i, m in enumerate(hist_months):
            back = 30 - i
            level = base * (1 + growth) ** (-back)
            new = m >= "2026-01"
            qty = level * _season(m, new) * rng.normal(1, .07)
            hist_rows.append([item, m, round(max(qty, 0), -2)])
    sales_history = pd.DataFrame(hist_rows, columns=["item_id", "month", "qty"])

    def forecast_version(name, start, adj):
        rows = []
        for item, _desc, base, growth, _abc, _sl, _c in FG:
            for i, m in enumerate(month_range(start, 18)):
                qty = base * (1 + growth) ** (i + 1) * _season(m, True) * adj.get(item, 1)
                rows.append([name, item, m, round(qty, -2)])
        return rows

    forecast = pd.DataFrame(
        forecast_version("FC-2026-10", "2026-11", {"FG-1003": .86, "FG-1001": .96}) +
        forecast_version("FC-2026-11", PLAN_START, {"FG-1002": .88}),
        columns=["version", "item_id", "month", "qty"])

    # Archived versions, keeping only the months now in the past, so lag-1 accuracy covers Sep-Nov 2026.
    # Built from actuals with a bias per item: FG-1003 runs under (demand growing), FG-1006 over.
    lean = {"FG-1001": (-.04, -.06), "FG-1002": (.03, -.02), "FG-1003": (-.09, -.11),
            "FG-1004": (.02, .01), "FG-1005": (-.01, .02), "FG-1006": (.24, .22)}
    actual = sales_history.set_index(["item_id", "month"])["qty"]
    archived = []
    for name, months in (("FC-2026-08", ["2026-09", "2026-10"]), ("FC-2026-09", ["2026-10", "2026-11"])):
        for item, (b_sep, b_oct) in lean.items():
            for m in months:
                b = b_sep if m == "2026-09" else b_oct if m == "2026-10" else (b_sep + b_oct) / 2
                archived.append([name, item, m, round(actual[(item, m)] * (1 + b), -2)])
    forecast = pd.concat([pd.DataFrame(archived, columns=forecast.columns), forecast], ignore_index=True)

    # A stock-out: FG-1003 Retinol was out of stock 9 of 31 days in October 2026. Recorded sales show
    # only what was available to sell; the planner estimates true demand from the 22 selling days.
    sales_history["stockout_days"] = 0.0
    so = (sales_history["item_id"] == "FG-1003") & (sales_history["month"] == "2026-10")
    sales_history.loc[so, "qty"] = round(float(sales_history.loc[so, "qty"].iloc[0]) * 22 / 31)
    sales_history.loc[so, "stockout_days"] = 9.0

    sales_orders = pd.DataFrame([
        ["FG-1001", "2026-12", 41000, "Retail DC East"], ["FG-1002", "2026-12", 30000, "Retail DC East"],
        ["FG-1001", "2027-01", 35000, "E-commerce"], ["FG-1003", "2026-12", 19000, "Wholesale UK"],
        ["FG-1004", "2026-12", 28000, "Retail DC West"],
    ], columns=["item_id", "month", "qty", "customer"])

    supply_orders = pd.DataFrame([
        ["PRD-1001", "FG-1001", "production", "released", "2026-12", 60000],
        ["PRD-1002", "FG-1002", "production", "firm", "2026-12", 40000],
        ["PRD-1003", "FG-1004", "production", "firm", "2026-12", 30000],
        ["PRD-1004", "FG-1002", "production", "firm", "2027-01", 70000],
        ["PRD-1005", "FG-1006", "production", "firm", "2027-02", 15000],
        ["PO-5001", "PKG-3001", "purchase", "released", "2027-01", 150000],
        ["PO-5002", "FG-1005", "purchase", "released", "2026-12", 25000],
        ["PO-5003", "RAW-4001", "purchase", "released", "2026-12", 250],
    ], columns=["order_id", "item_id", "order_type", "status", "due_month", "qty"])

    act_rows = []
    for m in month_range(add_months(PLAN_START, -6), 6):
        for item, plan, att in [("FG-1001", 70000, .95), ("FG-1002", 48000, 1.06), ("FG-1003", 25000, .76),
                                ("FG-1004", 42000, 1.0), ("FG-1006", 9000, .9)]:
            actual = plan * att * rng.normal(1, .04)
            act_rows.append([item, m, plan, round(actual, -2)])
    production_actuals = pd.DataFrame(act_rows, columns=["item_id", "month", "planned_qty", "actual_qty"])

    # Demand events proposed by Marketing and Sales, not yet approved at S&OP (try them in the what-if).
    events = pd.DataFrame([
        ["EV-01", "FG-1001", "promo", "2027-03", "2027-04", 25, 0, "proposed", "Marketing: extend the spring sale into March"],
        ["EV-02", "FG-1003", "launch", "2027-06", "2027-11", 0, 6000, "proposed", "Sales: new retailer listing"],
        ["EV-03", "FG-1006", "delist", "2027-09", None, -100, 0, "proposed", "Portfolio review: phase-out candidate"],
        ["EV-04", "FG-1002", "promo", "2027-01", "2027-01", 20, 0, "proposed", "E-commerce: January bundle"],
    ], columns=["event_id", "item_id", "event_type", "start_month", "end_month", "lift_pct", "extra_qty", "status", "note"])

    settings = Settings(plan_start=PLAN_START, current_forecast="FC-2026-11", previous_forecast="FC-2026-10")
    return PlanningData(items=items, bom=bom, work_centers=work_centers, calendar=calendar, routings=routings,
                        forecast=forecast, sales_history=sales_history, sales_orders=sales_orders,
                        supply_orders=supply_orders, production_actuals=production_actuals, events=events,
                        settings=settings)
