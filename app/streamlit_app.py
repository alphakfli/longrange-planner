"""LongRange Planner dashboard.  Run:  streamlit run app/streamlit_app.py"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from longrange.engine import Scenario, run_plan
from longrange.forecast.accuracy import compare_versions_monthly
from longrange.io.importer import load_files
from longrange.io.template import template_bytes
from longrange.months import label
from longrange.reports import excel_report, pdf_report
from longrange.sample import build_sample

st.set_page_config(page_title="LongRange Planner", page_icon="📈", layout="wide")

ACCENT, RED, AMBER, GREEN, GREY = "#0D5D6E", "#B4372A", "#C98A2B", "#2B7A4B", "#9AA8A3"
ITEM_COLORS = ["#0D5D6E", "#5DB4C6", "#2B7A4B", "#8FC9A3", "#6B6FB5", "#B5A8D6", "#7A8C86", "#C7D3CE"]
SEV_COLOR = {"Critical": "🔴", "Warning": "🟠", "Info": "🔵"}
st.markdown("""<style>
.block-container{padding-top:1.4rem}
div[data-testid="stMetricValue"]{font-size:1.7rem}
</style>""", unsafe_allow_html=True)


# ---------- data ----------
@st.cache_data(show_spinner=False)
def _load_upload(files: tuple[tuple[str, bytes], ...]):
    return load_files(dict(files))


@st.cache_data(show_spinner=False)
def _sample():
    return build_sample()


def _fig_layout(fig, height=340, **kw):
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=30, b=10), plot_bgcolor="white", colorway=ITEM_COLORS,
                      legend=dict(orientation="h", y=1.08, x=0), font=dict(size=12), **kw)
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="#E6ECE9")
    return fig


with st.sidebar:
    st.header("Data")
    src = st.radio("Source", ["Sample data", "Upload Excel or CSV"], label_visibility="collapsed")
    issues = []
    if src == "Sample data":
        data = _sample()
        st.caption("Northfield Skincare: a fictional cosmetics plant with 6 finished goods, 3 work centers and 2 forecast versions.")
    else:
        up = st.file_uploader("One .xlsx workbook, or CSV files named items.csv, forecast.csv …",
                              type=["xlsx", "xlsm", "csv"], accept_multiple_files=True)
        st.download_button("Download blank template", template_bytes(), "longrange_input_template.xlsx", width="stretch")
        if not up:
            st.info("Upload your data to start, or switch to the sample data.")
            st.stop()
        data, issues = _load_upload(tuple((f.name, f.getvalue()) for f in up))
        errors = [i for i in issues if i.severity == "error"]
        if errors:
            st.error(f"{len(errors)} error(s) in the data. See the Data check tab.")

    versions = data.forecast_versions()
    if not versions:
        st.error("No forecast versions found.")
        st.stop()
    default_v = data.settings.current_forecast if data.settings.current_forecast in versions else versions[-1]
    version = st.selectbox("Forecast version", versions, index=versions.index(default_v))

    st.header("Settings")
    s0 = data.settings
    horizon = st.slider("Horizon (months)", 6, 24, int(s0.horizon_months))
    frozen = st.slider("Frozen zone (months)", 0, 6, int(s0.frozen_months))
    service = st.slider("Service level for calculated safety stock", 0.80, 0.995, float(s0.default_service_level), 0.005, format="%.3f")
    settings = replace(s0, horizon_months=horizon, frozen_months=frozen, slushy_months=max(frozen, s0.slushy_months),
                       default_service_level=service, current_forecast=version)

    st.header("What-if")
    demand = st.slider("Demand change, all items", -30, 50, 0, 5, format="%d%%")
    wcs = data.work_centers
    shifts = {}
    if not wcs.empty:
        with st.expander("Shifts per work center"):
            for wc in wcs.itertuples():
                v = st.number_input(f"{wc.work_center} {wc.name}", 1.0, 3.0, float(wc.shifts), 1.0, key=f"sh_{wc.work_center}")
                if v != wc.shifts:
                    shifts[wc.work_center] = v
    routing = {}
    alt = data.routings.groupby("item_id")["work_center"].nunique() if not data.routings.empty else pd.Series(dtype=int)
    multi = alt[alt > 1].index.tolist()
    if multi:
        with st.expander("Move items to another line"):
            for item in multi:
                opts = data.routings[data.routings["item_id"] == item].sort_values("priority")["work_center"].tolist()
                v = st.selectbox(item, opts, key=f"rt_{item}")
                if v != opts[0]:
                    routing[item] = v
    makes = data.items.loc[data.items["replenishment"] == "make"]
    with st.expander("Outsource items"):
        outsource = st.multiselect("Buy these from a contract manufacturer instead",
                                   makes.loc[makes["item_type"] == "FG", "item_id"].tolist())
    changed = demand or shifts or routing or outsource
    scen = Scenario(name="What-if" if changed else "Base plan", demand_factor=1 + demand / 100,
                    shifts=shifts, routing=routing, outsource=outsource)

try:
    r = run_plan(data, version=version, scenario=scen, settings=settings)
except Exception as e:  # show data problems instead of a stack trace
    st.error(f"The plan could not run: {e}")
    st.stop()
S = r.summary()
months = r.months
mlabels = [label(m) for m in months]

# ---------- header ----------
st.title("Long-term production plan")
st.caption(f"Forecast **{r.version}**" + (f" vs {r.previous_version}" if r.previous_version else "") +
           f" · {label(months[0])} to {label(months[-1])} · {r.scenario.name}")
c = st.columns(6)
c[0].metric("Critical alerts", S["alerts_critical"])
c[1].metric(f"Peak load · {S['peak_load_wc']} {label(S['peak_load_month'])}" if S["peak_load_month"] else "Peak load",
            f"{S['peak_load_pct']:.0f}%")
c[2].metric("Overloaded WC-months", S["overloaded_months"])
c[3].metric("Inventory value now", f"${S['inventory_value_start'] / 1000:,.0f}k")
c[4].metric("E&O risk items", S["eo_risk_items"])
c[5].metric("Absolute attainment (3 mo)", "–" if np.isnan(S["absolute_attainment_pct"]) else f"{S['absolute_attainment_pct']:.1f}%")

tabs = st.tabs(["Overview", "Alerts", "Forecast", "MPS / MRP", "Capacity", "Inventory", "KPIs", "Data check", "Export"])

# ---------- Overview ----------
with tabs[0]:
    left, right = st.columns([3, 2])
    with left:
        st.subheader("Capacity load by work center")
        cap = r.capacity.pivot_table(index="work_center", columns="month", values="load_pct", sort=False)
        z = cap.to_numpy()
        fig = go.Figure(go.Heatmap(z=z, x=mlabels, y=cap.index, text=np.round(z).astype(int), texttemplate="%{text}%",
                                   colorscale=[[0, "#EEF4F2"], [.6, "#DDF0E3"], [.75, "#F6EAD2"], [.85, "#F0B9AF"], [1, RED]],
                                   zmin=0, zmax=max(130, float(np.nanmax(z)) if z.size else 130), showscale=False,
                                   hovertemplate="%{y} %{x}: %{z:.0f}%<extra></extra>"))
        st.plotly_chart(_fig_layout(fig, 60 + 46 * len(cap), yaxis_autorange="reversed"), width="stretch")
        st.subheader("Finished goods: weeks of coverage")
        fg = r.items.loc[r.items["item_type"] == "FG", "item_id"]
        inv = r.inventory[r.inventory["item_id"].isin(fg)]
        fig = go.Figure()
        for item, g in inv.groupby("item_id", sort=False):
            fig.add_trace(go.Scatter(x=[label(m) for m in g["month"]], y=g["weeks_of_coverage"].replace([np.inf], np.nan),
                                     name=item, mode="lines"))
        st.plotly_chart(_fig_layout(fig, 300, yaxis_title="weeks"), width="stretch")
    with right:
        st.subheader("Top alerts")
        top = r.alerts[r.alerts["severity"].isin(["Critical", "Warning"])].head(10)
        if top.empty:
            st.success("No critical or warning alerts.")
        for a in top.itertuples():
            st.markdown(f"{SEV_COLOR[a.severity]} **{a.category}** · {label(a.month) if a.month else ''}  \n{a.message}  \n"
                        f"<span style='color:#56655F'>→ {a.suggested_action}</span>", unsafe_allow_html=True)

# ---------- Alerts ----------
with tabs[1]:
    sev = st.multiselect("Severity", ["Critical", "Warning", "Info"], ["Critical", "Warning", "Info"])
    cats = sorted(r.alerts["category"].unique().tolist()) if not r.alerts.empty else []
    cat = st.multiselect("Area", cats, cats)
    al = r.alerts[r.alerts["severity"].isin(sev) & r.alerts["category"].isin(cat)].copy()
    al["month"] = al["month"].map(lambda m: label(m) if m else "")
    al.insert(0, "", al["severity"].map(SEV_COLOR))
    st.dataframe(al, width="stretch", hide_index=True, height=520,
                 column_config={"message": st.column_config.TextColumn(width="large"),
                                "suggested_action": st.column_config.TextColumn(width="medium")})

# ---------- Forecast ----------
with tabs[2]:
    items_fg = r.items.loc[r.items["item_type"] == "FG", "item_id"].tolist()
    cA, cB = st.columns([1, 3])
    with cA:
        pick = st.selectbox("Item", ["All finished goods", *items_fg])
        show_stat = st.checkbox("Statistical baseline", True)
        show_prev = st.checkbox("Previous version", True)
    with cB:
        hist = data.sales_history
        fc = data.forecast
        if pick != "All finished goods":
            hist, fc = hist[hist["item_id"] == pick], fc[fc["item_id"] == pick]
            stat = r.stat_forecast[r.stat_forecast["item_id"] == pick] if not r.stat_forecast.empty else pd.DataFrame()
        else:
            hist, fc = hist[hist["item_id"].isin(items_fg)], fc[fc["item_id"].isin(items_fg)]
            stat = r.stat_forecast[r.stat_forecast["item_id"].isin(items_fg)] if not r.stat_forecast.empty else pd.DataFrame()
        fig = go.Figure()
        h = hist.groupby("month")["qty"].sum()
        if len(h):
            fig.add_trace(go.Bar(x=[label(m) for m in h.index], y=h.values, name="Actual sales", marker_color=GREY))
        cur = fc[fc["version"] == r.version].groupby("month")["qty"].sum()
        fig.add_trace(go.Scatter(x=[label(m) for m in cur.index], y=cur.values, name=r.version, line=dict(color=ACCENT, width=3)))
        if show_prev and r.previous_version:
            pv = fc[fc["version"] == r.previous_version].groupby("month")["qty"].sum()
            fig.add_trace(go.Scatter(x=[label(m) for m in pv.index], y=pv.values, name=r.previous_version, line=dict(color=AMBER, dash="dash")))
        if show_stat and not stat.empty:
            sv = stat.groupby("month")["qty"].sum()
            fig.add_trace(go.Scatter(x=[label(m) for m in sv.index], y=sv.values, name="Statistical baseline", line=dict(color=GREEN, dash="dot")))
        st.plotly_chart(_fig_layout(fig, 380, yaxis_title="units"), width="stretch")
    st.subheader("Forecast bridge")
    if r.forecast_bridge.empty:
        st.info("Load a second forecast version to compare.")
    else:
        st.caption(f"{r.version} vs {r.previous_version}, over the months both versions cover.")
        st.dataframe(r.forecast_bridge, hide_index=True, width="stretch",
                     column_config={"change_pct": st.column_config.NumberColumn("change %", format="%.1f%%"),
                                    "previous": st.column_config.NumberColumn(format="%d"),
                                    "current": st.column_config.NumberColumn(format="%d"),
                                    "change": st.column_config.NumberColumn(format="%+d")})
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Statistical baseline")
        if r.stat_details:
            st.dataframe(pd.DataFrame([{"item": d.item_id, "method": d.method, "months of history": d.history_months,
                                        "holdout WMAPE": None if d.holdout_wmape is None else d.holdout_wmape * 100}
                                       for d in r.stat_details]), hide_index=True, width="stretch",
                         column_config={"holdout WMAPE": st.column_config.NumberColumn(format="%.1f%%")})
            st.caption("Each item uses the method with the lowest error on the last 6 months of history.")
            if not r.stat_forecast.empty:
                stat_ver = r.stat_forecast.copy()
                stat_ver["version"] = f"STAT-{months[0]}"
                st.download_button("Download baseline as a forecast version (CSV)", stat_ver.to_csv(index=False).encode(),
                                   f"STAT-{months[0]}.csv")
        else:
            st.info("Add sales history to get a statistical baseline.")
    with c2:
        st.subheader("Forecast accuracy")
        if r.accuracy.empty:
            st.info("Accuracy needs forecast versions that overlap months with actual sales.")
        else:
            acc = r.accuracy.copy()
            acc["wmape"] *= 100
            acc["bias"] *= 100
            st.dataframe(acc, hide_index=True, width="stretch",
                         column_config={"wmape": st.column_config.NumberColumn("WMAPE", format="%.1f%%"),
                                        "bias": st.column_config.NumberColumn("bias", format="%+.1f%%")})
    if r.previous_version:
        cm = compare_versions_monthly(data.forecast, r.version, r.previous_version)
        with st.expander("Monthly totals by version"):
            st.dataframe(cm, hide_index=True, width="stretch")

# ---------- MPS / MRP ----------
with tabs[3]:
    names = dict(zip(r.items["item_id"], r.items["description"], strict=False))
    item = st.selectbox("Item", r.items["item_id"].tolist(), format_func=lambda i: f"{i} · {names.get(i, '')}")
    tp = r.time_phased[r.time_phased["item_id"] == item]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=mlabels, y=tp["gross_requirement"], name="Gross requirement", marker_color=GREY))
    fig.add_trace(go.Bar(x=mlabels, y=tp["scheduled_receipts"], name="Existing orders", marker_color="#5DB4C6"))
    fig.add_trace(go.Bar(x=mlabels, y=tp["planned_receipts"], name="New planned orders", marker_color=ACCENT))
    fig.add_trace(go.Scatter(x=mlabels, y=tp["projected_available"], name="Projected available", line=dict(color="#16211F", width=3)))
    fig.add_trace(go.Scatter(x=mlabels, y=tp["safety_stock"], name="Safety stock", line=dict(color=RED, dash="dash")))
    if frozen:
        fig.add_vrect(x0=-0.5, x1=frozen - 0.5, fillcolor="#E9EEEC", opacity=.6, line_width=0, annotation_text="Frozen",
                      annotation_position="top left")
    st.plotly_chart(_fig_layout(fig, 400, barmode="group"), width="stretch")
    grid = tp.set_index("month")[["forecast", "sales_orders", "independent_demand", "dependent_demand", "gross_requirement",
                                  "scheduled_receipts", "planned_receipts", "planned_releases", "projected_available", "safety_stock"]].T
    grid.columns = mlabels
    st.dataframe(grid.round(0), width="stretch")
    ss_row = r.safety[r.safety["item_id"] == item].iloc[0]
    st.caption(f"Safety stock {ss_row['safety_stock']:,.0f}: {ss_row['method']}.")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("New planned orders")
        po = r.planned_orders.drop(columns=["release_index", "due_index"])
        only = st.checkbox("Only this item", True)
        st.dataframe(po[po["item_id"] == item] if only else po, hide_index=True, width="stretch", height=300)
    with c2:
        st.subheader("Changes to existing orders")
        if r.action_messages.empty:
            st.success("No changes suggested.")
        else:
            st.dataframe(r.action_messages, hide_index=True, width="stretch", height=300)

# ---------- Capacity ----------
with tabs[4]:
    st.dataframe(r.utilization, hide_index=True, width="stretch",
                 column_config={"avg_load_pct": st.column_config.NumberColumn("average load", format="%.0f%%"),
                                "peak_load_pct": st.column_config.NumberColumn("peak load", format="%.0f%%")})
    wc = st.selectbox("Work center", r.capacity["work_center"].unique().tolist(),
                      index=int(r.utilization["peak_load_pct"].values.argmax()) if not r.utilization.empty else 0)
    g = r.capacity[r.capacity["work_center"] == wc]
    det = r.capacity_detail[r.capacity_detail["work_center"] == wc]
    fig = go.Figure()
    for itm, gi in det.groupby("item_id"):
        h = gi.groupby("month")["hours"].sum().reindex(months, fill_value=0)
        fig.add_trace(go.Bar(x=mlabels, y=h.values, name=itm))
    fig.add_trace(go.Scatter(x=mlabels, y=g["available_hours"], name="Available hours", line=dict(color=RED, width=2, dash="dash")))
    st.plotly_chart(_fig_layout(fig, 420, barmode="stack", yaxis_title="hours"), width="stretch")
    st.caption("Stacked bars show required hours by item; above the dashed line, the plan is not feasible. "
               "Try the what-if controls in the sidebar: shifts, moving items to another line, or outsourcing.")
    mm = st.select_slider("Breakdown for month", options=months, value=g.loc[g["load_pct"].idxmax(), "month"], format_func=label)
    st.dataframe(det[det["month"] == mm].sort_values("hours", ascending=False).round({"hours": 1}), hide_index=True, width="stretch",
                 column_config={"qty": st.column_config.NumberColumn(format="localized")})

# ---------- Inventory ----------
with tabs[5]:
    inv = r.inventory.copy()
    inv["weeks_of_coverage"] = inv["weeks_of_coverage"].replace([np.inf, -np.inf], np.nan)
    types = st.multiselect("Item types", sorted(r.items["item_type"].unique()), ["FG"])
    keep = r.items.loc[r.items["item_type"].isin(types), "item_id"]
    inv = inv[inv["item_id"].isin(keep)]
    woc = inv.pivot_table(index="item_id", columns="month", values="weeks_of_coverage", sort=False)
    z = woc.to_numpy()
    fig = go.Figure(go.Heatmap(z=z, x=mlabels, y=woc.index, text=np.where(np.isnan(z), "", np.round(z, 1).astype(str)),
                               texttemplate="%{text}", colorscale=[[0, "#F0B9AF"], [.15, "#FFFFFF"], [.6, "#FFFFFF"], [1, "#F0C987"]],
                               zmin=0, zmax=40, showscale=False, hovertemplate="%{y} %{x}: %{z:.1f} weeks<extra></extra>"))
    st.subheader("Weeks of coverage")
    st.plotly_chart(_fig_layout(fig, 70 + 32 * len(woc), yaxis_autorange="reversed"), width="stretch")
    st.caption("Red = low coverage, amber = high coverage (possible excess). Last 3 months are blank where demand beyond the horizon is unknown.")
    val = inv.groupby("month")["inventory_value"].sum()
    fig = go.Figure(go.Scatter(x=[label(m) for m in val.index], y=val.values, fill="tozeroy", line=dict(color=ACCENT)))
    st.subheader("Projected inventory value")
    st.plotly_chart(_fig_layout(fig, 280, yaxis_tickprefix="$"), width="stretch")
    st.subheader("Items needing attention")
    att = inv[inv["status"] != "Healthy"].sort_values(["item_id", "month"]).groupby("item_id").head(1)
    st.dataframe(att, hide_index=True, width="stretch")
    with st.expander("Safety stock by item"):
        st.dataframe(r.safety, hide_index=True, width="stretch")

# ---------- KPIs ----------
with tabs[6]:
    if r.attainment_month.empty:
        st.info("Add production_actuals (planned vs actual by item and month) to see attainment.")
    else:
        am = r.attainment_month.sort_values("month")
        fig = go.Figure()
        fig.add_trace(go.Bar(x=[label(m) for m in am["month"]], y=am["net_attainment_pct"], name="Net attainment", marker_color="#5DB4C6"))
        fig.add_trace(go.Bar(x=[label(m) for m in am["month"]], y=am["absolute_attainment_pct"], name="Absolute attainment", marker_color=ACCENT))
        fig.add_hline(y=settings.attainment_target_pct, line_dash="dash", line_color=RED, annotation_text="Target")
        st.plotly_chart(_fig_layout(fig, 340, barmode="group", yaxis_range=[60, 110], yaxis_ticksuffix="%"), width="stretch")
        st.caption("Net = Σ actual ÷ Σ plan. Absolute = Σ min(actual, plan) ÷ Σ plan: over-producing one item does not hide another's shortfall.")
        st.dataframe(r.attainment_item, hide_index=True, width="stretch",
                     column_config={"net_attainment_pct": st.column_config.NumberColumn("net", format="%.1f%%"),
                                    "absolute_attainment_pct": st.column_config.NumberColumn("absolute", format="%.1f%%")})

# ---------- Data check ----------
with tabs[7]:
    if issues:
        st.dataframe(pd.DataFrame([i.as_dict() for i in issues]), hide_index=True, width="stretch")
    else:
        st.success("No problems found in the input data.")
    if r.issues:
        st.write("Planning notes:")
        for msg in r.issues:
            st.write("• " + msg)
    with st.expander("Loaded tables"):
        for name in ["items", "bom", "work_centers", "routings", "supply_orders", "sales_orders"]:
            st.caption(name)
            st.dataframe(data.table(name), hide_index=True, width="stretch")

# ---------- Export ----------
with tabs[8]:
    st.write("Reports use the plan exactly as shown, including any what-if changes in the sidebar.")
    stem = f"plan_{r.version}{'_whatif' if changed else ''}"
    c1, c2, c3 = st.columns(3)
    c1.download_button("Excel workbook (all views)", excel_report(r), f"{stem}.xlsx", width="stretch", type="primary")
    c2.download_button("PDF: S&OP supply review", pdf_report(r), f"{stem}.pdf", width="stretch", type="primary")
    c3.download_button("Input data as a workbook", template_bytes(data), "planning_data.xlsx", width="stretch")
