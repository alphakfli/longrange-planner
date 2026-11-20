import io

import numpy as np
import pandas as pd
from openpyxl import load_workbook as open_xlsx

from longrange import load_files, load_workbook, run_plan
from longrange.forecast.accuracy import bias, compare_versions, wmape
from longrange.forecast.stats import forecast_item, statistical_forecast
from longrange.io.template import template_bytes
from longrange.months import month_range
from longrange.reports import excel_report, pdf_report
from longrange.sample import build_sample


def test_template_roundtrip_keeps_data():
    data = build_sample()
    loaded, issues = load_workbook(template_bytes(data))
    assert not [i for i in issues if i.severity == "error"]
    assert len(loaded.items) == len(data.items)
    assert loaded.settings.current_forecast == "FC-2026-11"
    assert loaded.settings.plan_start == "2026-12"


def test_csv_upload_with_erp_style_headers():
    items = "Item No,Description,Type,Replenishment System,Inventory\nA1,Serum,FG,Prod. Order,10\n"
    fc = "Forecast Name,Item No,Forecast Date,Quantity\nV1,A1,2027-01-01,5\nV1,A1,Feb 2027,6\n"
    data, issues = load_files({"items.csv": items.encode(), "forecast.csv": fc.encode()})
    assert data.items.iloc[0]["replenishment"] == "make"
    assert data.forecast["month"].tolist() == ["2027-01", "2027-02"]
    assert not [i for i in issues if i.severity == "error"]


def test_missing_required_column_is_an_error():
    data, issues = load_files({"items.csv": b"item_id,description\nA,x\n", "forecast.csv": b"version,item_id,month,qty\nV,A,2027-01,1\n"})
    assert any(i.severity == "error" and "item_type" in i.message for i in issues)


def test_accuracy_metrics():
    assert wmape([100, 100], [90, 120]) == 0.15
    assert bias([100, 60], [90, 50]) == -20 / 160


def test_forecast_picks_seasonal_method_for_seasonal_series():
    months = 36
    season = np.array([1, 1, 1.5, 2, 1, 1, 1, 1, 1, 1, 1, 1.2])
    y = np.array([1000 * season[i % 12] for i in range(months)])
    method, values, score, _ = forecast_item(y, 12)
    assert method in ("seasonal_naive", "holt_winters")
    assert values[3] > values[0]  # the April-type peak is kept


def test_statistical_forecast_shape():
    hist = pd.DataFrame([{"item_id": "A", "month": m, "qty": 100 + i} for i, m in enumerate(month_range("2024-01", 30))])
    fc, details = statistical_forecast(hist, "2026-07", 18)
    assert len(fc) == 18 and details[0].item_id == "A"


def test_compare_versions():
    f = pd.DataFrame({"version": ["V1", "V1", "V2", "V2"], "item_id": ["A"] * 4, "month": ["2027-01", "2027-02"] * 2,
                      "qty": [100, 100, 110, 120]})
    b = compare_versions(f, "V2", "V1")
    assert b.iloc[0]["change"] == 30 and round(b.iloc[0]["change_pct"]) == 15


def test_reports_build():
    r = run_plan(build_sample())
    xlsx = excel_report(r)
    wb = open_xlsx(io.BytesIO(xlsx))
    assert {"Summary", "Alerts", "Capacity load %", "MPS (finished goods)", "Weeks of coverage"} <= set(wb.sheetnames)
    pdf = pdf_report(r)
    assert pdf[:4] == b"%PDF" and len(pdf) > 5000
