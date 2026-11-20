"""Excel export: a formatted workbook with every view of the plan, ready for S&OP prep."""

from __future__ import annotations

import io

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule, ColorScaleRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from longrange.engine import PlanResult
from longrange.months import label

HEAD = PatternFill("solid", fgColor="0D5D6E")
WHITE = Font(bold=True, color="FFFFFF")
RED = PatternFill("solid", fgColor="F8D7D3")
AMBER = PatternFill("solid", fgColor="F6EAD2")
GREEN = PatternFill("solid", fgColor="DDF0E3")
SEV_FILL = {"Critical": RED, "Warning": AMBER, "Info": PatternFill("solid", fgColor="DCECEF")}


def _sheet(wb, title: str, df: pd.DataFrame, number_formats: dict[str, str] | None = None, widths: dict[str, int] | None = None):
    ws = wb.create_sheet(title)
    ws.append(list(df.columns))
    for c in ws[1]:
        c.font = WHITE
        c.fill = HEAD
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row in df.itertuples(index=False):
        ws.append([None if (isinstance(v, float) and (np.isnan(v) or np.isinf(v))) else v for v in row])
    number_formats = number_formats or {}
    for j, col in enumerate(df.columns, start=1):
        letter = get_column_letter(j)
        w = (widths or {}).get(col) or min(60, max(10, len(str(col)) + 2,
                                               int(df[col].map(lambda v: len(str(v))).quantile(.9)) + 2 if len(df) else 0))
        ws.column_dimensions[letter].width = w
        fmt = number_formats.get(col)
        if fmt is None and pd.api.types.is_float_dtype(df[col]):
            fmt = "#,##0"
        if fmt:
            for cell in ws[letter][1:]:
                cell.number_format = fmt
    ws.freeze_panes = "B2"
    if len(df):
        ws.auto_filter.ref = ws.dimensions
    return ws


