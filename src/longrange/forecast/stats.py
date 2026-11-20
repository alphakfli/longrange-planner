"""Statistical baseline forecast from monthly sales history.

Several simple, explainable methods are fitted per item; the one with the lowest
error on a holdout (the last few months of history) is used. Planners can then
adjust the baseline with commercial input and save it as a forecast version.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from longrange.forecast.accuracy import wmape
from longrange.months import month_range, months_between


@dataclass
class ItemForecast:
    item_id: str
    method: str
    values: np.ndarray        # forecast for the horizon
    holdout_wmape: float | None
    error_std: float | None   # std of holdout errors (forecast - actual), used for safety stock
    history_months: int


def moving_average(y: np.ndarray, h: int, window: int = 3) -> np.ndarray:
    return np.full(h, y[-window:].mean())


def seasonal_naive(y: np.ndarray, h: int, period: int = 12) -> np.ndarray:
    last = y[-period:]
    return np.array([last[i % period] for i in range(h)], dtype=float)


def holt(y: np.ndarray, h: int, alpha: float = .4, beta: float = .1, damp: float = .95) -> np.ndarray:
    level, trend = y[0], (y[min(3, len(y) - 1)] - y[0]) / max(1, min(3, len(y) - 1))
    for v in y[1:]:
        prev = level
        level = alpha * v + (1 - alpha) * (level + damp * trend)
        trend = beta * (level - prev) + (1 - beta) * damp * trend
    out, d = [], 0.0
    for i in range(1, h + 1):
        d += damp ** i
        out.append(level + d * trend)
    return np.maximum(np.array(out), 0)


def holt_winters(y: np.ndarray, h: int, period: int = 12, alpha: float = .3, beta: float = .05,
                 gamma: float = .3, damp: float = .95) -> np.ndarray:
    """Additive-trend, multiplicative-season Holt-Winters with a damped trend."""
    n = len(y)
    season_avg = [y[i * period:(i + 1) * period].mean() for i in range(n // period)]
    seasonals = np.array([np.mean([y[c * period + i] / season_avg[c] for c in range(n // period)]) for i in range(period)])
    seasonals = np.where(np.isfinite(seasonals) & (seasonals > 0), seasonals, 1.0)
    level = season_avg[0]
    trend = (season_avg[-1] - season_avg[0]) / (period * max(1, len(season_avg) - 1))
    s = seasonals.copy()
    for t in range(n):
        idx = t % period
        prev = level
        level = alpha * (y[t] / s[idx]) + (1 - alpha) * (level + damp * trend)
        trend = beta * (level - prev) + (1 - beta) * damp * trend
        s[idx] = gamma * (y[t] / max(level, 1e-9)) + (1 - gamma) * s[idx]
    out, d = [], 0.0
    for i in range(1, h + 1):
        d += damp ** i
        out.append((level + d * trend) * s[(n + i - 1) % period])
    return np.maximum(np.array(out), 0)


METHODS = {
    "moving_average_3": (moving_average, 3),
    "seasonal_naive": (seasonal_naive, 12),
    "holt_damped": (holt, 6),
    "holt_winters": (holt_winters, 24),
}


def forecast_item(y: np.ndarray, h: int, holdout: int = 6) -> tuple[str, np.ndarray, float | None, float | None]:
    """Pick the method with the lowest holdout WMAPE, then refit on all history."""
    y = np.asarray(y, dtype=float)
    candidates = [name for name, (_, need) in METHODS.items() if len(y) >= need]
    if not candidates:
        return "moving_average_3", np.full(h, y.mean() if len(y) else 0.0), None, None
    best = None
    if len(y) > holdout + 6:
        train, test = y[:-holdout], y[-holdout:]
        for name in candidates:
            fn, need = METHODS[name]
            if len(train) < need:
                continue
            pred = fn(train, holdout)
            score = wmape(test, pred)
            if best is None or score < best[1]:
                best = (name, score, np.std(pred - test, ddof=1))
    name, score, err = best if best else (candidates[-1], None, None)
    return name, METHODS[name][0](y, h), score, err


def statistical_forecast(history: pd.DataFrame, start: str, horizon: int, version: str = "STAT",
                         holdout: int = 6) -> tuple[pd.DataFrame, list[ItemForecast]]:
    """Return (forecast rows in the input format, per-item details)."""
    rows, details = [], []
    if history.empty:
        return pd.DataFrame(columns=["version", "item_id", "month", "qty"]), details
    months = month_range(start, horizon)
    for item, g in history.groupby("item_id"):
        g = g.groupby("month")["qty"].sum().sort_index()
        hist = g[g.index < start]
        if hist.empty:
            continue
        # fill gaps in the monthly series with zero
        full = month_range(hist.index.min(), months_between(hist.index.min(), hist.index.max()) + 1)
        y = hist.reindex(full, fill_value=0).to_numpy(dtype=float)
        method, values, score, err = forecast_item(y, horizon, holdout)
        details.append(ItemForecast(str(item), method, values, score, err, len(y)))
        rows += [[version, item, m, round(float(v))] for m, v in zip(months, values, strict=False)]
    return pd.DataFrame(rows, columns=["version", "item_id", "month", "qty"]), details
