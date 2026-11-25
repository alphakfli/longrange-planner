"""IBP-style key-figure export and a Power BI-ready workbook.

The plan is written the way SAP IBP holds it: one row per product (or resource), location, month and key figure,
plus a planning view with key figures as rows and months as columns. Every sheet is an Excel Table, so Power BI or
Power Query loads it directly and refreshes when the file is replaced.
"""

from __future__ import annotations

import io

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

HEAD = PatternFill("solid", fgColor="0D5D6E")
PRODUCT_KF = [("planned_forecast", "Consensus Demand"), ("sales_orders", "Sales Orders"),
              ("dependent_demand", "Dependent Demand"), ("scheduled_receipts", "Supply - Firm Receipts"),
              ("planned_receipts", "Supply - Planned Receipts"), ("projected_available", "Projected Inventory"),
              ("safety_stock", "Safety Stock")]


def key_figures(r, location: str = "PLANT1") -> pd.DataFrame:
    tp = r.time_phased.merge(r.planned_forecast.rename(columns={"qty": "planned_forecast"}), on=["item_id", "month"], how="left")
    tp["planned_forecast"] = tp["planned_forecast"].fillna(0.0)
    rows = []
    for col, kf in PRODUCT_KF:
        x = tp[["item_id", "month", col]].rename(columns={"item_id": "product", col: "value"})
        x["key_figure"], x["location"], x["level"] = kf, location, "PRODUCT_LOCATION_MONTH"
        rows.append(x)
    cap = r.capacity
    for col, kf in [("available_hours", "Capacity Supply"), ("required_hours", "Capacity Usage"), ("load_pct", "Capacity Utilization %")]:
        x = cap[["work_center", "month", col]].rename(columns={"work_center": "product", col: "value"})
        x["key_figure"], x["location"], x["level"] = kf, location, "RESOURCE_LOCATION_MONTH"
        rows.append(x)
    out = pd.concat(rows, ignore_index=True)[["level", "product", "location", "month", "key_figure", "value"]]
    out = out.rename(columns={"product": "product_or_resource"})
    out["version"] = r.version
    out["scenario"] = r.scenario.name
    return out


def planning_view(kf: pd.DataFrame) -> pd.DataFrame:
    order = [k for _, k in PRODUCT_KF] + ["Capacity Supply", "Capacity Usage", "Capacity Utilization %"]
    v = kf.pivot_table(index=["product_or_resource", "key_figure"], columns="month", values="value", aggfunc="sum")
    v = v.reset_index()
    v["_o"] = v["key_figure"].map({k: i for i, k in enumerate(order)})
    return v.sort_values(["product_or_resource", "_o"]).drop(columns="_o")


def _table_sheet(wb, title: str, df: pd.DataFrame, name: str):
    ws = wb.create_sheet(title[:31])
    df = df.copy()
    df.columns = [str(c) for c in df.columns]
    ws.append(list(df.columns))
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = HEAD
    for row in df.itertuples(index=False):
        vals = []
        for v in row:
            if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
                v = None
            elif isinstance(v, pd.Timestamp):
                v = None if pd.isna(v) else v.to_pydatetime()
            elif isinstance(v, (np.bool_,)):
                v = bool(v)
            elif v is pd.NaT:
                v = None
            vals.append(v)
        ws.append(vals)
    if not len(df):
        ws.append([None] * len(df.columns))
    ref = f"A1:{get_column_letter(len(df.columns))}{max(len(df), 1) + 1}"
    t = Table(displayName=name, ref=ref)
    t.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
    ws.add_table(t)
    for j, col in enumerate(df.columns, start=1):
        ws.column_dimensions[get_column_letter(j)].width = min(40, max(10, len(col) + 2))
    return ws


def ibp_workbook(r, orders=None, health=None, review=None) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "README"
    ws["A1"] = "Supply plan in IBP key-figure format"
    ws["A1"].font = Font(bold=True, size=14)
    notes = [f"Forecast version {r.version}, scenario {r.scenario.name}, months {r.months[0]} to {r.months[-1]}.",
             "tbl_key_figures: one row per product or resource, location, month and key figure (load into IBP or Power BI).",
             "tbl_planning_view: key figures as rows and months as columns, as in an IBP planning view.",
             "Other tables: order lines, OTIF by month and customer, data-health checks, supply-review agenda, alerts.",
             "In Power BI: Get data > Excel workbook > tick the tbl_ tables. Replace this file and press Refresh."]
    for i, n in enumerate(notes, start=3):
        ws.cell(i, 1, n)
    ws.column_dimensions["A"].width = 110
    kf = key_figures(r)
    _table_sheet(wb, "key_figures", kf, "tbl_key_figures")
    _table_sheet(wb, "planning_view", planning_view(kf), "tbl_planning_view")
    _table_sheet(wb, "alerts", r.alerts, "tbl_alerts")
    if orders is not None:
        _table_sheet(wb, "open_order_lines", orders.open_lines, "tbl_open_order_lines")
        _table_sheet(wb, "otif_by_month", orders.otif_month, "tbl_otif_by_month")
        _table_sheet(wb, "otif_by_customer", orders.by_customer, "tbl_otif_by_customer")
        _table_sheet(wb, "order_lines", orders.lines.drop(columns=[c for c in ("price",) if c in orders.lines]), "tbl_order_lines")
    if health is not None:
        _table_sheet(wb, "data_health", health[0], "tbl_data_health")
    if review is not None:
        _table_sheet(wb, "supply_review", review, "tbl_supply_review")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
