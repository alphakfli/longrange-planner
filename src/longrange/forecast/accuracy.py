"""Forecast accuracy, bias and version comparison."""

from __future__ import annotations

import numpy as np
import pandas as pd


def wmape(actual, forecast) -> float:
    """Weighted MAPE = sum |actual - forecast| / sum actual."""
    a, f = np.asarray(actual, float), np.asarray(forecast, float)
    denom = np.abs(a).sum()
    return float(np.abs(a - f).sum() / denom) if denom else 0.0


def bias(actual, forecast) -> float:
    """Bias = sum (forecast - actual) / sum actual. Positive = over-forecasting."""
    a, f = np.asarray(actual, float), np.asarray(forecast, float)
    denom = np.abs(a).sum()
    return float((f - a).sum() / denom) if denom else 0.0


def accuracy_report(forecast: pd.DataFrame, history: pd.DataFrame) -> pd.DataFrame:
    """Compare every forecast version with actual sales over the months they share.

    Returns one row per version and item: months compared, WMAPE, bias and the
    standard deviation of the monthly error (the sigma in the safety stock formula).
    """
    if forecast.empty or history.empty:
        return pd.DataFrame(columns=["version", "item_id", "months", "actual", "forecast", "wmape", "bias", "error_std"])
    act = history.groupby(["item_id", "month"], as_index=False)["qty"].sum().rename(columns={"qty": "actual"})
    fc = forecast.groupby(["version", "item_id", "month"], as_index=False)["qty"].sum().rename(columns={"qty": "forecast"})
    m = fc.merge(act, on=["item_id", "month"], how="inner")
    rows = []
    for (ver, item), g in m.groupby(["version", "item_id"]):
        err = g["forecast"] - g["actual"]
        rows.append({"version": ver, "item_id": item, "months": len(g), "actual": g["actual"].sum(),
                     "forecast": g["forecast"].sum(), "wmape": wmape(g["actual"], g["forecast"]),
                     "bias": bias(g["actual"], g["forecast"]),
                     "error_std": float(err.std(ddof=1)) if len(g) > 1 else np.nan})
    return pd.DataFrame(rows)


def compare_versions(forecast: pd.DataFrame, new: str, old: str, months: list[str] | None = None) -> pd.DataFrame:
    """Forecast bridge: total by item in the new vs old version over the shared months."""
    f = forecast[forecast["version"].isin([new, old])]
    if months:
        f = f[f["month"].isin(months)]
    shared = set(f[f["version"] == new]["month"]) & set(f[f["version"] == old]["month"])
    f = f[f["month"].isin(shared)]
    p = f.pivot_table(index="item_id", columns="version", values="qty", aggfunc="sum", fill_value=0)
    for v in (new, old):
        if v not in p.columns:
            p[v] = 0.0
    out = pd.DataFrame({"item_id": p.index, "previous": p[old].to_numpy(), "current": p[new].to_numpy()})
    out["change"] = out["current"] - out["previous"]
    out["change_pct"] = np.where(out["previous"] > 0, out["change"] / out["previous"] * 100, np.nan)
    return out.sort_values("change", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)


def compare_versions_monthly(forecast: pd.DataFrame, new: str, old: str) -> pd.DataFrame:
    """Month-by-month totals of two versions, for a line chart."""
    f = forecast[forecast["version"].isin([new, old])]
    p = f.pivot_table(index="month", columns="version", values="qty", aggfunc="sum")
    return p.reset_index()