def excel_report(r: PlanResult) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    s = r.summary()
    ws["A1"] = "Long-term production plan"
    ws["A1"].font = Font(bold=True, size=16)
    ws["A2"] = f"Forecast {r.version}" + (f" vs {r.previous_version}" if r.previous_version else "") + f" · {label(r.months[0])} to {label(r.months[-1])} · scenario: {r.scenario.name}"
    rows = [
        ("Critical alerts", s["alerts_critical"]), ("Warnings", s["alerts_warning"]), ("New planned orders", s["planned_orders"]),
        ("Peak capacity load", f"{s['peak_load_pct']:.0f}% ({s['peak_load_wc']}, {label(s['peak_load_month']) if s['peak_load_month'] else ''})"),
        ("Work-center months over capacity", s["overloaded_months"]),
        ("Inventory value, first month", round(s["inventory_value_start"])), ("Inventory value, last month", round(s["inventory_value_end"])),
        ("Finished goods with a shortage", s["fg_shortage_items"]), ("Items with E&O risk", s["eo_risk_items"]),
        ("Net attainment, last 3 months", None if np.isnan(s["net_attainment_pct"]) else round(s["net_attainment_pct"], 1)),
        ("Absolute attainment, last 3 months", None if np.isnan(s["absolute_attainment_pct"]) else round(s["absolute_attainment_pct"], 1)),
    ]
    for i, (k, v) in enumerate(rows, start=4):
        ws.cell(i, 1, k).font = Font(bold=True)
        ws.cell(i, 2, v)
        if isinstance(v, (int, float)) and v is not None and v > 1000:
            ws.cell(i, 2).number_format = "#,##0"
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 34

    # Alerts
    al = r.alerts.copy()
    al["month"] = al["month"].map(lambda m: label(m) if m else "")
    wa = _sheet(wb, "Alerts", al, widths={"message": 90, "suggested_action": 60, "category": 16, "ref": 14})
    for i, sev in enumerate(al["severity"], start=2):
        wa.cell(i, 1).fill = SEV_FILL.get(sev, PatternFill())

    # Capacity (wide: work center x month load %)
    cap = r.capacity.pivot_table(index=["work_center", "name"], columns="month", values="load_pct").reset_index()
    cap.columns = [label(c) if c not in ("work_center", "name") else c for c in cap.columns]
    wc = _sheet(wb, "Capacity load %", cap, widths={"name": 34})
    rng = f"C2:{get_column_letter(cap.shape[1])}{cap.shape[0] + 1}"
    wc.conditional_formatting.add(rng, CellIsRule(operator="greaterThan", formula=[str(r.settings.capacity_critical_pct)], fill=RED))
    wc.conditional_formatting.add(rng, CellIsRule(operator="between", formula=[str(r.settings.capacity_warning_pct), str(r.settings.capacity_critical_pct)], fill=AMBER))
    for row in wc.iter_rows(min_row=2, min_col=3):
        for c in row:
            c.number_format = '0"%"'
    _sheet(wb, "Capacity hours", r.capacity[["work_center", "month", "shifts", "working_days", "efficiency_pct",
                                              "available_hours", "required_hours", "spare_hours", "load_pct"]],
           number_formats={"load_pct": '0"%"'})
    _sheet(wb, "Capacity by item", r.capacity_detail.sort_values(["work_center", "month", "hours"], ascending=[True, True, False]))

    # Planned orders and order changes
    po = r.planned_orders.drop(columns=["release_index", "due_index"]).merge(
        r.items[["item_id", "description"]], on="item_id", how="left")
    po = po[["planned_id", "item_id", "description", "order_type", "release_month", "due_month", "qty", "zone", "release_in_past", "vendor"]]
    _sheet(wb, "Planned orders", po, widths={"description": 32})
    _sheet(wb, "Order changes", r.action_messages, widths={"reason": 80})

    # MPS grid: finished goods, projected available by month
    fg = r.items.loc[r.items["item_type"] == "FG", "item_id"]
    tp = r.time_phased[r.time_phased["item_id"].isin(fg)]
    measures = ["independent_demand", "scheduled_receipts", "planned_receipts", "projected_available", "safety_stock"]
    grid = tp.melt(id_vars=["item_id", "month"], value_vars=measures, var_name="measure")
    grid = grid.pivot_table(index=["item_id", "measure"], columns="month", values="value", sort=False).reset_index()
    grid["measure"] = pd.Categorical(grid["measure"], measures, ordered=True)
    grid = grid.sort_values(["item_id", "measure"])
    grid["measure"] = grid["measure"].astype(str).str.replace("_", " ").str.capitalize()
    grid.columns = [label(c) if c not in ("item_id", "measure") else c for c in grid.columns]
    wm = _sheet(wb, "MPS (finished goods)", grid, widths={"measure": 22})
    for row in wm.iter_rows(min_row=2):
        if row[1].value == "Projected available":
            for c in row:
                c.font = Font(bold=True)
    _sheet(wb, "Time-phased (all items)", r.time_phased)

    # Inventory
    inv = r.inventory.copy()
    inv["weeks_of_coverage"] = inv["weeks_of_coverage"].replace([np.inf, -np.inf], np.nan)
    woc = inv.pivot_table(index="item_id", columns="month", values="weeks_of_coverage", sort=False).reset_index()
    woc.columns = [label(c) if c != "item_id" else c for c in woc.columns]
    ww = _sheet(wb, "Weeks of coverage", woc)
    if woc.shape[1] > 1:
        ww.conditional_formatting.add(f"B2:{get_column_letter(woc.shape[1])}{woc.shape[0] + 1}",
                                      ColorScaleRule(start_type="num", start_value=0, start_color="F8D7D3",
                                                     mid_type="num", mid_value=8, mid_color="FFFFFF",
                                                     end_type="num", end_value=40, end_color="F6EAD2"))
        for row in ww.iter_rows(min_row=2, min_col=2):
            for c in row:
                c.number_format = "0.0"
    _sheet(wb, "Inventory detail", inv, number_formats={"weeks_of_coverage": "0.0", "coverage_limit_weeks": "0", "inventory_value": "$#,##0"})
    _sheet(wb, "Safety stock", r.safety, widths={"method": 60})

    # Forecast
    if not r.forecast_bridge.empty:
        _sheet(wb, "Forecast bridge", r.forecast_bridge, number_formats={"change_pct": '0.0"%"'})
    if not r.accuracy.empty:
        acc = r.accuracy.copy()
        acc["wmape"] *= 100
        acc["bias"] *= 100
        _sheet(wb, "Forecast accuracy", acc, number_formats={"wmape": '0.0"%"', "bias": '0.0"%"'})
    if not r.stat_forecast.empty:
        st = r.stat_forecast.pivot_table(index="item_id", columns="month", values="qty").reset_index()
        st.columns = [label(c) if c != "item_id" else c for c in st.columns]
        meth = pd.DataFrame([{"item_id": d.item_id, "method": d.method,
                              "holdout_wmape_pct": None if d.holdout_wmape is None else d.holdout_wmape * 100} for d in r.stat_details])
        _sheet(wb, "Statistical forecast", meth.merge(st, on="item_id", how="right"), number_formats={"holdout_wmape_pct": '0.0"%"'})

    # KPIs
    if not r.attainment_month.empty:
        _sheet(wb, "Attainment by month", r.attainment_month,
               number_formats={"net_attainment_pct": '0.0"%"', "absolute_attainment_pct": '0.0"%"'})
        _sheet(wb, "Attainment by item", r.attainment_item,
               number_formats={"net_attainment_pct": '0.0"%"', "absolute_attainment_pct": '0.0"%"'})
    _sheet(wb, "Settings", r.settings.to_table())

    for w in wb.worksheets:
        w.sheet_view.zoomScale = 100
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
