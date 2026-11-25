# SAP and IBP mapping

LongRange Planner runs on plain tables, so it works beside SAP ERP and SAP IBP rather than inside them. This page
maps each input table to its usual SAP ECC / S/4HANA source and each output to the IBP key figure it corresponds to.
Field names are the standard ones; your system may use custom fields or reports, so check with your SAP team.
Typical extraction routes: SE16N table downloads, an SAP Query, Analysis for Office, the standard list reports
below exported to Excel, or an IBP planning view exported from the Excel add-in.

## Inputs from SAP ERP

| Table | Columns | SAP source |
| --- | --- | --- |
| items | item_id, description, item_type | MARA-MATNR, MAKT-MAKTX, material type MARA-MTART (FERT finished, HALB semi-finished, VERP packaging, ROH raw) |
| items | replenishment | MARC-BESKZ procurement type: E in-house → make, F external → buy |
| items | lead_time_weeks | MARC-PLIFZ planned delivery time (buy) or MARC-DZEIT in-house production time (make), in days ÷ 7 |
| items | min_order_qty, order_multiple, max_order_qty | MARC-BSTMI minimum lot size, MARC-BSTRF rounding value, MARC-BSTMA maximum lot size (MRP 1 view) |
| items | safety_stock | MARC-EISBE |
| items | on_hand | MARD-LABST unrestricted stock (MB52, MMBE) |
| items | unit_cost | MBEW-STPRS / MBEW-PEINH standard price |
| items | shelf_life_months | MARA-MHDHB total shelf life |
| items | vendor | Fixed source in the source list (EORD-FLIFN) or main info record |
| bom | parent_item, component_item, qty_per, scrap_pct | STKO / STPO (CS11, CS12): STPO-MENGE ÷ STKO-BMENG; STPO-AUSCH component scrap |
| work_centers, calendar | shifts, hours, days, efficiency | CRHD work centers and KAKO capacity headers (CR02, CR03); factory calendar |
| routings | units_per_hour, setup_hours | PLKO / PLPO routing operations (CA03): base quantity ÷ machine time; setup time |
| sales_history | qty by month | Billed or delivered quantity by month: VBRP (billing items) or MCSI / S001 (LIS) |
| sales_orders | open qty by month | Open schedule lines: VBAP / VBEP (VA05) |
| order_lines | order, customer, dates, quantities | VBAK / VBAP / VBEP: order date VBAK-AUDAT, requested date (first schedule line, VBEP-EDATU), confirmed date (confirmed schedule line, VBEP-BMENG > 0); shipped date and quantity from deliveries LIKP-WADAT_IST / LIPS-LFIMG (VL06O) |
| supply_orders | firm and released orders | Production orders AFKO / AFPO (COOIS), purchase orders EKKO / EKPO / EKET (ME2M); planned orders PLAF if you load them |
| production_actuals | planned vs actual | Order quantity vs delivered quantity, AFPO-PSMNG / AFPO-WEMNG (COOIS) |

## Inputs from SAP IBP

| Table | IBP source |
| --- | --- |
| forecast | Consensus demand key figure at product / location / month, one version per monthly cycle (snapshot) |
| events | Promotion and product-introduction key figures, or the event list behind them |
| settings | Planning-area horizon, frozen horizon, service level settings |

## Outputs as IBP key figures

The **IBP key figures / Power BI** export writes the plan in IBP's structure: one row per product (or resource),
location, month and key figure, plus a planning view with key figures as rows and months as columns.

| LongRange output | IBP key figure (typical name) |
| --- | --- |
| planned forecast after events | Consensus Demand |
| sales orders | Sales Orders / Customer Receipts |
| dependent demand | Dependent Demand / Component Demand |
| firm and released receipts | Supply - Firm Receipts (Production / Purchase Receipts) |
| planned receipts | Supply - Planned Receipts (Planned Production / Planned External Receipts) |
| projected available | Projected Inventory |
| safety stock | Safety Stock / Target Inventory |
| available hours | Capacity Supply |
| required hours | Capacity Usage |
| load % | Capacity Utilization |

Key-figure names differ between planning areas: map them once in Power Query or in the IBP data integration
template.

## Cross-checks in SAP

| LongRange view | Compare with |
| --- | --- |
| Projected available, planned orders | MD04 stock / requirements list, MD05 / MD06 MRP list |
| Action messages | MD06 exception messages (reschedule in, reschedule out, cancel) |
| Capacity load | CM01 / CM21 capacity planning |
| Order promising | CO09 availability overview, the ATP check in VA02 |
| OTIF and backlog | VA05 open orders, VL06O deliveries, your delivery-performance report |
| Data health | MM60 materials list, MD07 stock / requirements collective display |
