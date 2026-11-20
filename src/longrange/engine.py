"""Run a complete long-term plan: the one function the dashboard, CLI and reports call."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from longrange.forecast.accuracy import accuracy_report, compare_versions
from longrange.forecast.stats import ItemForecast, statistical_forecast
from longrange.models import PlanningData, Settings
from longrange.months import month_range, months_between
from longrange.planning.alerts import build_alerts
from longrange.planning.capacity import available_hours, capacity_load
from longrange.planning.inventory import inventory_health
from longrange.planning.kpi import attainment, utilization_summary
from longrange.planning.netting import run_netting
from longrange.planning.safety_stock import safety_stock_table


@dataclass
class Scenario:
    """What-if changes applied on top of the data, without editing it."""

    name: str = "Base plan"
    demand_factor: float = 1.0                                     # e.g. 1.15 = +15% on all forecast
    item_factors: dict[str, float] = field(default_factory=dict)   # per item multiplier
    shifts: dict[str, float] = field(default_factory=dict)         # work center -> shifts
    efficiency: dict[str, float] = field(default_factory=dict)     # work center -> efficiency %
    routing: dict[str, str] = field(default_factory=dict)          # item -> work center
    outsource: list[str] = field(default_factory=list)             # items switched to buy


@dataclass
class PlanResult:
    settings: Settings
    scenario: Scenario
    months: list[str]
    version: str
    previous_version: str | None
    items: pd.DataFrame
    safety: pd.DataFrame
    time_phased: pd.DataFrame
    planned_orders: pd.DataFrame
    action_messages: pd.DataFrame
    supply: pd.DataFrame
    capacity: pd.DataFrame
    capacity_detail: pd.DataFrame
    utilization: pd.DataFrame
    inventory: pd.DataFrame
    forecast_bridge: pd.DataFrame
    accuracy: pd.DataFrame
    stat_forecast: pd.DataFrame
    stat_details: list[ItemForecast]
    attainment_month: pd.DataFrame
    attainment_item: pd.DataFrame
    alerts: pd.DataFrame
    issues: list[str]

    def summary(self) -> dict:
        fg = set(self.items.loc[self.items["item_type"] == "FG", "item_id"])
        inv = self.inventory
        first = inv[inv["month"] == self.months[0]]
        last = inv[inv["month"] == self.months[-1]]
        fg_inv = inv[inv["item_id"].isin(fg)]
        woc = fg_inv[np.isfinite(fg_inv["weeks_of_coverage"])].groupby("month")["weeks_of_coverage"].median()
        att = self.attainment_month.sort_values("month").tail(3)
        counts = self.alerts["severity"].value_counts().to_dict() if not self.alerts.empty else {}
        return {
            "horizon": f"{self.months[0]} to {self.months[-1]}",
            "version": self.version,
            "alerts_critical": int(counts.get("Critical", 0)),
            "alerts_warning": int(counts.get("Warning", 0)),
            "alerts_info": int(counts.get("Info", 0)),
            "planned_orders": len(self.planned_orders),
            "peak_load_pct": float(self.capacity["load_pct"].max()) if not self.capacity.empty else 0.0,
            "peak_load_wc": self.capacity.loc[self.capacity["load_pct"].idxmax(), "work_center"] if not self.capacity.empty else "",
            "peak_load_month": self.capacity.loc[self.capacity["load_pct"].idxmax(), "month"] if not self.capacity.empty else "",
            "overloaded_months": int((self.capacity["load_pct"] > self.settings.capacity_critical_pct).sum()) if not self.capacity.empty else 0,
            "inventory_value_start": float(first["inventory_value"].sum()),
            "inventory_value_end": float(last["inventory_value"].sum()),
            "median_fg_woc_start": float(woc.iloc[0]) if len(woc) else float("nan"),
            "fg_shortage_items": int(fg_inv[fg_inv["status"] == "Shortage"]["item_id"].nunique()),
            "eo_risk_items": int(inv[inv["status"].isin(["E&O risk", "No demand"])]["item_id"].nunique()),
            "net_attainment_pct": float(att["actual_qty"].sum() / att["planned_qty"].sum() * 100) if len(att) else float("nan"),
            "absolute_attainment_pct": float(att["capped_actual"].sum() / att["planned_qty"].sum() * 100) if len(att) else float("nan"),
        }


def _series(df: pd.DataFrame, months: list[str], value: str = "qty") -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    if df.empty:
        return out
    idx = {m: i for i, m in enumerate(months)}
    for item, g in df.groupby("item_id"):
        arr = np.zeros(len(months))
        for m, q in zip(g["month"], g[value], strict=False):
            if m in idx:
                arr[idx[m]] += float(q)
        out[item] = arr
    return out


def resolve_versions(data: PlanningData, version: str | None) -> tuple[str, str | None]:
    versions = data.forecast_versions()
    if not versions:
        raise ValueError("No forecast versions in the data.")
    current = version or data.settings.current_forecast or versions[-1]
    if current not in versions:
        raise ValueError(f"Forecast version '{current}' not found. Available: {', '.join(versions)}")
    prev = data.settings.previous_forecast
    if not prev or prev not in versions or prev == current:
        earlier = [v for v in versions if v < current]
        prev = earlier[-1] if earlier else None
    return current, prev


def run_plan(data: PlanningData, version: str | None = None, scenario: Scenario | None = None,
             settings: Settings | None = None) -> PlanResult:
    s = settings or data.settings
    sc = scenario or Scenario()
    current, prev = resolve_versions(data, version)
    fc = data.forecast[data.forecast["version"] == current]
    start = s.plan_start or fc["month"].min()
    months = month_range(start, s.horizon_months)
    H = len(months)

    items = data.items.copy()
    for item in sc.outsource:
        items.loc[items["item_id"] == item, "replenishment"] = "buy"
    bom = data.bom[~data.bom["parent_item"].isin(sc.outsource)]

    # Demand
    fc = fc.copy()
    fc["qty"] = fc["qty"] * sc.demand_factor * fc["item_id"].map(sc.item_factors).fillna(1.0)
    forecast = _series(fc, months)
    sales = _series(data.sales_orders, months)
    independent = {}
    for item in set(forecast) | set(sales):
        independent[item] = np.maximum(forecast.get(item, np.zeros(H)), sales.get(item, np.zeros(H)))

    # Statistical baseline and accuracy feed safety stock sigma
    history = data.sales_history
    stat_fc, stat_details = statistical_forecast(history, start, H) if not history.empty else (pd.DataFrame(), [])
    acc = accuracy_report(data.forecast, history)
    sigmas: dict[str, tuple[float, str]] = {}
    if not acc.empty:
        good = acc[(acc["months"] >= 3) & acc["error_std"].notna()].sort_values("months")
        for r in good.itertuples():
            sigmas[r.item_id] = (float(r.error_std), f"forecast error, {r.version}, {r.months} months")
    for d in stat_details:
        if d.item_id not in sigmas and d.error_std:
            sigmas[d.item_id] = (float(d.error_std), f"statistical backtest error, {d.method}")
    safety = safety_stock_table(items, sigmas, s.default_service_level, s.weeks_per_month)
    ss_map = dict(zip(safety["item_id"], safety["safety_stock"], strict=False))

    # Netting
    net = run_netting(items, bom, independent, sales, forecast, data.supply_orders, ss_map, months,
                      s.frozen_months, s.slushy_months, s.weeks_per_month)

    # Capacity
    avail = available_hours(data.work_centers, data.calendar, months, sc.shifts, sc.efficiency)
    routings = data.routings[~data.routings["item_id"].isin(sc.outsource)]
    load, detail = capacity_load(net.supply, routings, avail, months, sc.routing)
    util = utilization_summary(load, s.capacity_warning_pct, s.capacity_critical_pct)

    inv = inventory_health(net.time_phased, items, s.weeks_per_month, s.eo_coverage_share, s.max_weeks_of_coverage)
    bridge = compare_versions(data.forecast, current, prev, months) if prev else pd.DataFrame(
        columns=["item_id", "previous", "current", "change", "change_pct"])
    att_m, att_i = attainment(data.production_actuals)

    issues = list(net.issues)
    if not data.supply_orders.empty:
        beyond = data.supply_orders[data.supply_orders["due_month"].map(lambda m: months_between(start, m) >= H)]
        if len(beyond):
            issues.append(f"{len(beyond)} supply order(s) are due after the horizon and were ignored.")
    alerts = build_alerts(items=items, inventory=inv, load=load, planned_orders=net.planned_orders,
                          action_messages=net.action_messages, forecast_bridge=bridge, attainment_by_month=att_m,
                          safety=safety, issues=issues, settings=s)
    return PlanResult(settings=s, scenario=sc, months=months, version=current, previous_version=prev, items=items,
                      safety=safety, time_phased=net.time_phased, planned_orders=net.planned_orders,
                      action_messages=net.action_messages, supply=net.supply, capacity=load, capacity_detail=detail,
                      utilization=util, inventory=inv, forecast_bridge=bridge, accuracy=acc, stat_forecast=stat_fc,
                      stat_details=stat_details, attainment_month=att_m, attainment_item=att_i, alerts=alerts,
                      issues=issues)
