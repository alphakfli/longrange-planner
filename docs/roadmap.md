# Roadmap

## Next
- **Business Central connector**: OData / API v2.0 pull of items, BOMs, routings, demand forecasts, sales history
  and orders (mapping in `src/longrange/io/connectors/business_central.py`).
- **Saved scenarios**: name, save and compare what-if scenarios side by side.
- **Levelling suggestions**: propose pull-ahead, alternate line or outsourcing moves for overloaded months,
  with the cost of each.
- **Safety lead time** applied to due dates, and weekly buckets for the first 3 months.

## Later
- SAP S/4HANA connector (planned independent requirements, MRP views, PP/DS capacity).
- Odoo, NetSuite and generic SQL connectors.
- Multi-site planning with transfers between locations.
- Forecast value added: compare statistical, consensus and final versions against actuals.
- Excel and PDF report templates that companies can brand.
- Docker image and one-click deploy to Streamlit Community Cloud.
