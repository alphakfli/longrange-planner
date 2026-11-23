# Planning logic

All quantities are planned in monthly buckets. Months are written `YYYY-MM`.

## 1. Demand

For each item and month:

```
independent demand = max(forecast, sales orders)
```

This is forecast consumption: sales orders in a month use up that month's forecast, so demand is not
counted twice. Load forecast entries on the first of the month (any date in the month is read as that month).

### Consensus vs statistical baseline

For each item, gap = consensus ÷ baseline − 1 over the plan horizon. Beyond ±`settings.baseline_gap_alert_pct`
(20%) the item gets a Baseline gap alert: the consensus is far from what history alone suggests, so it needs a
known event behind it. The largest single-month gap is shown too, but does not alert on its own, because
methods without seasonality always miss a sale month.

### Stock-out months

Recorded sales in a month when an item was out of stock show only what supply allowed. With `stockout_days`
on the sales history row, the planner estimates true demand from the selling days:

```
estimated demand = recorded × days in month ÷ (days in month − stockout days)      (capped at 3×)
```

The estimate replaces the recorded quantity for the statistical baseline, accuracy, bias, safety stock sigma
and ABC/XYZ. Above the cap, the month raises a Warning to agree a manual estimate.

### Forecast bias, lag 1

Accuracy is judged against the forecast that was used to plan the month, not a newer one. For each of the
last `settings.bias_months` (3) months with actual sales, the planner takes the version whose first month is that
month: FC-2026-10 for November, FC-2026-09 for October. Per item:

```
bias = Σ(forecast − actual) ÷ Σ actual        positive = over-forecast, negative = under-forecast
```

Items outside ±`settings.bias_alert_pct` (10%) get a Forecast bias alert. Bias is fixed at the source (the forecast),
not covered with safety stock, which is sized for random error only.

### Demand events (promotions, launches, delistings)

The `events` sheet sits on top of the consensus forecast instead of being typed into it, so each event stays visible
and can be switched on or off. For every month an event covers:

```
forecast with event = forecast × (1 + lift_pct / 100) + extra_qty      (never below 0)
```

- `promo`: a % lift for a few months, e.g. +25% in March and April.
- `launch` or new listing: `extra_qty` units per month (works even where the forecast is 0).
- `delist`: `lift_pct = -100`; a blank `end_month` runs to the end of the horizon, so you see the stock left behind.
- `item_id = ALL` applies the event to every finished good. Events are applied in sheet order.

`status = approved` events are in the plan. `status = proposed` events are shown with their units and an Info alert,
but planned only when the what-if "Include proposed events" is ticked. This mirrors S&OP: Marketing and Sales
propose, the S&OP meeting decides with the supply impact in front of it. An applied event that starts inside the
frozen zone raises a Warning, because orders there are already firm and supply cannot react.

The forecast version comes from `settings.current_forecast`, or the last version by name. The previous version
(`settings.previous_forecast`, or the one before current) is used for the forecast bridge and alerts.

## 2. Safety stock

If `items.safety_stock` is filled in, it is used. Otherwise:

```
SS = Z × σ × √(lead time in months + 1)
```

- **Z** comes from the service level (`items.service_level`, or `settings.default_service_level`): 0.95 → 1.645.
- **σ** is the standard deviation of monthly forecast error (forecast − actual). It comes from past forecast
  versions compared with `sales_history` where at least 3 months overlap, otherwise from the statistical
  forecast's holdout errors.
- **+1** is the review period: the plan is refreshed monthly, so stock must also cover one month of uncertainty.

### Service level by ABC / XYZ segment

Finished goods are segmented two ways:

- **ABC by value**: next 12 months of forecast × `unit_cost`, ranked. Items up to 80% of cumulative value are A,
  up to 95% are B, the rest C (`settings.abc_a_share`, `abc_b_share`). The top item is always A. A class typed
  in `items.abc` overrides the calculated one.
- **XYZ by predictability**: coefficient of variation of forecast error, σ ÷ average monthly demand of the last 12
  months. X ≤ 10%, Y ≤ 25%, Z above (`settings.xyz_x_max_cv`, `xyz_y_max_cv`). Items with no error history use the
  variability of their sales instead.

