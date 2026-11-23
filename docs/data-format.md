# Input data format

One Excel workbook with one sheet per table, or one CSV file per table named after it (`items.csv`, `forecast.csv` …).
Only `items` and `forecast` are required. Months are `YYYY-MM`; dates and text such as `Nov 2026` are also accepted.
Generate a template with every column: `longrange template my_input.xlsx`.

## items (required)

One row per item: finished goods, bulk, packaging and raw materials.

| Column | Required | Default | Meaning |
| --- | --- | --- | --- |
| `item_id` | yes |  | Unique item code |
| `description` |  | blank | Item name |
| `item_type` | yes |  | FG (finished good), BULK, PKG (packaging) or RAW |
| `replenishment` | yes |  | make (production order) or buy (purchase order) |
| `uom` |  | `EA` | Unit of measure |
| `on_hand` |  | `0.0` | Inventory available now |
| `safety_stock` |  | blank | Safety stock quantity. Leave blank to calculate it from forecast error and service level |
| `service_level` |  | blank | Target service level, e.g. 0.95. Blank = settings default |
| `lead_time_weeks` |  | `0.0` | Production or purchase lead time in weeks |
| `safety_lead_time_weeks` |  | `0.0` | Extra time buffer in weeks |
| `min_order_qty` |  | `0.0` | Smallest batch or purchase quantity |
| `order_multiple` |  | `0.0` | Round orders up to this multiple (tank or run size) |
| `max_order_qty` |  | `0.0` | Largest batch; 0 = no limit |
| `lot_accum_months` |  | `1.0` | Months of demand to group into one order (1 = lot-for-lot) |
| `shelf_life_months` |  | `0.0` | Total shelf life; 0 = not tracked |
| `unit_cost` |  | `0.0` | Standard cost per unit |
| `vendor` |  | blank | Supplier or contract manufacturer for bought items |
| `abc` |  | blank | Optional ABC class (A, B or C). Blank = calculated from forecast value |

## bom

Bill of materials: what each made item consumes per unit.

| Column | Required | Default | Meaning |
| --- | --- | --- | --- |
| `parent_item` | yes |  |  |
| `component_item` | yes |  |  |
| `qty_per` | yes |  | Component quantity per 1 parent unit |
| `scrap_pct` |  | `0.0` | Extra component consumed, in percent |

## work_centers

Lines and resources with their monthly capacity.

| Column | Required | Default | Meaning |
| --- | --- | --- | --- |
| `work_center` | yes |  |  |
| `name` |  | blank |  |
| `shifts` |  | `1.0` |  |
| `hours_per_shift` |  | `8.0` |  |
| `working_days_per_month` |  | `21.0` |  |
| `efficiency_pct` |  | `100.0` | Planned efficiency or OEE in percent |

## calendar

Optional: working days per work center and month (holidays, shutdowns). Overrides the default.

| Column | Required | Default | Meaning |
| --- | --- | --- | --- |
| `work_center` | yes |  |  |
| `month` | yes |  |  |
| `working_days` | yes |  |  |

## routings

Which work center makes each item, and how fast. priority 1 = primary line.

| Column | Required | Default | Meaning |
| --- | --- | --- | --- |
| `item_id` | yes |  |  |
| `work_center` | yes |  |  |
| `units_per_hour` | yes |  |  |
| `setup_hours` |  | `0.0` |  |
| `priority` |  | `1.0` |  |

## forecast (required)

Demand forecast by version, item and month. Keep every monthly version.

| Column | Required | Default | Meaning |
| --- | --- | --- | --- |
| `version` | yes |  |  |
| `item_id` | yes |  |  |
| `month` | yes |  |  |
| `qty` | yes |  |  |

## sales_history

Actual sales or shipments by item and month. Used for statistical forecast and accuracy.

| Column | Required | Default | Meaning |
| --- | --- | --- | --- |
| `item_id` | yes |  |  |
| `month` | yes |  |  |
| `qty` | yes |  |  |

## sales_orders

Open customer orders by due month. They consume the forecast.

| Column | Required | Default | Meaning |
| --- | --- | --- | --- |
| `item_id` | yes |  |  |
| `month` | yes |  |  |
| `qty` | yes |  |  |
| `customer` |  | blank |  |

## supply_orders

Existing production and purchase orders (scheduled receipts).

| Column | Required | Default | Meaning |
| --- | --- | --- | --- |
| `order_id` | yes |  |  |
| `item_id` | yes |  |  |
| `order_type` |  | `production` | production or purchase |
| `status` |  | `firm` | released, firm or planned |
| `due_month` | yes |  |  |
| `qty` | yes |  |  |

## events

Promotions, launches and delistings to lay on top of the forecast. Approved events are in the plan; proposed events can be tried as a what-if.

| Column | Required | Default | Meaning |
| --- | --- | --- | --- |
| `event_id` | yes |  | Short code, e.g. EV-01 |
| `item_id` | yes |  | Finished good, or ALL for every finished good |
| `event_type` |  | `promo` | promo, launch, delist or other |
| `start_month` | yes |  | First month affected |
| `end_month` |  | blank | Last month affected. Blank = start month only (delist: to the end of the horizon) |
| `lift_pct` |  | `0.0` | Change to the forecast in percent: 25 = +25%, -100 = no demand (delist) |
| `extra_qty` |  | `0.0` | Units added per month on top of the forecast, e.g. a launch or a new listing |
| `status` |  | `approved` | approved (in the plan) or proposed (what-if only) |
| `note` |  | blank | Owner or reason, e.g. 'Marketing: spring sale extension' |

## production_actuals

Planned vs actual production by item and month, for attainment KPIs.

| Column | Required | Default | Meaning |
| --- | --- | --- | --- |
| `item_id` | yes |  |  |
| `month` | yes |  |  |
| `planned_qty` | yes |  |  |
| `actual_qty` | yes |  |  |

## settings

Two columns, `key` and `value`. Any key left out takes its default.

| Key | Default |
| --- | --- |
| `plan_start` | blank |
| `horizon_months` | 18 |
| `current_forecast` | blank |
| `previous_forecast` | blank |
| `frozen_months` | 3 |
| `slushy_months` | 6 |
| `default_service_level` | 0.95 |
| `capacity_warning_pct` | 85.0 |
| `capacity_critical_pct` | 100.0 |
| `forecast_change_alert_pct` | 10.0 |
| `eo_coverage_share` | 0.5 |
| `max_weeks_of_coverage` | 26.0 |
| `attainment_target_pct` | 95.0 |
| `weeks_per_month` | 4.33 |
| `service_level_policy` | single |
| `abc_a_share` | 0.8 |
| `abc_b_share` | 0.95 |
| `xyz_x_max_cv` | 0.1 |
| `xyz_y_max_cv` | 0.25 |
| `sl_ax` | 0.98 |
| `sl_ay` | 0.97 |
| `sl_az` | 0.95 |
| `sl_bx` | 0.97 |
| `sl_by` | 0.95 |
| `sl_bz` | 0.93 |
| `sl_cx` | 0.93 |
| `sl_cy` | 0.92 |
| `sl_cz` | 0.9 |
