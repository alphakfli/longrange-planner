"""PDF export: an S&OP supply review pack (landscape, letter size)."""

from __future__ import annotations

import io
from datetime import date

import numpy as np
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, Line, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from longrange.engine import PlanResult
from longrange.months import label

INK = colors.HexColor("#16211F")
MUTED = colors.HexColor("#56655F")
ACCENT = colors.HexColor("#0D5D6E")
LINE = colors.HexColor("#D3DCD8")
RED = colors.HexColor("#F8D7D3")
RED_INK = colors.HexColor("#B4372A")
AMBER = colors.HexColor("#F6EAD2")
GREEN = colors.HexColor("#DDF0E3")
SEV = {"Critical": RED, "Warning": AMBER, "Info": colors.HexColor("#DCECEF")}

ss = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=20, textColor=INK, spaceAfter=4)
H2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=14, textColor=INK, spaceBefore=6, spaceAfter=6)
BODY = ParagraphStyle("b", parent=ss["BodyText"], fontName="Helvetica", fontSize=9.5, leading=12.5, textColor=INK, alignment=TA_LEFT)
SMALL = ParagraphStyle("s", parent=BODY, fontSize=8, leading=10, textColor=MUTED)
CELL = ParagraphStyle("c", parent=BODY, fontSize=8, leading=10)


def _table(data, widths=None, header=True, zebra=False, font=8):
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [("FONT", (0, 0), (-1, -1), "Helvetica", font), ("TEXTCOLOR", (0, 0), (-1, -1), INK),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEBELOW", (0, 0), (-1, -1), .3, LINE),
             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), ACCENT), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                  ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", font)]
    t.setStyle(TableStyle(style))
    return t


def _fmt(v, kind="n"):
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return "–"
    if kind == "pct":
        return f"{v:.0f}%"
    if kind == "pct1":
        return f"{v:.1f}%"
    if kind == "money":
        return f"${v:,.0f}"
    if kind == "w":
        return f"{v:.1f}"
    return f"{v:,.0f}"


def _load_chart(r: PlanResult, wc: str, width=9.6 * inch, height=2.4 * inch):
    g = r.capacity[r.capacity["work_center"] == wc]
    vals = [float(v) for v in g["load_pct"]]
    d = Drawing(width, height)
    bc = VerticalBarChart()
    bc.x, bc.y, bc.width, bc.height = 40, 28, width - 60, height - 48
    bc.data = [vals]
    bc.valueAxis.valueMin = 0
    top = max(120, int(np.ceil(max(vals + [100]) / 20) * 20))
    bc.valueAxis.valueMax = top
    bc.valueAxis.valueStep = 20
    bc.valueAxis.labels.fontSize = 7
    bc.valueAxis.labels.fontName = "Helvetica"
    bc.categoryAxis.labels.fontName = "Helvetica"
    bc.valueAxis.labelTextFormat = "%d%%"
    bc.categoryAxis.categoryNames = [label(m) for m in g["month"]]
    bc.categoryAxis.labels.fontSize = 6.5
    bc.categoryAxis.labels.angle = 0
    bc.bars[0].fillColor = ACCENT
    bc.bars[0].strokeColor = None
    for i, v in enumerate(vals):
        if v > r.settings.capacity_critical_pct:
            bc.bars[(0, i)].fillColor = RED_INK
        elif v >= r.settings.capacity_warning_pct:
            bc.bars[(0, i)].fillColor = colors.HexColor("#C98A2B")
    d.add(bc)
    y100 = bc.y + bc.height * (100 / top)
    d.add(Line(bc.x, y100, bc.x + bc.width, y100, strokeColor=RED_INK, strokeDashArray=[3, 2], strokeWidth=.8))
    d.add(String(bc.x + bc.width + 2, y100 - 3, "100%", fontSize=7, fontName="Helvetica", fillColor=RED_INK))
    return d


