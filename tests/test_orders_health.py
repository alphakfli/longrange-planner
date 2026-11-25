import io
from dataclasses import replace

import openpyxl
import pandas as pd
import pytest

from longrange.engine import run_plan
from longrange.io.importer import load_files
from longrange.io.template import template_bytes
from longrange.reports.ibp import ibp_workbook, key_figures
from longrange.sample import build_sample


@pytest.fixture(scope="module")
def sample():
    return build_sample()


@pytest.fixture(scope="module")
def res(sample):
    return run_plan(sample)


def test_plan_itself_is_unchanged(res):
    s = res.summary()
    assert s["planned_orders"] == 174
    assert round(s["peak_load_pct"], 1) == 130.3
    assert s["alerts_critical"] == 6


def test_open_lines_add_up_to_sales_orders(sample):
    ol = sample.order_lines
    op = ol[ol["status"] == "open"].copy()
    op["month"] = op["confirmed_date"].fillna(op["requested_date"]).dt.strftime("%Y-%m").where(
        op["confirmed_date"].fillna(op["requested_date"]) >= "2026-12-01", "2026-12")
    a = op.groupby(["item_id", "month"])["qty"].sum()
    b = sample.sales_orders.groupby(["item_id", "month"])["qty"].sum()
    pd.testing.assert_series_equal(a.sort_index(), b.sort_index(), check_names=False, check_dtype=False)


def test_retinol_lines_need_the_december_order_firmed(res):
    op = res.orders.open_lines
    ret = op[op["item_id"] == "FG-1003"]
    assert len(ret) == 3 and ret["at_risk"].all()
    assert set(ret["promise_status"]) == {"Needs a planned order firmed"}
    assert (ret["promise_month"] == "2027-03").all()               # first month after the frozen zone
    assert (ret["promise_month_if_firmed"] == "2026-12").all()
    pl = res.planned_orders[(res.planned_orders["item_id"] == "FG-1003") & (res.planned_orders["due_month"] == "2026-12")]
    assert ret["action"].str.contains(pl.iloc[0]["planned_id"]).all()


def test_plan_basis_promises_against_all_supply(sample):
    r = run_plan(sample, settings=replace(sample.settings, atp_basis="plan"))
    assert r.orders.kpis["at_risk_lines"] == 0


def test_past_due_and_backlog(res):
    k = res.orders.kpis
    op = res.orders.open_lines
    assert k["past_due_lines"] == 3
    assert set(op.loc[op["past_due"], "order_id"]) == {"SO-260004", "SO-260014", "SO-260015"}
    assert k["backlog_value"] == pytest.approx(op["value"].sum())
    assert op.loc[op["order_id"] == "SO-260015", "days_past_due"].iloc[0] == 34


def test_otif_definitions():
    d = build_sample()
    lines = pd.DataFrame([
        # on time, in full
        dict(order_id="A", line=10, customer="C", item_id="FG-1001", qty=100, requested_date="2026-11-10",
             confirmed_date="2026-11-10", shipped_date="2026-11-09", shipped_qty=100, status="shipped"),
        # on time vs confirmed, late vs requested
        dict(order_id="B", line=10, customer="C", item_id="FG-1001", qty=100, requested_date="2026-11-05",
             confirmed_date="2026-11-12", shipped_date="2026-11-12", shipped_qty=100, status="shipped"),
        # late and short
        dict(order_id="C", line=10, customer="C", item_id="FG-1001", qty=100, requested_date="2026-11-10",
             confirmed_date="2026-11-10", shipped_date="2026-11-15", shipped_qty=80, status="shipped"),
        dict(order_id="D", line=10, customer="C", item_id="FG-1001", qty=100, requested_date="2026-11-10",
             confirmed_date="2026-11-10", shipped_date=None, shipped_qty=0, status="cancelled"),
    ])
    for c in ("requested_date", "confirmed_date", "shipped_date"):
        lines[c] = pd.to_datetime(lines[c])
    lines["unit_price"] = 0.0
    lines["order_date"] = pd.NaT
    k = run_plan(replace(d, order_lines=lines)).orders.kpis
    assert k["lines_shipped"] == 3
    assert k["otif_confirmed_pct"] == pytest.approx(200 / 3)
    assert k["otif_requested_pct"] == pytest.approx(100 / 3)
    assert k["fill_rate_pct"] == pytest.approx(280 / 300 * 100)


def test_data_health_flags_and_score(sample):
    h, hk = run_plan(sample).data_health, run_plan(sample).health_kpis
    fail = set(h.loc[h["status"] == "Fix", "check_id"])
    assert fail == {"D11", "D13", "D14"}
    assert hk["score"] == pytest.approx(100 * (31 - 6) / 31)
    items = sample.items.copy()
    items.loc[items["item_id"] == "PKG-3001", "vendor"] = ""
    items.loc[items["item_id"] == "RAW-4005", "lead_time_weeks"] = 0
    r2 = run_plan(replace(sample, items=items))
    f2 = r2.data_health.set_index("check_id")
    assert f2.loc["D03", "examples"] == "PKG-3001" and f2.loc["D04", "examples"] == "RAW-4005"
    assert r2.health_kpis["score"] < hk["score"]


def test_supply_review_covers_the_functions(res):
    rv = res.review
    assert {"Manufacturing", "Procurement", "Logistics", "Customer service", "Business management", "Supply chain"} <= set(rv["group"])
    assert rv[rv["group"] == "Customer service"]["topic"].str.contains("SO-260010").any()


def test_ibp_key_figures_match_the_plan(res):
    kf = key_figures(res)
    cd = kf[(kf["key_figure"] == "Consensus Demand") & (kf["product_or_resource"] == "FG-1001")]["value"].sum()
    assert cd == pytest.approx(res.planned_forecast.loc[res.planned_forecast["item_id"] == "FG-1001", "qty"].sum())
    use = kf[kf["key_figure"] == "Capacity Usage"]["value"].sum()
    assert use == pytest.approx(res.capacity["required_hours"].sum())
    wb = openpyxl.load_workbook(io.BytesIO(ibp_workbook(res, res.orders, (res.data_health, res.health_kpis), res.review)))
    names = {t for ws in wb for t in ws.tables}
    assert {"tbl_key_figures", "tbl_planning_view", "tbl_open_order_lines", "tbl_data_health", "tbl_supply_review"} <= names


def test_order_lines_round_trip(sample, res):
    data, issues = load_files({"in.xlsx": template_bytes(sample)})
    assert not [i for i in issues if i.severity == "error"]
    assert len(data.order_lines) == len(sample.order_lines)
    r2 = run_plan(data)
    assert r2.orders.kpis["at_risk_lines"] == res.orders.kpis["at_risk_lines"]
    assert r2.orders.kpis["otif_confirmed_pct"] == pytest.approx(res.orders.kpis["otif_confirmed_pct"])


def test_app_smoke():
    from pathlib import Path

    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"), default_timeout=180)
    at.run()
    assert not at.exception
    assert "OTIF vs confirmed date" in [m.label for m in at.metric]
