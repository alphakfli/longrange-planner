"""Order management: delivery performance (OTIF, fill rate), the open backlog, and order promising (ATP).

Promising works in the plan's monthly buckets. Open lines are taken in order of their committed date and
allocated against finished-goods stock plus supply, month by month:

* ``firm_in_frozen`` (default): inside the frozen zone only firm and released orders count, because a planned
  order there is not yet a commitment; after the frozen zone all supply counts.
* ``plan``: every receipt in the plan counts, as if all planned orders were firmed.

Each line gets the month it can be promised on both bases, so the gap shows which planned orders must be firmed
to keep a promise.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def _mon(m: str) -> str:
    return pd.Timestamp(m + "-01").strftime("%b %Y")


@dataclass
class OrderResult:
    as_of: pd.Timestamp
    lines: pd.DataFrame          # every line with on-time / in-full flags and value
    open_lines: pd.DataFrame     # open lines with promise months, status and suggested action
    otif_month: pd.DataFrame     # month: lines, OTIF vs requested and confirmed, fill rate
    by_customer: pd.DataFrame    # customer: OTIF, fill rate, backlog, at-risk lines
    by_item: pd.DataFrame        # item: OTIF, fill rate, backlog, at-risk lines
    kpis: dict


def as_of_date(settings, months: list[str]) -> pd.Timestamp:
    if settings.orders_as_of:
        try:
            return pd.Timestamp(settings.orders_as_of).normalize()
        except (ValueError, TypeError):
            pass
    return pd.Timestamp(months[0] + "-01") - pd.Timedelta(days=1)


def _month_index(d: pd.Timestamp, months: list[str]) -> int:
    if pd.isna(d):
        return 0
    m = d.strftime("%Y-%m")
    if m < months[0]:
        return 0
    return months.index(m) if m in months else len(months)


def _promise(open_lines: pd.DataFrame, supply: np.ndarray, start_stock: float, months: list[str]) -> list[int | None]:
    """Earliest month index each line can be fully covered, allocating in line order."""
    cum = start_stock + np.cumsum(supply)
    used = 0.0
    out = []
    for q in open_lines["open_qty"]:
        need = used + q
        ok = np.nonzero(cum >= need - 1e-6)[0]
        if len(ok):
            out.append(int(ok[0]))
            used = need
        else:
            out.append(None)      # not covered inside the horizon; does not consume supply
    return out


def order_management(r, order_lines: pd.DataFrame) -> OrderResult | None:
    if order_lines is None or order_lines.empty:
        return None
    s, months = r.settings, r.months
    asof = as_of_date(s, months)
    items = r.items.set_index("item_id")
    cost = items["unit_cost"].to_dict()
    names = items["description"].to_dict()

    ol = order_lines.copy()
    ol["status"] = ol["status"].fillna("open").str.lower()
    ol = ol[ol["status"] != "cancelled"].copy()
    for c in ("order_date", "requested_date", "confirmed_date", "shipped_date"):
        ol[c] = pd.to_datetime(ol[c], errors="coerce")
    ol["price"] = np.where(ol["unit_price"] > 0, ol["unit_price"], ol["item_id"].map(cost).fillna(0.0))
    ol["commit_date"] = ol["confirmed_date"].fillna(ol["requested_date"])
    ol["confirmed_later"] = ol["confirmed_date"] > ol["requested_date"]
    tol = pd.Timedelta(days=int(s.otif_tolerance_days))

    # ---- delivery performance on shipped lines
    sh = ol[ol["status"] == "shipped"].copy()
    window = set(pd.period_range(end=asof.to_period("M"), periods=int(s.otif_months), freq="M").strftime("%Y-%m"))
    sh = sh[sh["shipped_date"].dt.strftime("%Y-%m").isin(window) & (sh["shipped_date"] <= asof)]
    sh["in_full"] = sh["shipped_qty"] >= sh["qty"] - 1e-6
    sh["on_time_requested"] = sh["shipped_date"] <= sh["requested_date"] + tol
    sh["on_time_confirmed"] = sh["shipped_date"] <= sh["commit_date"] + tol
    sh["otif_requested"] = sh["in_full"] & sh["on_time_requested"]
    sh["otif_confirmed"] = sh["in_full"] & sh["on_time_confirmed"]
    sh["days_late"] = (sh["shipped_date"] - sh["commit_date"]).dt.days
    sh["ship_month"] = sh["shipped_date"].dt.strftime("%Y-%m")

    PERF = ["lines", "otif_requested_pct", "otif_confirmed_pct", "on_time_pct", "in_full_pct", "fill_rate_pct"]

    def perf(df: pd.DataFrame, key: str | None) -> pd.DataFrame:
        d = df.assign(_k=df[key] if key else "all")
        g = d.groupby("_k").agg(lines=("qty", "size"), otif_requested_pct=("otif_requested", "mean"),
                                otif_confirmed_pct=("otif_confirmed", "mean"), on_time_pct=("on_time_confirmed", "mean"),
                                in_full_pct=("in_full", "mean"), shipped=("shipped_qty", "sum"), ordered=("qty", "sum"))
        for c in ("otif_requested_pct", "otif_confirmed_pct", "on_time_pct", "in_full_pct"):
            g[c] = 100 * g[c].astype(float)
        g["fill_rate_pct"] = 100 * g["shipped"] / g["ordered"].replace(0, np.nan)
        return g[PERF].rename_axis(key or "all")

    otif_month = (perf(sh, "ship_month").reset_index().rename(columns={"ship_month": "month"})
                  if len(sh) else pd.DataFrame(columns=["month"] + PERF))

    # ---- open backlog and promising
    op = ol[ol["status"] == "open"].copy()
    op["open_qty"] = (op["qty"] - op["shipped_qty"]).clip(lower=0)
    op = op[op["open_qty"] > 0]
    op["value"] = op["open_qty"] * op["price"]
    op["past_due"] = op["commit_date"] < asof
    op["days_past_due"] = np.where(op["past_due"], (asof - op["commit_date"]).dt.days, 0)
    op["due_index"] = [_month_index(d, months) for d in op["commit_date"]]
    op = op.sort_values(["commit_date", "order_date", "order_id", "line"]).reset_index(drop=True)
    tp = r.time_phased
    frozen = int(s.frozen_months)
    po = r.planned_orders
    rows = []
    for item, g in op.groupby("item_id", sort=False):
        t = tp[tp["item_id"] == item].set_index("month").reindex(months).fillna(0.0)
        firm = t["scheduled_receipts"].to_numpy()
        plan = firm + t["planned_receipts"].to_numpy()
        basis = plan if str(s.atp_basis).lower() == "plan" else np.where(np.arange(len(months)) < frozen, firm, plan)
        stock = float(items.at[item, "on_hand"]) if item in items.index else 0.0
        p_basis = _promise(g, basis, stock, months)
        p_plan = _promise(g, plan, stock, months)
        first_po = po[po["item_id"] == item].sort_values("due_index")
        for (idx, line), kb, kp in zip(g.iterrows(), p_basis, p_plan, strict=True):
            due = line["due_index"]
            if kb is not None and kb <= due:
                status = "Past due, stock available" if line["past_due"] else "Can be promised"
                action = "Ship now and close the line." if line["past_due"] else ""
            elif kp is not None and kp <= due:
                status = "Needs a planned order firmed"
                cand = first_po[first_po["due_index"] <= max(due, 0)]
                cand = cand if len(cand) else first_po
                pl = cand.iloc[0] if len(cand) else None
                action = (f"Firm {pl['planned_id']} ({pl['qty']:,.0f} due {_mon(pl['due_month'])}) to keep this date."
                          if pl is not None else "Firm the planned supply for this item.")
            else:
                status = "Late"
                action = ("Agree a new date with the customer, or allocate from another order."
                          if kp is not None else "No supply in the horizon: escalate to supply planning.")
            rows.append(dict(index=idx, promise_month=months[kb] if kb is not None and kb < len(months) else None,
                             promise_month_if_firmed=months[kp] if kp is not None and kp < len(months) else None,
                             promise_status=status, action=action))
    pr = pd.DataFrame(rows).set_index("index") if rows else pd.DataFrame(
        columns=["promise_month", "promise_month_if_firmed", "promise_status", "action"])
    op = op.join(pr)
    op["at_risk"] = op["promise_status"].isin(["Needs a planned order firmed", "Late"])
    op["description"] = op["item_id"].map(names)
    open_lines = op[["order_id", "line", "customer", "item_id", "description", "open_qty", "value", "order_date",
                     "requested_date", "confirmed_date", "past_due", "days_past_due", "promise_month",
                     "promise_month_if_firmed", "promise_status", "at_risk", "action"]]

    # ---- by customer and by item
    def group_view(key: str) -> pd.DataFrame:
        perf_g = perf(sh, key) if len(sh) else pd.DataFrame(columns=PERF).rename_axis(key)
        back = op.groupby(key).agg(open_lines=("open_qty", "size"), backlog_value=("value", "sum"),
                                   past_due_lines=("past_due", "sum"), at_risk_lines=("at_risk", "sum"))
        out = perf_g.join(back, how="outer").fillna({"open_lines": 0, "backlog_value": 0.0, "past_due_lines": 0,
                                                    "at_risk_lines": 0}).reset_index()
        return out.sort_values("backlog_value", ascending=False)

    by_customer = group_view("customer")
    by_item = group_view("item_id")
    by_item.insert(1, "description", by_item["item_id"].map(names))

    tot = perf(sh, None).iloc[0] if len(sh) else pd.Series(dtype=float)
    kpis = dict(
        as_of=asof, lines_shipped=len(sh),
        otif_requested_pct=float(tot.get("otif_requested_pct", np.nan)),
        otif_confirmed_pct=float(tot.get("otif_confirmed_pct", np.nan)),
        fill_rate_pct=float(tot.get("fill_rate_pct", np.nan)),
        confirmed_later_pct=100 * float(ol.loc[ol["confirmed_date"].notna(), "confirmed_later"].mean())
        if ol["confirmed_date"].notna().any() else np.nan,
        open_lines=len(op), backlog_value=float(op["value"].sum()),
        past_due_lines=int(op["past_due"].sum()), past_due_value=float(op.loc[op["past_due"], "value"].sum()),
        at_risk_lines=int(op["at_risk"].sum()), at_risk_value=float(op.loc[op["at_risk"], "value"].sum()),
        late_lines=int((op["promise_status"] == "Late").sum()),
        firm_needed_lines=int((op["promise_status"] == "Needs a planned order firmed").sum()),
        otif_target_pct=float(s.otif_target_pct))
    lines = ol.merge(sh[["order_id", "line", "in_full", "on_time_requested", "on_time_confirmed", "otif_requested",
                         "otif_confirmed", "days_late"]], on=["order_id", "line"], how="left")
    return OrderResult(asof, lines, open_lines, otif_month, by_customer, by_item, kpis)
