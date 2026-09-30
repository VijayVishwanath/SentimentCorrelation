"""Module 6 — Outcome Reporting.

Before-vs-after remediation measurement. Two lenses:
  1. The remediation register (pre/post columns as supplied, or derived from telemetry and tickets
     when an upload leaves them out).
  2. DEX Score before/after, recomputed from device-week telemetry and tickets
     with pre = weeks < remediation week, post = weeks >= remediation week
     (the windowing used to build the register).
"""
from __future__ import annotations

import json
import threading

import pandas as pd

from .dex_score import compute_components, experience_recovery

PAIRS = {
    "frustration": ("pre_frustration_score", "post_frustration_score"),
    "repeat_rate": ("pre_repeat_contact_rate_pct", "post_repeat_contact_rate_pct"),
    "ticket_rate": ("pre_ticket_rate_per_week", "post_ticket_rate_per_week"),
    "boot": ("pre_boot_duration_sec", "post_boot_duration_sec"),
    "latency": ("pre_network_latency_ms", "post_network_latency_ms"),
    "hw_health": ("pre_hardware_health_score", "post_hardware_health_score"),
    "hangs": ("pre_app_hang_count", "post_app_hang_count"),
}
LOWER_IS_BETTER = {"frustration", "repeat_rate", "ticket_rate", "boot", "latency", "hangs"}


def _pair(rems: pd.DataFrame, key: str) -> dict:
    pre_c, post_c = PAIRS[key]
    pre, post = float(rems[pre_c].mean()), float(rems[post_c].mean())
    change = post - pre
    improved = change < 0 if key in LOWER_IS_BETTER else change > 0
    pct = (abs(change) / pre * 100) if pre else 0.0
    return {"pre": round(pre, 2), "post": round(post, 2), "change": round(change, 2),
            "change_pct": round(pct, 1), "improved": bool(improved)}


def case_dex(store, rem: dict, sla: float) -> dict:
    dev, w = rem["device_id"], int(rem["week_of_remediation"])
    dw, tk = store.dex_frames(dev)
    before = compute_components(dw[dw["week"] < w], tk[tk["week"] < w], sla)
    after = compute_components(dw[dw["week"] >= w], tk[tk["week"] >= w], sla)
    return {"before": before, "after": after}


def cohort_dex(store, rems: pd.DataFrame, sla: float) -> dict:
    parts_b_dw, parts_b_tk, parts_a_dw, parts_a_tk = [], [], [], []
    for r in rems.to_dict("records"):
        dev, w = r["device_id"], int(r["week_of_remediation"])
        dw, tk = store.dex_frames(dev)
        parts_b_dw.append(dw[dw["week"] < w]); parts_a_dw.append(dw[dw["week"] >= w])
        parts_b_tk.append(tk[tk["week"] < w]); parts_a_tk.append(tk[tk["week"] >= w])
    if not parts_b_dw:
        return {"available": False}
    before = compute_components(pd.concat(parts_b_dw), pd.concat(parts_b_tk), sla)
    after = compute_components(pd.concat(parts_a_dw), pd.concat(parts_a_tk), sla)
    b, a = before.get("dex_score"), after.get("dex_score")  # None when every fix sits at the first/last data week
    return {"available": b is not None and a is not None, "before": before, "after": after,
            "experience_recovery_pct": experience_recovery(b, a) if (a is not None and b) else None}


def business_impact(rems: pd.DataFrame, tickets: pd.DataFrame, cfg: dict) -> dict:
    """Annualised savings from the remediated cohort, plus fleet-wide opportunity."""
    weekly_tickets_avoided = float((rems["pre_ticket_rate_per_week"] - rems["post_ticket_rate_per_week"]).sum(skipna=True))
    annual_tickets_avoided = weekly_tickets_avoided * 52
    res = tickets["resolution_time_hours"].astype(float) if len(tickets) else pd.Series(dtype=float)
    avg_res_hours = float(res.mean()) if res.notna().any() else 0.0  # unknown resolution time -> no productivity estimate
    ticket_cost = annual_tickets_avoided * cfg["cost_per_ticket_usd"]
    productivity_hours = annual_tickets_avoided * avg_res_hours * cfg["productivity_loss_factor"]
    productivity_cost = productivity_hours * cfg["hourly_employee_cost_usd"]
    total = ticket_cost + productivity_cost
    per_device = total / len(rems) if len(rems) else 0.0
    return {
        "annual_tickets_avoided": round(annual_tickets_avoided, 1),
        "support_cost_savings_usd": round(ticket_cost),
        "productivity_hours_recovered": round(productivity_hours, 1),
        "productivity_savings_usd": round(productivity_cost),
        "total_annual_savings_usd": round(total),
        "savings_per_remediated_device_usd": round(per_device),
        "assumptions": {k: cfg[k] for k in ("cost_per_ticket_usd", "hourly_employee_cost_usd",
                                            "productivity_loss_factor")} | {"avg_resolution_hours": round(avg_res_hours, 2)},
    }


