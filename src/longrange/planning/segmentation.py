"""ABC / XYZ segmentation of finished goods, and the service level each segment gets.

ABC ranks items by forecast value (next 12 months x unit cost): A = the items that make
up the first 80% of value, B = the next 15%, C = the rest. Value tells you where stock
money and stockouts matter most.

XYZ ranks items by how predictable they are: the coefficient of variation of forecast
error (sigma of error / average monthly demand). X = steady and well forecast, Y = some
noise, Z = hard to forecast. Predictability tells you how much buffer each unit of
service level costs: a Z item needs far more safety stock for the same service level.

Combining the two gives a 3 x 3 matrix. A typical policy protects AX/AY hardest (high
value, cheap to protect) and accepts lower service on CZ (low value, expensive to protect).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from longrange.models import Settings
from longrange.planning.safety_stock import safety_stock

COLUMNS = ["item_id", "description", "annual_value", "value_share_pct", "cum_share_pct", "abc_calculated", "abc",
           "avg_monthly_demand", "sigma", "error_cv", "xyz", "segment", "matrix_service_level"]


def matrix_level(settings: Settings, abc: str, xyz: str) -> float:
    return float(getattr(settings, f"sl_{abc.lower()}{xyz.lower()}", settings.default_service_level))


def classify(items: pd.DataFrame, forecast: dict[str, np.ndarray], history: pd.DataFrame,
             sigmas: dict[str, tuple[float, str]], settings: Settings) -> pd.DataFrame:
    fg = items[items["item_type"] == "FG"]
    if fg.empty:
        return pd.DataFrame(columns=COLUMNS)
    rows = []
    for _, it in fg.iterrows():
        f = forecast.get(it["item_id"], np.zeros(12))[:12]
        annual_qty = float(f.sum()) * 12 / max(len(f), 1)
        rows.append({"item_id": it["item_id"], "description": it.get("description", ""),
                     "annual_value": annual_qty * float(it.get("unit_cost") or 0), "given_abc": str(it.get("abc") or "").strip().upper(),
                     "avg_forecast": float(f.mean()) if len(f) else 0.0})
    df = pd.DataFrame(rows).sort_values("annual_value", ascending=False).reset_index(drop=True)
    total = df["annual_value"].sum()
    df["value_share_pct"] = df["annual_value"] / total * 100 if total else 0.0
    df["cum_share_pct"] = df["value_share_pct"].cumsum()
    cum = df["cum_share_pct"].round(6)
    df["abc_calculated"] = np.where(cum <= settings.abc_a_share * 100, "A",
                                    np.where(cum <= settings.abc_b_share * 100, "B", "C"))
    df.loc[0, "abc_calculated"] = "A"                     # the top item is always A
    df["abc"] = [g if g in ("A", "B", "C") else c for g, c in zip(df["given_abc"], df["abc_calculated"], strict=True)]

    recent = history.sort_values("month").groupby("item_id").tail(12) if not history.empty else history
    hist_mean = recent.groupby("item_id")["qty"].mean().to_dict() if not recent.empty else {}
    hist_std = recent.groupby("item_id")["qty"].std().to_dict() if not recent.empty else {}
    avg, sig, cv = [], [], []
    for r in df.itertuples():
        mean = hist_mean.get(r.item_id) or r.avg_forecast
        s = sigmas.get(r.item_id, (None, ""))[0]
        if not s:                         # no error history: fall back to demand variability
            s = hist_std.get(r.item_id)
        avg.append(mean)
        sig.append(s)
        cv.append(s / mean if s and mean else np.nan)
    df["avg_monthly_demand"] = np.round(avg)
    df["sigma"] = [None if s is None or (isinstance(s, float) and np.isnan(s)) else round(float(s), 1) for s in sig]
    df["error_cv"] = np.round(cv, 3)
    df["xyz"] = ["Z" if np.isnan(c) or c > settings.xyz_y_max_cv else ("X" if c <= settings.xyz_x_max_cv else "Y")
                 for c in df["error_cv"]]
    df["segment"] = df["abc"] + df["xyz"]
    df["matrix_service_level"] = [matrix_level(settings, a, x) for a, x in zip(df["abc"], df["xyz"], strict=True)]
    df["annual_value"] = df["annual_value"].round()
    df["value_share_pct"] = df["value_share_pct"].round(1)
    df["cum_share_pct"] = df["cum_share_pct"].round(1)
    return df[COLUMNS]


def compare_with_safety(seg: pd.DataFrame, safety: pd.DataFrame) -> pd.DataFrame:
    """Add the safety stock in the plan and what the matrix service level would give."""
    if seg.empty:
        return seg
    s = safety.set_index("item_id")
    out = seg.copy()
    out["plan_safety_stock"] = out["item_id"].map(s["safety_stock"])
    out["plan_method"] = out["item_id"].map(s["method"])
    lt = out["item_id"].map(s["lead_time_months"]).fillna(0)
    out["matrix_safety_stock"] = [round(safety_stock(sg, sl, lead)) if sg else None
                                  for sg, sl, lead in zip(out["sigma"], out["matrix_service_level"], lt, strict=True)]
    return out
