"""Causal uplift of remediations: difference-in-differences against matched, never-fixed devices.

The naive before/after overstates a fix: devices get fixed *because* they were at their worst, and many would
have calmed down anyway (regression to the mean). So for every fixed device we find devices that were never
fixed but were degraded on the same signal the week before the fix, with a similar ticket history, and measure
them over the same weeks:

    uplift = (treated post − treated pre) − mean(control post − control pre)

Windows: pre = the WINDOW weeks before the fix week, post = the fix week and the WINDOW−1 weeks after.
Outcomes per device-week: tickets raised, and frustration burden (the week's highest frustration, 0 with no
ticket). The 95% interval is a percentile bootstrap over fixed devices (seeded, so the page is reproducible).
"""
from __future__ import annotations

import threading

import numpy as np

from .thresholds import CATEGORY_PRIMARY_SIGNAL, THRESHOLDS, TELEMETRY_SIGNALS

WINDOW = 4
CONTROLS = 5
TICKET_WEIGHT = 3  # ticket history matters more than the exact signal level for balance (checked: 1, 3, 6)
BOOTSTRAP = 1000
SEED = 7
METRICS = {"tickets": ("ticket_count", "tickets / device-week"),
           "frustration": ("experience_burden", "frustration burden / device-week")}


def _degraded(key: str, values: np.ndarray) -> np.ndarray:
    if key == "noncompliant":
        return values > 0
    th = THRESHOLDS[key]
    return values < th["warn"] if th["critical"] < th["warn"] else values > th["warn"]


def _ci(x: np.ndarray, rng: np.random.Generator) -> list[float]:
    if len(x) < 2:
        return [float(x.mean()), float(x.mean())] if len(x) else [0.0, 0.0]
    boots = x[rng.integers(0, len(x), size=(BOOTSTRAP, len(x)))].mean(axis=1)
    return [round(float(np.percentile(boots, 2.5)), 3), round(float(np.percentile(boots, 97.5)), 3)]


def _summary(treated: np.ndarray, control: np.ndarray, rng: np.random.Generator) -> dict:
    did = treated - control
    ci = _ci(did, rng)
    uplift = float(did.mean())
    naive = float(treated.mean())
    return {"naive_change": round(naive, 3), "control_change": round(float(control.mean()), 3),
            "uplift": round(uplift, 3), "ci95": ci, "significant": bool(ci[1] < 0 or ci[0] > 0),
            "causal_share_pct": round(100 * uplift / naive, 1) if naive < 0 and uplift < 0 else 0.0}


