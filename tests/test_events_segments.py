import pandas as pd

from longrange.engine import Scenario, run_plan
from longrange.forecast.events import apply_events
from longrange.io.importer import load_workbook
from longrange.io.template import template_bytes
from longrange.models import Settings
from longrange.planning.segmentation import classify
from longrange.reports import excel_report, pdf_report
from longrange.sample import build_sample

MONTHS = ["2027-01", "2027-02", "2027-03", "2027-04"]


def _fc():
    return pd.DataFrame([["A", m, 100.0] for m in MONTHS] + [["B", m, 50.0] for m in MONTHS],
                        columns=["item_id", "month", "qty"])


def _events(rows):
    return pd.DataFrame(rows, columns=["event_id", "item_id", "event_type", "start_month", "end_month", "lift_pct",
                                       "extra_qty", "status", "note"])


def test_promo_lift_and_extra_qty():
    ev = _events([["E1", "A", "promo", "2027-02", "2027-03", 20, 0, "approved", ""],
                  ["E2", "B", "launch", "2027-03", None, 0, 30, "approved", ""]])
    out, impact = apply_events(_fc(), ev, ["A", "B"], MONTHS)
    q = out.set_index(["item_id", "month"])["qty"]
    assert q[("A", "2027-01")] == 100 and q[("A", "2027-02")] == 120 and q[("A", "2027-03")] == 120
    assert q[("B", "2027-03")] == 80 and q[("B", "2027-04")] == 50      # blank end = start month only
    assert impact["event_qty"].sum() == 70


def test_delist_runs_to_horizon_and_proposed_is_not_applied():
    ev = _events([["D1", "A", "delist", "2027-03", None, -100, 0, "approved", ""],
                  ["P1", "ALL", "promo", "2027-01", "2027-01", 50, 0, "proposed", ""]])
    out, impact = apply_events(_fc(), ev, ["A", "B"], MONTHS)
    q = out.set_index(["item_id", "month"])["qty"]
    assert q[("A", "2027-03")] == 0 and q[("A", "2027-04")] == 0
    assert q[("A", "2027-01")] == 100                                  # proposed: shown, not planned
    assert set(impact.loc[impact["event_id"] == "P1", "item_id"]) == {"A", "B"}
    out2, _ = apply_events(_fc(), ev, ["A", "B"], MONTHS, include_proposed=True, excluded=["D1"])
    q2 = out2.set_index(["item_id", "month"])["qty"]
    assert q2[("A", "2027-01")] == 150 and q2[("A", "2027-04")] == 100


def test_abc_xyz_classification():
    items = pd.DataFrame({"item_id": ["A", "B", "C"], "description": "", "item_type": "FG", "unit_cost": [10.0, 2.0, 1.0],
                          "abc": ["", "", "A"]})
    import numpy as np
    fc = {"A": np.full(12, 100.0), "B": np.full(12, 100.0), "C": np.full(12, 100.0)}
    sigmas = {"A": (5.0, ""), "B": (20.0, ""), "C": (60.0, "")}
    seg = classify(items, fc, pd.DataFrame(columns=["item_id", "month", "qty"]), sigmas, Settings()).set_index("item_id")
    assert seg.loc["A", "abc"] == "A" and seg.loc["B", "abc_calculated"] == "B" and seg.loc["C", "abc_calculated"] == "C"
    assert seg.loc["C", "abc"] == "A"                                  # class given on the item wins
    assert list(seg["xyz"]) == ["X", "Y", "Z"]
    assert seg.loc["A", "matrix_service_level"] == Settings().sl_ax


def test_policy_changes_calculated_safety_stock_only():
    d = build_sample()
    base = run_plan(d).safety.set_index("item_id")
    seg = run_plan(d, scenario=Scenario(service_level_policy="abc_xyz")).safety.set_index("item_id")
    assert seg.loc["FG-1002", "safety_stock"] > base.loc["FG-1002", "safety_stock"]   # AY: 97% vs 95%
    assert seg.loc["FG-1001", "safety_stock"] == base.loc["FG-1001", "safety_stock"]  # given on item
    assert seg.loc["FG-1002", "service_level_source"] == "ABC/XYZ AY"


def test_sample_events_are_proposed_and_flagged():
    d = build_sample()
    r = run_plan(d)
    assert not r.events["applied"].any()
    assert (r.alerts["category"] == "Event").sum() == 4
    r2 = run_plan(d, scenario=Scenario(include_proposed_events=True))
    assert r2.events["applied"].all()
    ev = r2.alerts[r2.alerts["category"] == "Event"]
    assert (ev["ref"] == "EV-04").any()                                 # starts in frozen zone
    assert ev[ev["ref"] == "EV-03"]["message"].str.contains("still projected in stock").any()   # delisting
    seg = r2.segments.set_index("item_id")
    assert seg.loc["FG-1002", "matrix_safety_stock"] == round(r2.safety.set_index("item_id").loc["FG-1002", "safety_stock"]) \
        or r2.safety.set_index("item_id").loc["FG-1002", "service_level"] != seg.loc["FG-1002", "matrix_service_level"]
    assert excel_report(r2)[:2] == b"PK" and pdf_report(r2)[:4] == b"%PDF"


def test_events_round_trip_through_template():
    d = build_sample()
    loaded, issues = load_workbook(template_bytes(d))
    assert not [i for i in issues if i.severity == "error"]
    assert len(loaded.events) == 4 and set(loaded.events["status"]) == {"proposed"}