def _value_chart(r: PlanResult, width=9.6 * inch, height=2.0 * inch):
    v = r.inventory.groupby("month", sort=False)["inventory_value"].sum()
    pts = [(i, float(x) / 1000) for i, x in enumerate(v)]
    d = Drawing(width, height)
    lp = LinePlot()
    lp.x, lp.y, lp.width, lp.height = 50, 26, width - 70, height - 40
    lp.data = [pts]
    lp.lines[0].strokeColor = ACCENT
    lp.lines[0].strokeWidth = 2
    lp.xValueAxis.valueMin, lp.xValueAxis.valueMax = 0, len(pts) - 1
    lp.xValueAxis.valueSteps = list(range(0, len(pts), 2))
    labels = [label(m) for m in v.index]
    lp.xValueAxis.labelTextFormat = lambda x: labels[int(x)] if 0 <= int(x) < len(labels) else ""
    lp.xValueAxis.labels.fontSize = 7
    lp.xValueAxis.labels.fontName = "Helvetica"
    lp.yValueAxis.labels.fontName = "Helvetica"
    lp.yValueAxis.valueMin = 0
    lp.yValueAxis.labels.fontSize = 7
    lp.yValueAxis.labelTextFormat = "$%dk"
    d.add(lp)
    return d


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(0.5 * inch, 0.35 * inch, f"LongRange Planner · generated {date.today().isoformat()}")
    canvas.drawRightString(10.5 * inch, 0.35 * inch, f"Page {doc.page}")
    canvas.restoreState()


