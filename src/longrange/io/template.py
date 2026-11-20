"""Write a blank Excel input template from the schema, with an instructions sheet."""

from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from longrange.models import SCHEMA, Settings

HEAD = PatternFill("solid", fgColor="0D5D6E")
REQ = PatternFill("solid", fgColor="F6EAD2")


def template_bytes(data=None) -> bytes:
    """Return an .xlsx template. If ``data`` (PlanningData) is given, its rows are filled in."""
    wb = Workbook()
    ws = wb.active
    ws.title = "README"
    ws["A1"] = "LongRange Planner input workbook"
    ws["A1"].font = Font(bold=True, size=14)
    lines = [
        "One sheet per table. Keep the header row exactly as written; extra columns are ignored.",
        "Months use YYYY-MM (for example 2026-11). Dates are also accepted and read as their month.",
        "Shaded headers are required. Blank optional cells take the default shown below.",
        "Keep every monthly forecast version in the forecast sheet; set current_forecast on the settings sheet.",
        "",
    ]
    r = 3
    for line in lines:
        ws.cell(r, 1, line)
        r += 1
    for sheet, spec in SCHEMA.items():
        ws.cell(r, 1, sheet).font = Font(bold=True)
        ws.cell(r, 2, spec["help"])
        r += 1
        for col in spec["columns"]:
            ws.cell(r, 2, col.name)
            ws.cell(r, 3, "required" if col.required else f"optional (default {col.default if col.default is not None else 'blank'})")
            ws.cell(r, 4, col.help)
            r += 1
        r += 1
    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 34
    ws.column_dimensions["C"].width = 26
    ws.column_dimensions["D"].width = 90

    for sheet, spec in SCHEMA.items():
        sh = wb.create_sheet(sheet)
        cols = spec["columns"]
        for j, col in enumerate(cols, start=1):
            c = sh.cell(1, j, col.name)
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = HEAD
            c.alignment = Alignment(horizontal="center")
            if col.required:
                sh.cell(2, j).fill = REQ if data is None else PatternFill()
            sh.column_dimensions[get_column_letter(j)].width = max(12, len(col.name) + 4)
        sh.freeze_panes = "A2"
        if data is not None:
            df = data.table(sheet)
            for i, row in enumerate(df.itertuples(index=False), start=2):
                for j, v in enumerate(row, start=1):
                    sh.cell(i, j, None if v != v else v)  # NaN -> blank

    st = wb.create_sheet("settings")
    st.append(["key", "value", "meaning"])
    for c in st[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = HEAD
    meanings = {
        "plan_start": "First planning month, YYYY-MM. Blank = first month of the current forecast",
        "horizon_months": "Months to plan (18 for long-term)",
        "current_forecast": "Forecast version to plan with. Blank = last version by name",
        "previous_forecast": "Version to compare with. Blank = the version before current",
        "frozen_months": "Months where existing orders are not changed",
        "slushy_months": "Months where changes need agreement",
        "default_service_level": "Service level for calculated safety stock (0.95 = 95%)",
        "capacity_warning_pct": "Load % that raises a warning",
        "capacity_critical_pct": "Load % that raises a critical alert",
        "forecast_change_alert_pct": "Forecast change vs previous version that raises an alert",
        "eo_coverage_share": "Coverage above this share of shelf life is an E&O risk",
        "max_weeks_of_coverage": "Coverage limit for items without shelf life",
        "attainment_target_pct": "Target for plan attainment",
        "weeks_per_month": "Weeks in a month for lead-time conversion",
    }
    settings = data.settings if data is not None else Settings()
    for _, row in settings.to_table().iterrows():
        st.append([row["key"], row["value"], meanings.get(row["key"], "")])
    st.column_dimensions["A"].width = 28
    st.column_dimensions["B"].width = 16
    st.column_dimensions["C"].width = 70
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
