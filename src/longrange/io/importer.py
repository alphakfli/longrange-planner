"""Load planning data from an Excel workbook, a folder of CSV files, or uploaded files.

Every loader returns ``(PlanningData, issues)``. ``issues`` is a list of
``ValidationIssue``: errors block planning, warnings do not.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from longrange.models import SCHEMA, PlanningData, Settings, empty_table
from longrange.months import normalize_month

# Common alternative headers people use in ERP exports, mapped to our names.
ALIASES = {
    "item": "item_id", "item_no": "item_id", "item_number": "item_id", "no": "item_id", "sku": "item_id",
    "material": "item_id", "product": "item_id",
    "type": "item_type", "replenishment_system": "replenishment",
    "inventory": "on_hand", "qty_on_hand": "on_hand", "stock": "on_hand",
    "safety_stock_quantity": "safety_stock", "lead_time": "lead_time_weeks", "moq": "min_order_qty",
    "minimum_order_quantity": "min_order_qty", "maximum_order_quantity": "max_order_qty",
    "date": "month", "period": "month", "forecast_date": "month", "quantity": "qty",
    "forecast_name": "version", "demand_forecast_name": "version",
    "parent": "parent_item", "component": "component_item", "quantity_per": "qty_per",
    "due_date": "due_month", "order_no": "order_id", "status_code": "status",
}

SHEET_ALIASES = {"item": "items", "boms": "bom", "workcenters": "work_centers", "work_center": "work_centers",
                 "routing": "routings", "forecasts": "forecast", "demand_forecast": "forecast",
                 "history": "sales_history", "sales": "sales_history", "orders": "sales_orders",
                 "open_orders": "supply_orders", "supply": "supply_orders", "actuals": "production_actuals",
                 "setting": "settings"}


@dataclass
class ValidationIssue:
    severity: str   # "error" or "warning"
    sheet: str
    message: str
    row: int | None = None

    def as_dict(self) -> dict:
        return {"severity": self.severity, "sheet": self.sheet, "row": self.row, "message": self.message}


def _snake(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).strip().lower()).strip("_")


def _as_text(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _sheet_key(name: str) -> str:
    key = _snake(name)
    return SHEET_ALIASES.get(key, key)


def _clean_table(sheet: str, raw: pd.DataFrame, issues: list[ValidationIssue]) -> pd.DataFrame:
    spec = SCHEMA[sheet]
    df = raw.copy()
    df.columns = [ALIASES.get(_snake(c), _snake(c)) for c in df.columns]
    df = df.loc[:, ~df.columns.duplicated()]
    df = df.dropna(how="all")
    for col in spec["columns"]:
        if col.name not in df.columns:
            if col.required:
                issues.append(ValidationIssue("error", sheet, f"Missing required column '{col.name}'."))
                return empty_table(sheet)
            df[col.name] = col.default
    for col in spec["columns"]:
        s = df[col.name]
        if col.kind == "number":
            num = pd.to_numeric(s, errors="coerce")
            bad = s.notna() & num.isna() & (s.astype(str).str.strip() != "")
            for idx in df.index[bad][:5]:
                issues.append(ValidationIssue("warning", sheet, f"'{col.name}' value '{s[idx]}' is not a number; treated as blank.", int(idx) + 2))
            if col.default is not None:
                num = num.fillna(col.default)
            df[col.name] = num.astype("float64")
        elif col.kind == "month":
            mon = s.map(normalize_month)
            for idx in df.index[mon.isna() & s.notna()][:5]:
                issues.append(ValidationIssue("error", sheet, f"'{col.name}' value '{s[idx]}' is not a month (use YYYY-MM).", int(idx) + 2))
            df[col.name] = mon
        else:
            df[col.name] = s.where(s.notna(), col.default if col.default is not None else None)
            df[col.name] = df[col.name].map(_as_text)
    required = [c.name for c in spec["columns"] if c.required]
    missing = df[required].isna().any(axis=1) | (df[required].astype(str).apply(lambda col: col.str.strip() == "")).any(axis=1)
    if missing.any():
        issues.append(ValidationIssue("warning", sheet, f"{int(missing.sum())} row(s) skipped because a required value is blank."))
        df = df[~missing]
    keep = [c.name for c in spec["columns"]]
    return df[keep].reset_index(drop=True)


def _cross_checks(data: PlanningData, issues: list[ValidationIssue]) -> None:
    items = data.items
    if items.empty:
        issues.append(ValidationIssue("error", "items", "No items found."))
        return
    dup = items["item_id"][items["item_id"].duplicated()].unique()
    if len(dup):
        issues.append(ValidationIssue("error", "items", f"Duplicate item_id: {', '.join(map(str, dup[:10]))}."))
    items["item_type"] = items["item_type"].str.upper()
    items["replenishment"] = items["replenishment"].str.lower().replace(
        {"prod. order": "make", "production": "make", "prod_order": "make", "purchase": "buy", "assembly": "make"})
    bad = items[~items["replenishment"].isin(["make", "buy"])]
    for _, r in bad.head(10).iterrows():
        issues.append(ValidationIssue("error", "items", f"Item {r['item_id']}: replenishment must be 'make' or 'buy', got '{r['replenishment']}'."))
    known = set(items["item_id"])
    for sheet, col in [("bom", "parent_item"), ("bom", "component_item"), ("routings", "item_id"),
                       ("forecast", "item_id"), ("sales_orders", "item_id"), ("supply_orders", "item_id")]:
        df = data.table(sheet)
        unknown = sorted(set(df[col]) - known) if not df.empty else []
        if unknown:
            issues.append(ValidationIssue("warning", sheet, f"Unknown {col} (not in items, ignored): {', '.join(map(str, unknown[:10]))}."))
            data_table = df[df[col].isin(known)].reset_index(drop=True)
            setattr(data, sheet, data_table)
    makes = items[items["replenishment"] == "make"]["item_id"]
    if not data.work_centers.empty:
        routed = set(data.routings["item_id"])
        for item in makes:
            if item not in routed:
                issues.append(ValidationIssue("warning", "routings", f"Made item {item} has no routing, so its capacity load is not counted."))
        unknown_wc = sorted(set(data.routings["work_center"]) - set(data.work_centers["work_center"]))
        if unknown_wc:
            issues.append(ValidationIssue("warning", "routings", f"Unknown work_center: {', '.join(unknown_wc)}."))
    bom_parents = set(data.bom["parent_item"])
    for item in makes:
        row = items[items["item_id"] == item].iloc[0]
        if row["item_type"] == "FG" and item not in bom_parents:
            issues.append(ValidationIssue("warning", "bom", f"Finished good {item} is made but has no BOM."))
    if data.forecast.empty:
        issues.append(ValidationIssue("error", "forecast", "No forecast rows found."))
    neg = items[items["on_hand"] < 0]
    if not neg.empty:
        issues.append(ValidationIssue("warning", "items", f"Negative on_hand for {', '.join(neg['item_id'].head(10))}."))


def _build(tables: dict[str, pd.DataFrame]) -> tuple[PlanningData, list[ValidationIssue]]:
    issues: list[ValidationIssue] = []
    data = PlanningData()
    by_key = {_sheet_key(k): v for k, v in tables.items()}
    for sheet, spec in SCHEMA.items():
        if sheet in by_key:
            setattr(data, sheet, _clean_table(sheet, by_key[sheet], issues))
        elif spec["required"]:
            issues.append(ValidationIssue("error", sheet, f"Sheet or file '{sheet}' is missing."))
    if "settings" in by_key:
        raw = by_key["settings"].copy()
        raw.columns = [_snake(c) for c in raw.columns]
        data.settings = Settings.from_table(raw)
    if not data.items.empty:
        _cross_checks(data, issues)
    return data, issues


def load_workbook(source) -> tuple[PlanningData, list[ValidationIssue]]:
    """Load from an .xlsx path, bytes or file-like object; one sheet per table."""
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    sheets = pd.read_excel(source, sheet_name=None, engine="openpyxl", skiprows=0)
    tables = {}
    for name, df in sheets.items():
        if _snake(name) in ("readme", "instructions"):
            continue
        tables[name] = df
    return _build(tables)


def load_csv_folder(folder: str | Path) -> tuple[PlanningData, list[ValidationIssue]]:
    """Load from a folder with one CSV per table: items.csv, bom.csv, forecast.csv ..."""
    folder = Path(folder)
    tables = {p.stem: pd.read_csv(p) for p in sorted(folder.glob("*.csv"))}
    return _build(tables)


def load_files(files: dict[str, bytes]) -> tuple[PlanningData, list[ValidationIssue]]:
    """Load from uploaded files {filename: bytes}: one workbook, or several CSVs named by table."""
    xlsx = [n for n in files if n.lower().endswith((".xlsx", ".xlsm"))]
    if xlsx:
        return load_workbook(files[xlsx[0]])
    tables = {Path(n).stem: pd.read_csv(io.BytesIO(b)) for n, b in files.items() if n.lower().endswith(".csv")}
    return _build(tables)