def _estimate(store, category: str | None, department: str | None) -> dict:
    rems = store.remediations
    if category:
        rems = rems[rems["root_cause_category"] == category]
    if department:
        rems = rems[rems["department"] == department]
    if rems.empty:
        return {"available": False, "reason": "no remediations in scope"}

    dw = store.device_weeks
    weeks = sorted(int(w) for w in dw["week"].unique())
    col = {w: i for i, w in enumerate(weeks)}
    ids = dw["device_id"].unique()
    row = {d: i for i, d in enumerate(ids)}

    def grid(c: str) -> np.ndarray:
        m = dw.pivot(index="device_id", columns="week", values=c).reindex(index=ids, columns=weeks)
        return m.to_numpy(dtype=float)

    outcome = {k: grid(c) for k, (c, _) in METRICS.items()}
    ctrl = np.array([row[d] for d in ids if d not in store.remediated_devices])
    if len(ctrl) < CONTROLS:
        return {"available": False, "reason": "not enough never-fixed devices to form a control group"}
    signal_grid: dict[str, np.ndarray] = {}

    cases = []
    for r in rems.to_dict("records"):
        d, w, cat = r["device_id"], int(r["week_of_remediation"]), r["root_cause_category"]
        pre = [col[x] for x in range(w - WINDOW, w) if x in col]
        post = [col[x] for x in range(w, w + WINDOW) if x in col]
        key = CATEGORY_PRIMARY_SIGNAL.get(cat)
        if d not in row or len(pre) < 2 or len(post) < 2 or not key or (w - 1) not in col:
            continue
        if key not in signal_grid:
            signal_grid[key] = grid(TELEMETRY_SIGNALS[key][0])
        sig = signal_grid[key]
        t_i, before = row[d], col[w - 1]
        tick = outcome["tickets"]
        c_sig, c_pre = sig[ctrl, before], np.nanmean(tick[np.ix_(ctrl, pre)], axis=1)
        ok = ~np.isnan(c_sig) & ~np.isnan(c_pre)
        pool = ok & _degraded(key, np.nan_to_num(c_sig))
        if pool.sum() < CONTROLS:
            pool = ok
        scale = np.nanstd(sig[:, before]) or 1.0
        dist = np.abs(c_sig - sig[t_i, before]) / scale + np.abs(c_pre - np.nanmean(tick[t_i, pre])) \
            * TICKET_WEIGHT / (np.nanstd(c_pre) or 1.0)
        dist[~pool] = np.inf
        match = ctrl[np.argsort(dist)[:CONTROLS]]
        case = {"category": cat}
        for k, m in outcome.items():
            case[f"{k}_treated"] = float(np.nanmean(m[t_i, post]) - np.nanmean(m[t_i, pre]))
            case[f"{k}_control"] = float(np.nanmean(np.nanmean(m[np.ix_(match, post)], axis=1)
                                                    - np.nanmean(m[np.ix_(match, pre)], axis=1)))
        case["pre_tickets_treated"] = float(np.nanmean(tick[t_i, pre]))
        case["pre_tickets_control"] = float(np.nanmean(tick[np.ix_(match, pre)]))
        cases.append(case)

    if not cases:
        return {"available": False, "reason": f"fixes need {WINDOW} weeks either side with telemetry"}
    rng = np.random.default_rng(SEED)

    def block(group: list[dict]) -> dict:
        out = {"cases": len(group)}
        for k, (_, unit) in METRICS.items():
            out[k] = {**_summary(np.array([c[f"{k}_treated"] for c in group]),
                                 np.array([c[f"{k}_control"] for c in group]), rng), "unit": unit}
        out["balance"] = {"pre_tickets_treated": round(float(np.mean([c["pre_tickets_treated"] for c in group])), 3),
                          "pre_tickets_control": round(float(np.mean([c["pre_tickets_control"] for c in group])), 3)}
        return out

    cats = sorted({c["category"] for c in cases})
    return {
        "available": True, "window_weeks": WINDOW, "controls_per_case": CONTROLS, "control_pool": int(len(ctrl)),
        "overall": block(cases),
        "by_category": [{"category": cat, **block([c for c in cases if c["category"] == cat])} for cat in cats],
        "method": (f"Difference-in-differences: each fixed device vs its {CONTROLS} nearest never-fixed devices, degraded on "
                   f"the same signal the week before the fix, with a similar ticket rate; {WINDOW} weeks before vs from the fix "
                   f"week. 95% interval: bootstrap over fixed devices ({BOOTSTRAP} resamples)."),
        "reading": "uplift < 0 means the fix removed tickets/frustration beyond what similar unfixed devices did anyway",
    }


_memo: dict = {}
_lock = threading.Lock()


def causal_uplift(store, category: str | None = None, department: str | None = None) -> dict:
    """Memoised per dataset: the estimate only depends on the data, not on cost settings."""
    key = (id(store), category, department)
    with _lock:
        hit = _memo.get(key)
        if hit is not None and hit[0] is store:
            return hit[1]
    res = _estimate(store, category, department)
    with _lock:
        if len(_memo) > 32:
            _memo.clear()
        _memo[key] = (store, res)
    return res


def annual_tickets_avoided(u: dict) -> float | None:
    """Tickets a year the fixes removed beyond the control trend: −uplift × fixed devices × 52 (0 if no effect)."""
    if not u.get("available"):
        return None
    o = u["overall"]
    return round(max(0.0, -o["tickets"]["uplift"]) * o["cases"] * 52, 1)

