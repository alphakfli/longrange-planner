# Changelog

## 0.2.0 (2026-11-23)

- Demand events: new optional `events` sheet for promotions, launches and delistings, applied on top of the
  forecast. Approved events are planned; proposed events are shown with their impact and can be included as a
  what-if. Alerts for proposed events and for applied events that start inside the frozen zone.
- ABC / XYZ segmentation of finished goods (value and forecastability), a 3 × 3 service level matrix, and a
  `service_level_policy` setting to use it for calculated safety stock.
- Forecast tab: event impact chart and table, plan demand line. Inventory tab: segment matrix, Pareto chart and
  safety stock comparison. New Excel sheets and a PDF events table.
- Warning when a delisting leaves projected stock behind.
- KPIs tab: lag-1 forecast bias over the last 3 months (each month judged on the version that
  planned it), with a chart, a month-by-month table and a Forecast bias alert outside ±10%.
  Settings `bias_alert_pct` and `bias_months`. Sample data gets two archived versions.
- Stock-outs: optional `stockout_days` in sales history. Demand for those months is estimated from the
  selling days (capped at 3×) and used for planning, the baseline and bias; shown on the Forecast chart,
  the KPIs bias section, Data check and Excel, with a Stock-out alert. Sample: FG-1003, 9 days in Oct 2026.
- Sample data: four proposed events.

## 0.1.0 (2026-11-20)

First version.

- Excel and CSV import with validation, ERP-style header aliases and a generated input template.
- Statistical baseline forecast, forecast accuracy and bias, forecast version bridge.
- 18-month MPS / MRP netting with lot sizing, safety stock, time fences and action messages.
- Rough-cut capacity by work center, inventory health, weeks of coverage and E&O risk.
- Net and absolute attainment, capacity utilization.
- Alerts with suggested actions.
- Streamlit dashboard with what-if scenarios (demand, shifts, routing, outsourcing).
- Excel and PDF (S&OP supply review) reports.
- Command line: `longrange plan`, `template`, `sample`.
- Connector interface with a Business Central stub.
