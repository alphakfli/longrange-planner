"""Monthly time buckets. Months are stored as 'YYYY-MM' strings everywhere."""

from __future__ import annotations

import math
import re
from datetime import date, datetime

import pandas as pd

_MONTH_NAMES = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def normalize_month(value) -> str | None:
    """Turn a date, timestamp or text such as '2026-11', '11/2026' or 'Nov 2026' into 'YYYY-MM'."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return f"{value.year:04d}-{value.month:02d}"
    if isinstance(value, pd.Period):
        return f"{value.year:04d}-{value.month:02d}"
    text = str(value).strip()
    if not text:
        return None
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})(?:[-/.]\d{1,2})?(?:[ T].*)?", text)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{4})", text)
    if m:
        return f"{int(m.group(2)):04d}-{int(m.group(1)):02d}"
    m = re.fullmatch(r"([A-Za-z]{3})[A-Za-z]*[ \-']*(\d{2,4})", text)
    if m and m.group(1).lower() in _MONTH_NAMES:
        year = int(m.group(2))
        year = year + 2000 if year < 100 else year
        return f"{year:04d}-{_MONTH_NAMES[m.group(1).lower()]:02d}"
    try:
        ts = pd.Timestamp(text)
        return f"{ts.year:04d}-{ts.month:02d}"
    except (ValueError, TypeError):
        return None


def add_months(month: str, n: int) -> str:
    y, m = int(month[:4]), int(month[5:7])
    total = y * 12 + (m - 1) + n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def month_range(start: str, n: int) -> list[str]:
    return [add_months(start, i) for i in range(n)]


def months_between(a: str, b: str) -> int:
    """Number of months from a to b (b - a)."""
    return (int(b[:4]) * 12 + int(b[5:7])) - (int(a[:4]) * 12 + int(a[5:7]))


def label(month: str) -> str:
    """'2026-11' -> 'Nov 26'."""
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{names[int(month[5:7]) - 1]} {month[2:4]}"


def weeks_to_months(weeks: float, weeks_per_month: float = 4.33) -> int:
    """Lead time in whole monthly buckets, rounded half up (2 weeks -> 0, 3 weeks -> 1, 6 weeks -> 1)."""
    if not weeks or weeks <= 0:
        return 0
    return int(math.floor(weeks / weeks_per_month + 0.5))


def current_month() -> str:
    today = date.today()
    return f"{today.year:04d}-{today.month:02d}"