def pdf_report(r: PlanResult, title: str = "S&OP supply review") -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(letter), leftMargin=.5 * inch, rightMargin=.5 * inch,
                            topMargin=.5 * inch, bottomMargin=.55 * inch, title=title, author="LongRange Planner")
    s = r.summary()
    story = []

    # Page 1: summary and decisions
    story.append(Paragraph(title.replace("&", "&amp;"), H1))
    story.append(Paragraph(f"Forecast <b>{r.version}</b>{' vs ' + r.previous_version if r.previous_version else ''} · "
                           f"{label(r.months[0])} to {label(r.months[-1])} · scenario: {r.scenario.name}", SMALL))
    story.append(Spacer(1, 10))
    peak_where = f"{s['peak_load_wc']} {label(s['peak_load_month'])}" if s["peak_load_month"] else ""
    tiles = [["Critical alerts", f"Peak load ({peak_where})", "Overloaded WC-months", "Inventory value now", "E&O risk items", "Absolute attainment (3 mo)"],
             [str(s["alerts_critical"]), f"{s['peak_load_pct']:.0f}%",
              str(s["overloaded_months"]), _fmt(s["inventory_value_start"], "money"), str(s["eo_risk_items"]),
              _fmt(s["absolute_attainment_pct"], "pct1")]]
    t = Table(tiles, colWidths=[1.66 * inch] * 6)
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, 0), "Helvetica", 8), ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
                           ("FONT", (0, 1), (-1, 1), "Helvetica-Bold", 14), ("TEXTCOLOR", (0, 1), (-1, 1), INK),
                           ("BOX", (0, 0), (-1, -1), .5, LINE), ("INNERGRID", (0, 0), (-1, -1), .5, LINE),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    story.append(t)
    story.append(Spacer(1, 12))
    story.append(Paragraph("Decisions and risks", H2))
    top = r.alerts[r.alerts["severity"].isin(["Critical", "Warning"])].head(14)
    rows = [["Severity", "Area", "Month", "What the plan shows", "Suggested action"]]
    for a in top.itertuples():
        rows.append([a.severity, a.category, label(a.month) if a.month else "", Paragraph(a.message, CELL), Paragraph(a.suggested_action, CELL)])
    tb = _table(rows, [0.75 * inch, 0.95 * inch, 0.6 * inch, 4.6 * inch, 3.1 * inch])
    for i, a in enumerate(top.itertuples(), start=1):
        tb.setStyle(TableStyle([("BACKGROUND", (0, i), (0, i), SEV.get(a.severity, colors.white))]))
    story.append(tb)
    story.append(PageBreak())

    # Page 2: capacity
    story.append(Paragraph("Capacity: is the plan feasible?", H2))
    months = r.months
    heat = [["Work center"] + [label(m) for m in months]]
    for wc, g in r.capacity.groupby("work_center", sort=False):
        heat.append([wc] + [f"{v:.0f}" for v in g["load_pct"]])
    ht = _table(heat, [0.8 * inch] + [0.51 * inch] * len(months), font=7)
    for i, (_wc, g) in enumerate(r.capacity.groupby("work_center", sort=False), start=1):
        for j, v in enumerate(g["load_pct"], start=1):
            fill = RED if v > r.settings.capacity_critical_pct else AMBER if v >= r.settings.capacity_warning_pct else GREEN if v > 0 else colors.white
            ht.setStyle(TableStyle([("BACKGROUND", (j, i), (j, i), fill), ("ALIGN", (1, 0), (-1, -1), "CENTER")]))
    story.append(ht)
    story.append(Paragraph("Load % = required hours ÷ available hours. Red above "
                           f"{r.settings.capacity_critical_pct:.0f}%, amber from {r.settings.capacity_warning_pct:.0f}%.", SMALL))
    story.append(Spacer(1, 8))
    if not r.utilization.empty:
        peak_wc = r.utilization.sort_values("peak_load_pct").iloc[-1]["work_center"]
        story.append(KeepTogether([Paragraph(f"{peak_wc}: load by month", BODY), _load_chart(r, peak_wc)]))
        rows = [["Work center", "Average load", "Peak load", "Peak month", "Months ≥ warning", "Months over capacity"]]
        for u in r.utilization.itertuples():
            rows.append([f"{u.work_center} {u.name}", _fmt(u.avg_load_pct, "pct"), _fmt(u.peak_load_pct, "pct"), label(u.peak_month),
                         u.months_over_warning, u.months_over_critical])
        story.append(_table(rows, [3.4 * inch, 1.1 * inch, 1.1 * inch, 1.1 * inch, 1.3 * inch, 1.5 * inch]))
    story.append(PageBreak())

    # Page 3: inventory
    story.append(Paragraph("Inventory health: weeks of coverage (finished goods)", H2))
    fg = r.items[r.items["item_type"] == "FG"]
    picks = [m for i, m in enumerate(months) if i in (0, 2, 5, 8, 11, 14)]
    rows = [["Item", "Description"] + [label(m) for m in picks] + ["Status"]]
    inv = r.inventory.set_index(["item_id", "month"])
    for it in fg.itertuples():
        vals = [inv.loc[(it.item_id, m), "weeks_of_coverage"] if (it.item_id, m) in inv.index else np.nan for m in picks]
        stat = r.inventory[(r.inventory["item_id"] == it.item_id)]["status"]
        worst = "Shortage" if (stat == "Shortage").any() else "E&O risk" if stat.isin(["E&O risk", "No demand"]).any() \
            else "Below safety stock" if (stat == "Below safety stock").any() else "Healthy"
        rows.append([it.item_id, Paragraph(it.description, CELL)] + [_fmt(v, "w") for v in vals] + [worst])
    tb = _table(rows, [0.8 * inch, 2.6 * inch] + [0.85 * inch] * len(picks) + [1.4 * inch])
    for i in range(1, len(rows)):
        st = rows[i][-1]
        tb.setStyle(TableStyle([("BACKGROUND", (-1, i), (-1, i), RED if st == "Shortage" else AMBER if st != "Healthy" else GREEN),
                                ("ALIGN", (2, 0), (-2, -1), "RIGHT")]))
    story.append(tb)
    story.append(Paragraph("Weeks of coverage = projected stock ÷ average weekly demand of the next three months.", SMALL))
    story.append(Spacer(1, 10))
    story.append(KeepTogether([Paragraph("Projected inventory value, all items", BODY), _value_chart(r)]))
    story.append(PageBreak())

    # Page 4: forecast and attainment
    story.append(Paragraph("Forecast bridge: what changed since last month", H2))
    if not r.forecast_bridge.empty:
        rows = [["Item", "Previous", "Current", "Change", "Change %"]]
        for b in r.forecast_bridge.head(12).itertuples():
            rows.append([b.item_id, _fmt(b.previous), _fmt(b.current), f"{b.change:+,.0f}", _fmt(b.change_pct, "pct1")])
        story.append(_table(rows, [1.6 * inch, 1.5 * inch, 1.5 * inch, 1.5 * inch, 1.2 * inch]))
        story.append(Paragraph(f"{r.version} vs {r.previous_version}, over the months both versions cover.", SMALL))
    else:
        story.append(Paragraph("Only one forecast version is loaded, so there is nothing to compare.", BODY))
    story.append(Spacer(1, 10))
    story.append(Paragraph("Plan attainment by month", H2))
    if not r.attainment_month.empty:
        rows = [["Month", "Planned", "Actual", "Net attainment", "Absolute attainment"]]
        for a in r.attainment_month.sort_values("month").itertuples():
            rows.append([label(a.month), _fmt(a.planned_qty), _fmt(a.actual_qty), _fmt(a.net_attainment_pct, "pct1"),
                         _fmt(a.absolute_attainment_pct, "pct1")])
        story.append(_table(rows, [1.4 * inch, 1.5 * inch, 1.5 * inch, 1.6 * inch, 1.8 * inch]))
        story.append(Paragraph("Net = Σ actual ÷ Σ plan. Absolute = Σ min(actual, plan) ÷ Σ plan: no credit for over-producing one item to cover another.", SMALL))
    else:
        story.append(Paragraph("No production actuals loaded.", BODY))

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