def ticket_reduction_pct(effect: dict | None) -> float:
    """Observed ticket-rate reduction of a fix category, as a positive %; 0 when tickets did not fall."""
    tr = (effect or {}).get("ticket_rate") or {}
    return float(tr.get("change_pct") or 0.0) if tr.get("improved") else 0.0


def cost_per_ticket(store, cfg: dict) -> float:
    """Support handling cost plus the employee time lost while the ticket is open."""
    res = store.tickets_enriched["resolution_time_hours"].astype(float)
    return cfg["cost_per_ticket_usd"] + (float(res.mean()) if res.notna().any() else 0.0)         * cfg["productivity_loss_factor"] * cfg["hourly_employee_cost_usd"]


_memo: dict = {}
_memo_lock = threading.Lock()


def outcome_report(store, cfg: dict, category: str | None = None, department: str | None = None) -> dict:
    """Memoised per dataset + settings: several pages, the Copilot and the runbooks all need it, and it takes
    seconds on a large fleet. Callers must treat the result as read-only."""
    key = (id(store), category, department, json.dumps(cfg, sort_keys=True, default=str))
    with _memo_lock:
        hit = _memo.get(key)
        if hit is not None and hit[0] is store:
            return hit[1]
    rep = _outcome_report(store, cfg, category, department)
    with _memo_lock:
        if len(_memo) > 64:
            _memo.clear()
        _memo[key] = (store, rep)
    return rep


def _outcome_report(store, cfg: dict, category: str | None, department: str | None) -> dict:
    rems = store.remediations
    if category:
        rems = rems[rems["root_cause_category"] == category]
    if department:
        rems = rems[rems["department"] == department]
    sla = cfg["resolution_sla_hours"]
    if rems.empty:
        return {"cases": 0, "aggregate": {}, "rows": [], "by_category": []}

    aggregate = {k: _pair(rems, k) for k in PAIRS}
    improved_cases = int(((rems["post_repeat_contact_rate_pct"] <= rems["pre_repeat_contact_rate_pct"])
                          & (rems["post_ticket_rate_per_week"] <= rems["pre_ticket_rate_per_week"])).sum())

    rows = []
    for r in rems.to_dict("records"):
        d = case_dex(store, r, sla)
        b = d["before"].get("dex_score") if d["before"].get("available") else None
        a = d["after"].get("dex_score") if d["after"].get("available") else None
        rows.append({**{k: r[k] for k in ("remediation_id", "device_id", "employee_name", "department",
                                          "root_cause_category", "problem_type", "week_of_remediation", "date",
                                          "action_taken", "pre_ticket_count", "post_ticket_count")},
                     **{f"{k}_pre": r[PAIRS[k][0]] for k in PAIRS}, **{f"{k}_post": r[PAIRS[k][1]] for k in PAIRS},
                     "dex_before": b, "dex_after": a,
                     "recovery_pct": experience_recovery(b, a) if (a is not None and b) else None,
                     "low_sample": bool(r["post_ticket_count"] <= 2)})

    by_cat = []
    for cat, g in rems.groupby("root_cause_category"):
        cd = cohort_dex(store, g, sla)
        by_cat.append({"category": cat, "cases": int(len(g)), "action": g["action_taken"].mode().iat[0],
                       "frustration": _pair(g, "frustration"), "repeat_rate": _pair(g, "repeat_rate"),
                       "ticket_rate": _pair(g, "ticket_rate"),
                       "dex_before": cd["before"].get("dex_score"), "dex_after": cd["after"].get("dex_score"),
                       "recovery_pct": cd["experience_recovery_pct"]})
    by_cat.sort(key=lambda d: -1e9 if d["recovery_pct"] is None else d["recovery_pct"], reverse=True)

    cohort = cohort_dex(store, rems, sla)
    return {
        "cases": int(len(rems)),
        "improved_cases": improved_cases,
        "aggregate": aggregate,
        "dex": cohort,
        "business_impact": business_impact(rems, store.tickets_enriched, cfg),
        "by_category": by_cat,
        "rows": rows,
        "notes": ["Post-fix ticket volume drops sharply once a device is fixed, so several cases have only 1-2 "
                  "post-remediation tickets (flagged low_sample). The aggregate across all cases is the "
                  "statistically meaningful read.",
                  "DEX before/after windows: pre = weeks before the remediation week, post = remediation week "
                  "onward; repeat contacts are recomputed inside each window."],
    }