With `settings.service_level_policy = abc_xyz` (or the dashboard switch), calculated safety stock uses the target
level of the item's segment from `settings.sl_ax` … `sl_cz`:

| | X steady | Y variable | Z erratic |
| --- | --- | --- | --- |
| **A** high value | 98% | 97% | 95% |
| **B** | 97% | 95% | 93% |
| **C** low value | 93% | 92% | 90% |

The logic: an A item's stockout costs the most revenue, so it gets the most protection; a Z item needs far more
stock for each extra point of service, so the level steps down from X to Z. Service level or safety stock typed
on the item always wins. The Inventory tab also shows, for every finished good, the safety stock the segment level
would give next to the one in the plan, which shows items that carry too much or too little buffer.

## 3. Netting (MPS and MRP)

Items are processed by low-level code: finished goods first, then bulk, then raw materials and packaging. A BOM
loop is reported as a data issue.

For each item:

```
gross requirement   = independent demand + dependent demand
projected available = on hand + Σ (scheduled receipts + planned receipts − gross requirement)
```

**Existing orders** (`supply_orders`) are scheduled receipts in their due month (past-due orders count in the
first month). Released orders are never changed. For firm and planned orders the engine checks whether each is
still needed, latest first:

- In the **frozen zone** (`frozen_months`), an unneeded order is kept and flagged "Review (frozen)".
- Beyond it, an order is **cancelled** if stock stays above safety stock without it, or **reduced** to the
  smallest quantity (respecting minimum and multiple) that keeps it there.

**New planned orders** are created in the first month where projected available would fall below safety stock:

```
need = safety stock − projected available + net demand of the next (lot_accum_months − 1) months
qty  = max(need, min_order_qty), rounded up to order_multiple, split into orders of at most max_order_qty
release month = due month − lead time (weeks ÷ weeks_per_month, rounded half up)
```

A release month before the plan start means the order is already late ("Late release" alert).

**Dependent demand:** for each made item, every firm, planned and new order creates component demand in its
release month: `qty × qty_per × (1 + scrap_pct / 100)`. Released orders are assumed to have their components
issued already.

## 4. Capacity

```
available hours = shifts × hours_per_shift × working days × efficiency %
required hours  = Σ (order qty ÷ units_per_hour + setup_hours)   for production orders starting that month
load %          = required ÷ available
```

Working days come from `calendar` if given, else `work_centers.working_days_per_month`. Each item uses its
routing with the lowest `priority` number, unless a scenario moves it.

## 5. Inventory health

```
weeks of coverage = projected available ÷ (average gross requirement of the next 3 months ÷ weeks_per_month)
E&O limit         = shelf_life_months × weeks_per_month × eo_coverage_share   (or max_weeks_of_coverage)
```

Status per item and month: Shortage (negative), Below safety stock, No demand, E&O risk (coverage above the
limit), Healthy. The last 3 months are not judged for excess, because demand beyond the horizon is unknown.

## 6. KPIs

```
net attainment      = Σ actual ÷ Σ planned
absolute attainment = Σ min(actual, planned) ÷ Σ planned
```

Absolute attainment gives no credit for over-producing one item to cover another's shortfall.

## 7. Statistical forecast

For each item with sales history, four methods are tried: 3-month moving average, seasonal naive (needs 12
months), damped Holt (6 months) and Holt-Winters with multiplicative seasonality and damped trend (24 months).
Each is fitted on all but the last 6 months and scored by WMAPE on those 6; the best is refitted on all history.

Note: if a promotion moved month (for example a sale moving from November to April), history before the move
will mislead seasonal methods. Review the baseline before using it.

## Known simplifications

- Monthly buckets: lead times under about two weeks round to zero months.
- Safety lead time is stored but not yet applied to dates (most values are below one bucket).
- Capacity is infinite during netting; levelling is left to the planner, supported by the what-if controls.
- One location. Multi-site planning is on the roadmap.
