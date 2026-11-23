"""The input data model: one table per sheet, plus planning settings.

Every table is a pandas DataFrame with the columns defined in ``SCHEMA``. The same
schema drives the Excel template, the importer's validation and the docs.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields

import pandas as pd


@dataclass(frozen=True)
class Column:
    name: str
    kind: str  # "text", "number", "month"
    required: bool = False
    default: object = None
    help: str = ""


def _c(name, kind="text", required=False, default=None, help=""):
    return Column(name, kind, required, default, help)


SCHEMA: dict[str, dict] = {
    "items": {
        "required": True,
        "help": "One row per item: finished goods, bulk, packaging and raw materials.",
        "columns": [
            _c("item_id", required=True, help="Unique item code"),
            _c("description", default="", help="Item name"),
            _c("item_type", required=True, help="FG (finished good), BULK, PKG (packaging) or RAW"),
            _c("replenishment", required=True, help="make (production order) or buy (purchase order)"),
            _c("uom", default="EA", help="Unit of measure"),
            _c("on_hand", "number", default=0.0, help="Inventory available now"),
            _c("safety_stock", "number", default=None,
               help="Safety stock quantity. Leave blank to calculate it from forecast error and service level"),
            _c("service_level", "number", default=None, help="Target service level, e.g. 0.95. Blank = settings default"),
            _c("lead_time_weeks", "number", default=0.0, help="Production or purchase lead time in weeks"),
            _c("safety_lead_time_weeks", "number", default=0.0, help="Extra time buffer in weeks"),
            _c("min_order_qty", "number", default=0.0, help="Smallest batch or purchase quantity"),
            _c("order_multiple", "number", default=0.0, help="Round orders up to this multiple (tank or run size)"),
            _c("max_order_qty", "number", default=0.0, help="Largest batch; 0 = no limit"),
            _c("lot_accum_months", "number", default=1.0, help="Months of demand to group into one order (1 = lot-for-lot)"),
            _c("shelf_life_months", "number", default=0.0, help="Total shelf life; 0 = not tracked"),
            _c("unit_cost", "number", default=0.0, help="Standard cost per unit"),
            _c("vendor", default="", help="Supplier or contract manufacturer for bought items"),
            _c("abc", default="", help="Optional ABC class (A, B or C). Blank = calculated from forecast value"),
        ],
    },
    "bom": {
        "required": False,
        "help": "Bill of materials: what each made item consumes per unit.",
        "columns": [
            _c("parent_item", required=True), _c("component_item", required=True),
            _c("qty_per", "number", required=True, help="Component quantity per 1 parent unit"),
            _c("scrap_pct", "number", default=0.0, help="Extra component consumed, in percent"),
        ],
    },
    "work_centers": {
        "required": False,
        "help": "Lines and resources with their monthly capacity.",
        "columns": [
            _c("work_center", required=True), _c("name", default=""),
            _c("shifts", "number", default=1.0), _c("hours_per_shift", "number", default=8.0),
            _c("working_days_per_month", "number", default=21.0),
            _c("efficiency_pct", "number", default=100.0, help="Planned efficiency or OEE in percent"),
        ],
    },
    "calendar": {
        "required": False,
        "help": "Optional: working days per work center and month (holidays, shutdowns). Overrides the default.",
        "columns": [_c("work_center", required=True), _c("month", "month", required=True),
                    _c("working_days", "number", required=True)],
    },
    "routings": {
        "required": False,
        "help": "Which work center makes each item, and how fast. priority 1 = primary line.",
        "columns": [
            _c("item_id", required=True), _c("work_center", required=True),
            _c("units_per_hour", "number", required=True), _c("setup_hours", "number", default=0.0),
            _c("priority", "number", default=1.0),
        ],
    },
    "forecast": {
        "required": True,
        "help": "Demand forecast by version, item and month. Keep every monthly version.",
        "columns": [_c("version", required=True), _c("item_id", required=True),
                    _c("month", "month", required=True), _c("qty", "number", required=True)],
    },
    "sales_history": {
        "required": False,
        "help": "Actual sales or shipments by item and month. Used for statistical forecast and accuracy.",
        "columns": [_c("item_id", required=True), _c("month", "month", required=True),
                    _c("qty", "number", required=True),
                    _c("stockout_days", "number", default=0.0,
                       help="Days the item was out of stock that month. The planner estimates true demand from the days it was available")],
    },
    "sales_orders": {
        "required": False,
        "help": "Open customer orders by due month. They consume the forecast.",
        "columns": [_c("item_id", required=True), _c("month", "month", required=True),
                    _c("qty", "number", required=True), _c("customer", default="")],
    },
    "supply_orders": {
        "required": False,
        "help": "Existing production and purchase orders (scheduled receipts).",
        "columns": [
            _c("order_id", required=True), _c("item_id", required=True),
            _c("order_type", default="production", help="production or purchase"),
            _c("status", default="firm", help="released, firm or planned"),
            _c("due_month", "month", required=True), _c("qty", "number", required=True),
        ],
    },
    "events": {
        "required": False,
        "help": "Promotions, launches and delistings to lay on top of the forecast. "
                "Approved events are in the plan; proposed events can be tried as a what-if.",
        "columns": [
            _c("event_id", required=True, help="Short code, e.g. EV-01"),
            _c("item_id", required=True, help="Finished good, or ALL for every finished good"),
            _c("event_type", default="promo", help="promo, launch, delist or other"),
            _c("start_month", "month", required=True, help="First month affected"),
            _c("end_month", "month", default=None, help="Last month affected. Blank = start month only (delist: to the end of the horizon)"),
            _c("lift_pct", "number", default=0.0, help="Change to the forecast in percent: 25 = +25%, -100 = no demand (delist)"),
            _c("extra_qty", "number", default=0.0, help="Units added per month on top of the forecast, e.g. a launch or a new listing"),
            _c("status", default="approved", help="approved (in the plan) or proposed (what-if only)"),
            _c("note", default="", help="Owner or reason, e.g. 'Marketing: spring sale extension'"),
        ],
    },
    "production_actuals": {
        "required": False,
        "help": "Planned vs actual production by item and month, for attainment KPIs.",
        "columns": [_c("item_id", required=True), _c("month", "month", required=True),
                    _c("planned_qty", "number", required=True), _c("actual_qty", "number", required=True)],
    },
}


def empty_table(sheet: str) -> pd.DataFrame:
    return pd.DataFrame({c.name: pd.Series(dtype="float64" if c.kind == "number" else "object")
                         for c in SCHEMA[sheet]["columns"]})


@dataclass
class Settings:
    """Planning settings. Each can be set on the Excel 'settings' sheet as key / value."""

    plan_start: str | None = None          # first planning month 'YYYY-MM'; default = earliest month of current forecast
    horizon_months: int = 18
    current_forecast: str | None = None    # forecast version to plan with; default = latest version name
    previous_forecast: str | None = None   # version to compare against; default = the one before current
    frozen_months: int = 3                 # firm zone: the plan does not change orders here
    slushy_months: int = 6                 # limited-change zone
    default_service_level: float = 0.95
    capacity_warning_pct: float = 85.0
    capacity_critical_pct: float = 100.0
    forecast_change_alert_pct: float = 10.0
    eo_coverage_share: float = 0.5         # coverage above this share of shelf life is an E&O risk
    max_weeks_of_coverage: float = 26.0    # coverage cap for items without shelf life
    attainment_target_pct: float = 95.0
    weeks_per_month: float = 4.33
    bias_alert_pct: float = 10          # flag lag-1 bias over the last bias_months above this
    bias_months: int = 3
    service_level_policy: str = "single"   # single = default_service_level for all; abc_xyz = use the matrix below
    abc_a_share: float = 0.80              # A items make up the first 80% of forecast value
    abc_b_share: float = 0.95              # B items the next 15%; C the rest
    xyz_x_max_cv: float = 0.10             # X: forecast error under 10% of average demand
    xyz_y_max_cv: float = 0.25             # Y: 10-25%; Z above
    sl_ax: float = 0.98
    sl_ay: float = 0.97
    sl_az: float = 0.95
    sl_bx: float = 0.97
    sl_by: float = 0.95
    sl_bz: float = 0.93
    sl_cx: float = 0.93
    sl_cy: float = 0.92
    sl_cz: float = 0.90

    @classmethod
    def from_table(cls, df: pd.DataFrame | None) -> Settings:
        s = cls()
        if df is None or df.empty:
            return s
        types = {f.name: f.type for f in fields(cls)}
        for _, row in df.iterrows():
            key = str(row.get("key", "")).strip().lower()
            val = row.get("value")
            if key not in types or val is None or (isinstance(val, float) and pd.isna(val)) or str(val).strip() == "":
                continue
            t = str(types[key])
            try:
                if "int" in t:
                    val = int(float(val))
                elif "float" in t:
                    val = float(val)
                else:
                    val = str(val).strip()
                    if key == "plan_start":
                        from longrange.months import normalize_month
                        val = normalize_month(val)
            except (ValueError, TypeError):
                continue
            setattr(s, key, val)
        return s

    def to_table(self) -> pd.DataFrame:
        return pd.DataFrame([{"key": f.name, "value": getattr(self, f.name)} for f in fields(self)])


@dataclass
class PlanningData:
    items: pd.DataFrame = field(default_factory=lambda: empty_table("items"))
    bom: pd.DataFrame = field(default_factory=lambda: empty_table("bom"))
    work_centers: pd.DataFrame = field(default_factory=lambda: empty_table("work_centers"))
    calendar: pd.DataFrame = field(default_factory=lambda: empty_table("calendar"))
    routings: pd.DataFrame = field(default_factory=lambda: empty_table("routings"))
    forecast: pd.DataFrame = field(default_factory=lambda: empty_table("forecast"))
    sales_history: pd.DataFrame = field(default_factory=lambda: empty_table("sales_history"))
    sales_orders: pd.DataFrame = field(default_factory=lambda: empty_table("sales_orders"))
    supply_orders: pd.DataFrame = field(default_factory=lambda: empty_table("supply_orders"))
    production_actuals: pd.DataFrame = field(default_factory=lambda: empty_table("production_actuals"))
    events: pd.DataFrame = field(default_factory=lambda: empty_table("events"))
    settings: Settings = field(default_factory=Settings)

    def table(self, name: str) -> pd.DataFrame:
        return getattr(self, name)

    def forecast_versions(self) -> list[str]:
        if self.forecast.empty:
            return []
        return sorted(self.forecast["version"].astype(str).unique().tolist())

    def copy(self) -> PlanningData:
        kw = {name: self.table(name).copy() for name in SCHEMA}
        from dataclasses import replace
        return PlanningData(**kw, settings=replace(self.settings))
