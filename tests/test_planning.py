import numpy as np
import pandas as pd
import pytest

from longrange.engine import Scenario, run_plan
from longrange.models import PlanningData, Settings
from longrange.months import add_months, month_range, normalize_month, weeks_to_months
from longrange.planning.capacity import available_hours
from longrange.planning.kpi import attainment
from longrange.planning.netting import lot_size, low_level_codes
from longrange.planning.safety_stock import safety_stock, z_value
from longrange.sample import build_sample


def tiny(**item_overrides) -> PlanningData:
    """One finished good made from one bulk, on one line, flat demand of 100 a month."""
    item = {"item_id": "FG", "description": "Serum", "item_type": "FG", "replenishment": "make", "uom": "EA",
            "on_hand": 150.0, "safety_stock": 50.0, "service_level": np.nan, "lead_time_weeks": 0.0,
            "safety_lead_time_weeks": 0.0, "min_order_qty": 0.0, "order_multiple": 0.0, "max_order_qty": 0.0,
            "lot_accum_months": 1.0, "shelf_life_months": 24.0, "unit_cost": 2.0, "vendor": "", "abc": "A"}
    item.update(item_overrides)
    bulk = dict(item, item_id="BLK", item_type="BULK", on_hand=0.0, safety_stock=0.0, shelf_life_months=0.0)
    months = month_range("2027-01", 6)
    return PlanningData(
        items=pd.DataFrame([item, bulk]),
        bom=pd.DataFrame([{"parent_item": "FG", "component_item": "BLK", "qty_per": 0.5, "scrap_pct": 0.0}]),
        work_centers=pd.DataFrame([{"work_center": "L1", "name": "Line", "shifts": 1.0, "hours_per_shift": 8.0,
                                    "working_days_per_month": 20.0, "efficiency_pct": 100.0}]),
        routings=pd.DataFrame([{"item_id": "FG", "work_center": "L1", "units_per_hour": 1.0, "setup_hours": 0.0, "priority": 1.0}]),
        forecast=pd.DataFrame([{"version": "V1", "item_id": "FG", "month": m, "qty": 100.0} for m in months]),
        settings=Settings(plan_start="2027-01", horizon_months=6, frozen_months=1, slushy_months=2),
    )


def test_months():
    assert normalize_month("Nov 2026") == "2026-11"
    assert normalize_month("11/2026") == "2026-11"
    assert normalize_month(pd.Timestamp("2026-11-15")) == "2026-11"
    assert add_months("2026-12", 1) == "2027-01"
    assert weeks_to_months(2) == 0 and weeks_to_months(6) == 1 and weeks_to_months(10) == 2


def test_lot_size():
    assert lot_size(1200, 2000, 1000) == 2000
    assert lot_size(2300, 2000, 1000) == 3000
    assert lot_size(17, 0, 0) == 17


def test_low_level_codes_and_loop():
    bom = pd.DataFrame({"parent_item": ["A", "B", "A"], "component_item": ["B", "C", "C"]})
    llc, issues = low_level_codes(["A", "B", "C"], bom)
    assert llc == {"A": 0, "B": 1, "C": 2} and not issues
    _, issues = low_level_codes(["A", "B"], pd.DataFrame({"parent_item": ["A", "B"], "component_item": ["B", "A"]}))
    assert issues


def test_safety_stock_formula():
    assert z_value(0.95) == pytest.approx(1.645, abs=1e-3)
    # sigma 7,750, lead time 0 months + 1 review month -> 1.645 * 7750
    assert safety_stock(7750, 0.95, 0) == pytest.approx(1.645 * 7750, rel=1e-3)
    assert safety_stock(0, 0.95, 1) == 0


def test_netting_flat_demand():
    r = run_plan(tiny())
    tp = r.time_phased[r.time_phased["item_id"] == "FG"]
    # 150 on hand, 100/month, SS 50: month 1 ends at 50 (no order), then 100 planned each month
    assert tp["planned_receipts"].tolist() == [0, 100, 100, 100, 100, 100]
    assert (tp["projected_available"] >= 50 - 1e-9).all()
    # Bulk dependent demand = 0.5 per FG unit, same month (no lead time)
    blk = r.time_phased[r.time_phased["item_id"] == "BLK"]
    assert blk["dependent_demand"].tolist() == [0, 50, 50, 50, 50, 50]


def test_min_and_multiple_and_accumulation():
    r = run_plan(tiny(min_order_qty=250, order_multiple=50, lot_accum_months=2))
    po = r.planned_orders[r.planned_orders["item_id"] == "FG"]
    assert (po["qty"] >= 250).all() and (po["qty"] % 50 == 0).all()


def test_lead_time_offsets_release_and_flags_past():
    r = run_plan(tiny(lead_time_weeks=9, on_hand=60))  # 2-month lead time; short in month 1
    po = r.planned_orders[r.planned_orders["item_id"] == "FG"]
    assert (po["due_index"] - po["release_index"] == 2).all()
    assert po["release_in_past"].iloc[0]
    assert (r.alerts["category"] == "Late release").any()


def test_existing_order_cancelled_when_not_needed():
    d = tiny(on_hand=2000)
    d.supply_orders = pd.DataFrame([{"order_id": "P1", "item_id": "FG", "order_type": "production", "status": "firm",
                                     "due_month": "2027-04", "qty": 300.0}])
    r = run_plan(d)
    am = r.action_messages
    assert am.iloc[0]["action"] == "Cancel" and am.iloc[0]["order_id"] == "P1"


def test_frozen_order_is_kept():
    d = tiny(on_hand=2000)
    d.supply_orders = pd.DataFrame([{"order_id": "P1", "item_id": "FG", "order_type": "production", "status": "firm",
                                     "due_month": "2027-01", "qty": 300.0}])
    r = run_plan(d)
    assert r.action_messages.iloc[0]["action"] == "Review (frozen)"


def test_capacity_and_overload_alert():
    r = run_plan(tiny())
    # 1 shift x 8 h x 20 days = 160 h; 100 units at 1/h = 100 h -> 62.5%
    assert r.capacity["available_hours"].iloc[0] == 160
    assert r.capacity["load_pct"].iloc[1] == pytest.approx(62.5)
    r2 = run_plan(tiny(), scenario=Scenario(demand_factor=2.0))
    assert (r2.alerts["category"] == "Capacity").any()


def test_shift_override_changes_capacity():
    wc = tiny().work_centers
    a = available_hours(wc, pd.DataFrame(columns=["work_center", "month", "working_days"]), ["2027-01"], {"L1": 2})
    assert a["available_hours"].iloc[0] == 320


def test_attainment_net_vs_absolute():
    df = pd.DataFrame({"item_id": ["A", "B", "C", "D"], "month": ["2026-10"] * 4,
                       "planned_qty": [70000, 48000, 25000, 42000], "actual_qty": [66500, 51000, 19000, 42000]})
    by_month, _ = attainment(df)
    row = by_month.iloc[0]
    assert row["net_attainment_pct"] == pytest.approx(178500 / 185000 * 100)
    assert row["absolute_attainment_pct"] == pytest.approx(175500 / 185000 * 100)


def test_sample_plan_shows_expected_problems():
    r = run_plan(build_sample())
    s = r.summary()
    assert s["peak_load_wc"] == "FL1" and s["peak_load_pct"] > 100
    assert (r.alerts["category"] == "E&O risk").any()
    assert set(r.forecast_bridge["item_id"]) >= {"FG-1002", "FG-1003"}
    assert len(r.months) == 18
