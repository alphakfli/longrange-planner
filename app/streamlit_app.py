"""LongRange Planner dashboard.  Run:  streamlit run app/streamlit_app.py"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

# Let the app find the package without installing it (Streamlit Community Cloud runs this file directly).
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

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
        st.caption("Northfield Skincare: a fictional cosmetics plant with 6 finished goods, 3 work centers, 2 current forecast versions and 2 archived ones for accuracy.")
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
    if data.settings.plan_start and not data.forecast.empty:   # hide archived versions with no future months
        future = data.forecast.loc[data.forecast["month"] >= data.settings.plan_start, "version"].unique()
        versions = [v for v in versions if v in future] or versions
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
    policies = {"single": "One level for all items", "abc_xyz": "By ABC / XYZ segment"}
    policy = st.radio("Service level policy", list(policies), format_func=policies.get,
                      index=list(policies).index(s0.service_level_policy if s0.service_level_policy in policies else "single"),
                      help="By segment uses the matrix on the Inventory tab. A service level or safety stock given on the item always wins.")
    settings = replace(s0, horizon_months=horizon, frozen_months=frozen, slushy_months=max(frozen, s0.slushy_months),
                       default_service_level=service, current_forecast=version, service_level_policy=policy)

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
    ev = data.events
    include_proposed, excluded = False, []
    if not ev.empty:
        with st.expander("Demand events", expanded=True):
            proposed = ev[ev["status"].astype(str).str.lower() == "proposed"]
            approved = ev[ev["status"].astype(str).str.lower() != "proposed"]
            if len(proposed):
                include_proposed = st.checkbox(f"Include proposed events ({len(proposed)})", False,
                                               help="Promotions and launches Marketing or Sales have asked for, not yet approved at S&OP.")
                st.caption(", ".join(f"{e.event_id} {e.event_type} {e.item_id}" for e in proposed.itertuples()))
            if len(approved):
                excluded = st.multiselect("Leave out approved events", approved["event_id"].tolist())
    changed = demand or shifts or routing or outsource or include_proposed or excluded
    scen = Scenario(name="What-if" if changed else "Base plan", demand_factor=1 + demand / 100,
                    shifts=shifts, routing=routing, outsource=outsource,
                    include_proposed_events=include_proposed, excluded_events=excluded)

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
if src == "Sample data":
    st.info("Demo with fictional data from 'Northfield Skincare'. Try the what-if controls in the sidebar, "
            "or upload your own Excel file: it stays in your browser.", icon="ℹ️")
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
        keep_items = items_fg if pick == "All finished goods" else [pick]
        pf = r.planned_forecast[r.planned_forecast["item_id"].isin(keep_items)].groupby("month")["qty"].sum()
        cur_h = cur[cur.index.isin(pf.index)]
        if len(pf) and not np.allclose(pf.reindex(cur_h.index).fillna(0).values, cur_h.values):
            fig.add_trace(go.Scatter(x=[label(m) for m in pf.index], y=pf.values, name="Plan demand (what-if + events)",
                                     line=dict(color="#6B6FB5", width=2)))
        st.plotly_chart(_fig_layout(fig, 380, yaxis_title="units"), width="stretch")

    st.subheader("Demand events")
    if r.events.empty:
        st.info("No events loaded. Add an 'events' sheet to plan promotions, launches and delistings on top of the forecast.")
    else:
        st.caption("Events sit on top of the consensus forecast: forecast × (1 + lift %) + extra units. "
                   "Approved events are in the plan; proposed ones are shown here but only planned when you include them in the sidebar.")
        imp = r.event_impact[r.event_impact["item_id"].isin(keep_items)]
        if not imp.empty:
            fig = go.Figure()
            for i, (eid, g) in enumerate(imp.groupby("event_id", sort=False)):
                gm = g.groupby("month")["event_qty"].sum().reindex(months, fill_value=0)
                fig.add_trace(go.Bar(x=mlabels, y=gm.values, name=f"{eid}{'' if g['applied'].iloc[0] else ' (not in plan)'}",
                                     marker_color=ITEM_COLORS[i % len(ITEM_COLORS)], opacity=1 if g["applied"].iloc[0] else .45))
            st.plotly_chart(_fig_layout(fig, 260, barmode="relative", yaxis_title="units vs forecast"), width="stretch")
        st.dataframe(r.events, hide_index=True, width="stretch",
                     column_config={"applied": st.column_config.CheckboxColumn("in plan"),
                                    "units": st.column_config.NumberColumn(format="%+d"),
                                    "in_frozen_zone": st.column_config.CheckboxColumn("starts in frozen zone"),
                                    "first_month": st.column_config.TextColumn("from"), "last_month": st.column_config.TextColumn("to")})
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

    st.subheader("ABC / XYZ segments and service levels")
    seg = r.segments
    if seg.empty:
        st.info("Segmentation needs finished goods with a forecast and unit cost.")
    else:
        st.caption(f"ABC by forecast value, next 12 months (A = first {settings.abc_a_share:.0%}, B = next "
                   f"{settings.abc_b_share - settings.abc_a_share:.0%}). XYZ by forecast error ÷ average demand "
                   f"(X ≤ {settings.xyz_x_max_cv:.0%}, Y ≤ {settings.xyz_y_max_cv:.0%}, Z above). "
                   f"Policy now: **{policies[policy]}**.")
        cm1, cm2 = st.columns([2, 3])
        with cm1:
            grid = [[getattr(settings, f"sl_{a.lower()}{x.lower()}") for x in "XYZ"] for a in "ABC"]
            names = [[", ".join(seg.loc[seg["segment"] == a + x, "item_id"]) for x in "XYZ"] for a in "ABC"]
            text = [[f"{grid[i][j]:.0%}<br><span style='font-size:10px'>{names[i][j]}</span>" for j in range(3)] for i in range(3)]
            fig = go.Figure(go.Heatmap(z=grid, x=["X steady", "Y variable", "Z erratic"], y=["A high value", "B", "C low value"],
                                       text=text, texttemplate="%{text}", colorscale=[[0, "#F4F7F6"], [1, "#9CCBD6"]],
                                       showscale=False, hovertemplate="%{y} / %{x}: %{z:.0%}<extra></extra>"))
            st.plotly_chart(_fig_layout(fig, 300, yaxis_autorange="reversed"), width="stretch")
            st.caption("Target service level per segment, with the items in each cell.")
        with cm2:
            show = seg[["item_id", "abc_calculated", "abc", "error_cv", "xyz", "segment", "matrix_service_level",
                        "plan_safety_stock", "matrix_safety_stock", "plan_method"]]
            st.dataframe(show, hide_index=True, width="stretch",
                         column_config={"abc_calculated": st.column_config.TextColumn("ABC calc"),
                                        "abc": st.column_config.TextColumn("ABC used"),
                                        "error_cv": st.column_config.NumberColumn("error CV", format="%.2f"),
                                        "matrix_service_level": st.column_config.NumberColumn("segment SL", format="percent"),
                                        "plan_safety_stock": st.column_config.NumberColumn("SS in plan", format="localized"),
                                        "matrix_safety_stock": st.column_config.NumberColumn("SS at segment SL", format="localized"),
                                        "plan_method": st.column_config.TextColumn("SS method")})
            st.caption("ABC used = the class on the item if given, otherwise the calculated one. "
                       "Compare 'SS in plan' with 'SS at segment SL' to find items with too much or too little buffer.")
        with st.expander("Value ranking (Pareto)"):
            fig = go.Figure()
            fig.add_trace(go.Bar(x=seg["item_id"], y=seg["annual_value"], name="Forecast value, 12 months",
                                 marker_color=[{"A": ACCENT, "B": "#5DB4C6", "C": GREY}[a] for a in seg["abc_calculated"]]))
            fig.add_trace(go.Scatter(x=seg["item_id"], y=seg["cum_share_pct"], name="Cumulative share", yaxis="y2",
                                     line=dict(color=AMBER)))
            st.plotly_chart(_fig_layout(fig, 300, yaxis_tickprefix="$",
                                        yaxis2=dict(overlaying="y", side="right", range=[0, 105], ticksuffix="%", showgrid=False)),
                            width="stretch")

# ---------- KPIs ----------
with tabs[6]:
    st.subheader(f"Forecast bias, last {settings.bias_months} months (lag 1)")
    bs, bd = r.bias_summary, r.bias_detail
    if bs.empty:
        st.info("Needs actual sales for recent months and the forecast version that planned each month "
                "(e.g. FC-2026-10 for November). Load your earlier versions to see bias.")
    else:
        lim = settings.bias_alert_pct
        st.caption(f"Each month is judged against the version used to plan it: the one made the month before. "
                   f"Bias = Σ(forecast − actual) ÷ Σ actual. Positive = over-forecast (excess, E&O), negative = "
                   f"under-forecast (shortages). Flag outside ±{lim:.0f}%.")
        order = bs["item_id"].tolist()
        fig = go.Figure(go.Bar(x=order, y=bs["bias"] * 100,
                               marker_color=[RED if f else ("#5DB4C6" if b < 0 else ACCENT) for f, b in zip(bs["flag"], bs["bias"], strict=True)],
                               text=[f"{b:+.1%}" for b in bs["bias"]], textposition="outside",
                               hovertemplate="%{x}: %{y:+.1f}%<extra></extra>"))
        fig.add_hrect(y0=-lim, y1=lim, fillcolor="#E5F4E4", opacity=.5, line_width=0)
        fig.add_hline(y=0, line_color=GREY)
        ymax = max(lim * 1.6, float((bs["bias"].abs() * 100).max()) * 1.3)
        st.plotly_chart(_fig_layout(fig, 300, yaxis_ticksuffix="%", yaxis_range=[-ymax, ymax], showlegend=False), width="stretch")
        piv = bd.pivot_table(index="item_id", columns="month", values="error_pct", aggfunc="sum") * 100
        piv.columns = [label(m) for m in piv.columns]
        tbl = bs.set_index("item_id")[["bias", "wmape", "forecast", "actual", "flag"]].copy()
        tbl[["bias", "wmape"]] *= 100
        tbl = piv.join(tbl).loc[order].reset_index()
        cfg = {c: st.column_config.NumberColumn(c, format="%+.1f%%") for c in piv.columns}
        cfg.update({"bias": st.column_config.NumberColumn(f"{settings.bias_months}-month bias", format="%+.1f%%"),
                    "wmape": st.column_config.NumberColumn("WMAPE", format="%.1f%%"),
                    "forecast": st.column_config.NumberColumn(format="localized"),
                    "actual": st.column_config.NumberColumn(format="localized"),
                    "flag": st.column_config.CheckboxColumn(f"outside ±{lim:.0f}%")})
        st.dataframe(tbl, hide_index=True, width="stretch", column_config=cfg)
        st.caption("Month columns = that month's error % against its lag-1 version. One big month can be a one-off "
                   "or a stock-out; the same sign every month is bias to fix at the source.")
        with st.expander("Which version planned each month"):
            st.dataframe(bd.assign(month=bd["month"].map(label), error_pct=bd["error_pct"] * 100), hide_index=True,
                         width="stretch", column_config={"error_pct": st.column_config.NumberColumn("error %", format="%+.1f%%")})

    st.subheader("Plan attainment")
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
