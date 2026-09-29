"""Module 7 — DEX Score framework.

DEX_SCORE = 0.35*EEI + 0.25*DHS + 0.20*RSS + 0.10*TRE + 0.10*STS   (requirements spec)

All components are 0-100 and computed for any population (fleet, department,
device model, single device) over any week window:

EEI  Employee Experience Index   100 - mean weekly frustration burden per employee-week
                                 (burden = highest frustration score raised that week, 0 if no contact)
DHS  Device Health Score         mean Device Health Score over the device-weeks
RSS  Remediation Success Score   100 * (1 - repeat-contact rate), repeat contacts recomputed
                                 *within* the window (same device + category seen earlier in window)
TRE  Ticket Resolution Efficiency mean over tickets of first-time-resolution (not escalated/reopened)
                                 x SLA attainment (min(1, SLA / resolution hours))
STS  Sentiment Trend Score       50 - 50*tanh(slope/10): 50 = flat, ->100 improving, ->0 worsening
                                 (slope = weekly change in mean frustration burden)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

WEIGHTS = {"eei": 0.35, "dhs": 0.25, "rss": 0.20, "tre": 0.10, "sts": 0.10}
COMPONENT_LABELS = {
    "eei": "Employee Experience Index",
    "dhs": "Device Health Score",
    "rss": "Remediation Success Score",
    "tre": "Ticket Resolution Efficiency",
    "sts": "Sentiment Trend Score",
}
STS_SLOPE_SCALE = 10.0  # burden pts/week that moves STS ~38 pts from neutral


def dex_score(eei: float, dhs: float, rss: float, tre: float, sts: float) -> float:
    return round(WEIGHTS["eei"] * eei + WEIGHTS["dhs"] * dhs + WEIGHTS["rss"] * rss
                 + WEIGHTS["tre"] * tre + WEIGHTS["sts"] * sts, 1)


def dex_band(score: float) -> str:
    return "Excellent" if score >= 85 else "Good" if score >= 70 else "Fair" if score >= 55 else "Poor"


def within_window_repeats(tickets: pd.DataFrame) -> pd.Series:
    """Repeat flag recomputed inside the window — avoids the pre/post boundary artefact."""
    if tickets.empty:
        return pd.Series(dtype=bool)
    t = tickets[["device_id", "category", "week", "ticket_id"]].sort_values(["device_id", "category", "week", "ticket_id"])
    rep = t.duplicated(["device_id", "category"], keep="first")
    return rep.reindex(tickets.index)


def resolution_efficiency(tickets: pd.DataFrame, sla_hours: float) -> float:
    if tickets.empty:
        return 100.0
    first_time = (~tickets["outcome_status"].isin(["Escalated", "Reopened"])).astype(float)
    # unknown resolution time -> judged on first-time resolution only
    sla = np.minimum(1.0, sla_hours / tickets["resolution_time_hours"].astype(float).clip(lower=0.1)).fillna(1.0)
    return round(float((first_time * sla).mean() * 100), 1)


def sentiment_trend(device_weeks: pd.DataFrame) -> tuple[float, float]:
    weekly = device_weeks.groupby("week")["experience_burden"].mean()
    if len(weekly) < 3:
        return 50.0, 0.0
    slope = float(np.polyfit(weekly.index.astype(float), weekly.values.astype(float), 1)[0])
    return round(float(50 - 50 * np.tanh(slope / STS_SLOPE_SCALE)), 1), round(slope, 3)


def compute_components(device_weeks: pd.DataFrame, tickets: pd.DataFrame, sla_hours: float = 8.0) -> dict:
    if device_weeks.empty:
        return {"available": False}
    eei = round(100 - float(device_weeks["experience_burden"].mean()), 1)
    dhs = round(float(device_weeks["device_health"].mean()), 1)
    reps = within_window_repeats(tickets)
    repeat_rate = float(reps.mean()) if len(reps) else 0.0
    rss = round(100 * (1 - repeat_rate), 1)
    tre = resolution_efficiency(tickets, sla_hours)
    sts, slope = sentiment_trend(device_weeks)
    score = dex_score(eei, dhs, rss, tre, sts)
    return {
        "available": True, "dex_score": score, "band": dex_band(score),
        "components": {"eei": eei, "dhs": dhs, "rss": rss, "tre": tre, "sts": sts},
        "weights": WEIGHTS, "labels": COMPONENT_LABELS,
        "contributions": {k: round(WEIGHTS[k] * v, 1) for k, v in
                          {"eei": eei, "dhs": dhs, "rss": rss, "tre": tre, "sts": sts}.items()},
        "supporting": {"repeat_contact_rate_pct": round(100 * repeat_rate, 1), "burden_slope_per_week": slope,
                       "device_weeks": int(len(device_weeks)), "tickets": int(len(tickets)),
                       "devices": int(device_weeks["device_id"].nunique()),
                       "avg_frustration": round(float(tickets["frustration_score"].mean()), 1) if len(tickets) else None,
                       "tickets_per_device_week": round(len(tickets) / len(device_weeks), 3)},
    }


def experience_recovery(before_score: float, after_score: float) -> float:
    """Experience Recovery % (requirements spec)."""
    if not before_score:
        return 0.0
    return round((after_score - before_score) / before_score * 100, 2)


def weekly_series(device_weeks: pd.DataFrame, tickets: pd.DataFrame, sla_hours: float = 8.0,
                  rolling: int = 4) -> list[dict]:
    """DEX score per week over a trailing window (default 4 weeks) for trend lines.

    Computed from per-week aggregates so it scales to millions of device-weeks; results equal
    compute_components() on each window. A ticket is a within-window repeat exactly when the previous
    ticket for the same device + category falls inside the window.
    """
    if device_weeks.empty:
        return []
    wk = device_weeks.groupby("week").agg(b_sum=("experience_burden", "sum"), n=("experience_burden", "size"),
                                          h_sum=("device_health", "sum"))
    wk["b_mean"] = wk["b_sum"] / wk["n"]
    t = tickets[["device_id", "category", "week", "ticket_id", "outcome_status", "resolution_time_hours",
                 "frustration_score", "repeat_contact"]].sort_values(["device_id", "category", "week", "ticket_id"])
    t = t.assign(prev_week=t.groupby(["device_id", "category"])["week"].shift(1))
    first_time = (~t["outcome_status"].isin(["Escalated", "Reopened"])).astype(float)
    sla = np.minimum(1.0, sla_hours / t["resolution_time_hours"].astype(float).clip(lower=0.1)).fillna(1.0)
    t = t.assign(tre=first_time * sla)
    tw = t.groupby("week").agg(tickets=("ticket_id", "size"), frus=("frustration_score", "mean"),
                               rep_flag=("repeat_contact", "mean"))
    weeks = sorted(int(w) for w in wk.index)
    out = []
    for w in weeks:
        lo = w - rolling + 1
        win = wk.loc[(wk.index >= lo) & (wk.index <= w)]
        eei = round(100 - float(win["b_sum"].sum() / win["n"].sum()), 1)
        dhs = round(float(win["h_sum"].sum() / win["n"].sum()), 1)
        tt = t[(t["week"] >= lo) & (t["week"] <= w)]
        if len(tt):
            rss = round(100 * (1 - float((tt["prev_week"] >= lo).mean())), 1)
            tre = round(float(tt["tre"].mean() * 100), 1)
        else:
            rss, tre = 100.0, 100.0
        if len(win) >= 3:
            slope = float(np.polyfit(win.index.astype(float), win["b_mean"].to_numpy(dtype=float), 1)[0])
            sts = round(float(50 - 50 * np.tanh(slope / STS_SLOPE_SCALE)), 1)
        else:
            sts = 50.0
        row = tw.loc[w] if w in tw.index else None
        out.append({"week": w, "dex_score": dex_score(eei, dhs, rss, tre, sts),
                    "eei": eei, "dhs": dhs, "rss": rss, "tre": tre, "sts": sts,
                    "tickets": int(row["tickets"]) if row is not None else 0,
                    "avg_frustration": round(float(row["frus"]), 1) if row is not None else None,
                    "device_health": round(float(wk.at[w, "h_sum"] / wk.at[w, "n"]), 1),
                    "repeat_rate_pct": round(100 * float(row["rep_flag"]), 1) if row is not None else 0.0})
    return out
