"""Safety stock: SS = Z x sigma(forecast error) x sqrt(lead time + review period).

Sigma is the standard deviation of monthly forecast error (forecast - actual).
The review period is one month, because the plan is refreshed monthly.
"""

from __future__ import annotations

import math
from statistics import NormalDist

import pandas as pd


def z_value(service_level: float) -> float:
    service_level = min(max(float(service_level), 0.5), 0.9999)
    return NormalDist().inv_cdf(service_level)


def safety_stock(sigma: float, service_level: float, lead_time_months: float, review_months: float = 1.0) -> float:
    if sigma is None or not math.isfinite(sigma) or sigma <= 0:
        return 0.0
    return z_value(service_level) * sigma * math.sqrt(max(lead_time_months, 0) + review_months)


def safety_stock_table(items: pd.DataFrame, sigmas: dict[str, tuple[float, str]], default_service_level: float,
                       weeks_per_month: float) -> pd.DataFrame:
    """One row per item: the safety stock used by the plan and where it came from.

    ``sigmas`` maps item_id -> (sigma, source description).
    """
    rows = []
    for _, it in items.iterrows():
        item = it["item_id"]
        given = it.get("safety_stock")
        sl = it.get("service_level")
        sl = float(sl) if pd.notna(sl) and sl else default_service_level
        lt_m = (float(it.get("lead_time_weeks") or 0) + float(it.get("safety_lead_time_weeks") or 0)) / weeks_per_month
        if pd.notna(given):
            rows.append({"item_id": item, "safety_stock": float(given), "method": "Given on item",
                         "service_level": None, "sigma": None, "lead_time_months": round(lt_m, 2)})
            continue
        sigma, src = sigmas.get(item, (None, ""))
        if sigma and sigma > 0:
            ss = safety_stock(sigma, sl, lt_m)
            rows.append({"item_id": item, "safety_stock": round(ss), "method": f"Calculated ({src})",
                         "service_level": sl, "sigma": round(sigma, 1), "lead_time_months": round(lt_m, 2)})
        else:
            rows.append({"item_id": item, "safety_stock": 0.0, "method": "None (no safety stock or history)",
                         "service_level": None, "sigma": None, "lead_time_months": round(lt_m, 2)})
    return pd.DataFrame(rows)
