"""Critical Few vs Trivial Many: the Pareto (80/20) view of what hurts employees.

Problem → Future risk → Solution → ROI, per issue type. An issue type is a root-cause category and the
diagnosis sub-cause inside it (e.g. Network → VPN tunnel instability), assigned to every ticket with the
same rules the Diagnosis page uses.

Four impact measures per issue type, all counted from the tickets in scope:

    Productivity Impact = Σ resolution hours × productivity loss factor            (employee hours lost)
    Cost Impact         = Σ support touches × cost per ticket                       (touches = 1 + escalated + reopened)
    Employee Impact     = Σ frustration score                                      (negative sentiment burden)
    Risk Impact         = forecast frustrated tickets next week for the category, split across its
                          sub-causes by their share of the category's recent tickets

    Priority Score (0-100) = Productivity Impact + Cost Impact + Employee Impact + Risk Impact,
                             each scaled 0-25 against the largest issue type on that measure

The critical few for a measure = the smallest set of issue types, largest first, that reach 80% of it.
Recommended fix and its annual value use the observed before/after ticket-rate reduction of past fixes in the
same category (fleet average when a category has no fix history yet, labelled as such).
"""
from __future__ import annotations

import math

import pandas as pd

from . import diagnosis, outcomes
from .thresholds import ACTION_BY_CATEGORY

TARGET = 80.0
RECENT_WEEKS = 8
MEASURES = {
    "productivity": ("Productivity loss", "productivity_hours", "h", "productivity loss"),
    "cost": ("IT support cost", "it_cost_usd", "$", "IT support cost"),
    "employee": ("Negative sentiment", "frustration", "pts", "negative sentiment"),
    "incidents": ("Incidents", "incidents", "tickets", "incidents"),
}
PRIORITY_PARTS = {"productivity": "productivity_hours", "cost": "it_cost_usd", "employee": "frustration",
                  "risk": "risk_tickets"}


def _issue(t: dict, device: dict, history: pd.DataFrame) -> tuple[str, str, str, str]:
    text = str(t.get("ticket_text") or "").lower()
    cat = t.get("category")
    if cat not in diagnosis.SUBCAUSES:  # "Other": use the same text + telemetry fusion as Diagnosis
        cat = diagnosis.rank_categories(text, t)[0]["category"]
    ctx = diagnosis.Ctx(text=text, row=t, device=device, history=history, prior_contacts=int(t.get("prior_contacts") or 0))
    top = diagnosis.rank_subcauses(cat, ctx)[0]
    return cat, top["name"], top["fix"], top["kb_id"]


_EMPTY_HISTORY = pd.DataFrame({"app_hang_count": []})


def classify(store, tickets: pd.DataFrame) -> pd.DataFrame:
    """One issue type per ticket (category, sub-cause, fix, KB). The only history a sub-cause rule reads is the
    app-hang trend over the trailing 4 device-weeks, so that is precomputed once instead of slicing per ticket."""
    dw = store.device_weeks[["device_id", "week", "app_hang_count"]].sort_values(["device_id", "week"])
    first = dw.groupby("device_id")["app_hang_count"].shift(3)
    first = first.fillna(dw.groupby("device_id")["app_hang_count"].transform("first"))
    hang = dict(zip(zip(dw["device_id"], dw["week"]), zip(first, dw["app_hang_count"])))
    devices = store.devices.set_index("device_id").to_dict("index")
    rows = []
    for t in tickets.to_dict("records"):
        h = _EMPTY_HISTORY
        if t.get("category") in ("Application Crash", "Other"):
            pair = hang.get((t["device_id"], t["week"]))
            h = pd.DataFrame({"app_hang_count": pair}) if pair else _EMPTY_HISTORY
        rows.append(_issue(t, devices.get(t["device_id"], {}), h))
    return pd.DataFrame(rows, columns=["issue_category", "sub_cause", "fix", "kb_id"], index=tickets.index)


def _forecast_by_category(store, cfg: dict, department: str | None) -> tuple[dict[str, float], bool]:
    """Forecast risk summed by the category of each device's strongest telemetry driver (as Forecaster.explain)."""
    from . import forecast
    fc = forecast.get_forecaster(store)
    if not fc.available:
        return {}, False
    tel = fc.latest_contrib[[g for g in fc.latest_contrib.columns if g in forecast.SIGNAL_FIX]]
    cat = tel.idxmax(axis=1).map(lambda g: forecast.SIGNAL_FIX[g][0]).where(tel.max(axis=1) > 0)
    frame = pd.DataFrame({"category": cat.to_numpy(), "risk": fc.latest_risk})
    if department:
        dept = fc.latest["device_id"].map(store.devices.set_index("device_id")["department"]).to_numpy()
        frame = frame[dept == department]
    return {k: float(v) for k, v in frame.dropna().groupby("category")["risk"].sum().items()}, True


def _pareto(issues: list[dict], key: str) -> dict:
    ranked = sorted(issues, key=lambda i: i[key], reverse=True)
    total = sum(i[key] for i in ranked)
    n = len(ranked)
    if not n or total <= 0:
        return {"total": 0, "issues": n, "critical_count": 0, "critical_issue_pct": 0, "critical_value_pct": 0,
                "top20_count": 0, "top20_value_pct": 0, "curve": []}
    cum, curve, k = 0.0, [], None
    for rank, i in enumerate(ranked, 1):
        share = 100 * i[key] / total
        cum += share
        if k is None and cum >= TARGET - 1e-9:
            k = rank
        curve.append({"id": i["id"], "label": i["sub_cause"], "category": i["category"], "value": round(i[key], 2),
                      "share_pct": round(share, 1), "cumulative_pct": round(cum, 1), "critical": k is None or rank == k})
    top20 = max(1, math.ceil(0.2 * n))
    return {"total": round(total, 2), "issues": n, "critical_count": k,
            "critical_issue_pct": round(100 * k / n, 1), "critical_value_pct": curve[k - 1]["cumulative_pct"],
            "top20_count": top20, "top20_value_pct": curve[top20 - 1]["cumulative_pct"], "curve": curve}


def critical_few(store, cfg: dict, tickets: pd.DataFrame, department: str | None = None, oc: dict | None = None) -> dict:
    """oc: a precomputed outcome_report for the same department (the API passes its memoised copy)."""
    if tickets.empty:
        return {"available": False, "reason": "no tickets in scope"}
    t = tickets.join(classify(store, tickets))
    loss, ticket_cost, hourly = cfg["productivity_loss_factor"], cfg["cost_per_ticket_usd"], cfg["hourly_employee_cost_usd"]
    t["_hours"] = t["resolution_time_hours"].astype(float).fillna(0) * loss
    t["_touches"] = 1 + t["escalated"].astype(int) + t["reopened"].astype(int)
    weeks = sorted(t["week"].unique())
    n_weeks = max(1, len(weeks))
    recent = t[t["week"] > weeks[-1] - RECENT_WEEKS]

    oc = oc if oc is not None else outcomes.outcome_report(store, cfg, department=department)
    effect = {c["category"]: c for c in oc.get("by_category") or []}
    fleet_red = outcomes.ticket_reduction_pct(oc.get("aggregate"))
    fc_cat, fc_ok = _forecast_by_category(store, cfg, department)

    issues = []
    for (cat, sub), g in t.groupby(["issue_category", "sub_cause"]):
        cat_recent = recent[recent["issue_category"] == cat]
        sub_share = float(cat_recent["sub_cause"].eq(sub).mean() if len(cat_recent)
                     else len(g) / max(1, int((t["issue_category"] == cat).sum())))
        # risk: forecast when the model is trained, else the recent weekly ticket rate as the run-rate proxy
        risk = fc_cat.get(cat, 0.0) * sub_share if fc_ok else int(recent["sub_cause"].eq(sub).sum()) / RECENT_WEEKS
        half = weeks[len(weeks) // 2] if len(weeks) > 1 else weeks[0]
        early, late = int((g["week"] < half).sum()), int((g["week"] >= half).sum())
        eff = effect.get(cat)
        red, src = (outcomes.ticket_reduction_pct(eff), "measured") if eff else (fleet_red, "fleet average")
        hours, cost = float(g["_hours"].sum()), float((g["_touches"] * ticket_cost).sum())
        annual_impact = (cost + hours * hourly) * 52 / n_weeks
        issues.append({
            "id": f"{cat} · {sub}", "category": cat, "sub_cause": sub,
            "incidents": int(len(g)), "devices": int(g["device_id"].nunique()), "employees": int(g["employee_name"].nunique()),
            "productivity_hours": round(hours, 1), "productivity_cost_usd": round(hours * hourly),
            "it_cost_usd": round(cost), "frustration": round(float(g["frustration_score"].sum()), 1),
            "avg_frustration": round(float(g["frustration_score"].mean()), 1),
            "high_frustration_tickets": int((g["frustration_score"] >= 60).sum()),
            "risk_tickets": round(risk, 2),
            "trend": {"earlier": early, "later": late,
                      "direction": "rising" if late > early * 1.2 else "falling" if late < early * 0.8 else "steady"},
            "solution": {"fix": g["fix"].mode().iat[0], "kb_id": g["kb_id"].mode().iat[0],
                         "playbook": (eff or {}).get("action") or ACTION_BY_CATEGORY[cat],
                         "evidence_cases": int((eff or {}).get("cases", 0)), "effect_source": src,
                         "ticket_reduction_pct": round(red, 1)},
            "annual_impact_usd": round(annual_impact),
            "roi": {"annual_preventable_usd": round(annual_impact * red / 100),
                    "tickets_avoided_per_year": round(len(g) * 52 / n_weeks * red / 100),
                    "hours_recovered_per_year": round(hours * 52 / n_weeks * red / 100)},
        })

    maxes = {p: max((i[k] for i in issues), default=0) or 1 for p, k in PRIORITY_PARTS.items()}
    totals = {p: sum(i[k] for i in issues) or 1 for p, k in PRIORITY_PARTS.items()}
    for i in issues:
        parts = {p: round(25 * i[k] / maxes[p], 1) for p, k in PRIORITY_PARTS.items()}
        i["priority"] = {"score": round(sum(parts.values()), 1), **parts}
        i["impact_share_pct"] = round(sum(100 * i[k] / totals[p] for p, k in PRIORITY_PARTS.items()) / 4, 2)
    issues.sort(key=lambda i: (i["priority"]["score"], i["roi"]["annual_preventable_usd"]), reverse=True)

    cum, k = 0.0, len(issues)
    for rank, i in enumerate(issues, 1):
        cum += i["impact_share_pct"]
        i["rank"], i["cumulative_impact_pct"] = rank, round(cum, 1)
        if cum >= TARGET - 1e-9 and k == len(issues):
            k = rank
    for i in issues:
        i["critical_few"] = i["rank"] <= k
    crit = [i for i in issues if i["critical_few"]]

    measures = {m: {"label": lab, "phrase": phrase, "unit": unit, **_pareto(issues, key)}
                for m, (lab, key, unit, phrase) in MEASURES.items()}
    statements = [{"measure": m, "issue_pct": d["critical_issue_pct"], "issue_count": d["critical_count"],
                   "value_pct": d["critical_value_pct"], "issues": d["issues"],
                   "text": f"{d['critical_issue_pct']:.0f}% of issue types ({d['critical_count']} of {d['issues']}) "
                           f"account for {d['critical_value_pct']:.0f}% of {d['phrase']}"}
                  for m, d in measures.items()]
    return {
        "available": True, "department": department, "weeks": n_weeks, "tickets": int(len(t)),
        "target_pct": TARGET, "statements": statements, "measures": measures, "issues": issues,
        "critical_few": {
            "count": len(crit), "of": len(issues), "issue_pct": round(100 * len(crit) / max(1, len(issues)), 1),
            "impact_pct": crit[-1]["cumulative_impact_pct"] if crit else 0,
            "annual_impact_usd": sum(i["annual_impact_usd"] for i in crit),
            "annual_preventable_usd": sum(i["roi"]["annual_preventable_usd"] for i in crit),
            "tickets_avoided_per_year": sum(i["roi"]["tickets_avoided_per_year"] for i in crit),
            "hours_recovered_per_year": sum(i["roi"]["hours_recovered_per_year"] for i in crit),
            "risk_tickets_next_week": round(sum(i["risk_tickets"] for i in crit), 1),
        },
        "trivial_many": {"count": len(issues) - len(crit),
                         "annual_impact_usd": sum(i["annual_impact_usd"] for i in issues if not i["critical_few"])},
        "risk_source": "forecast (next week, frustrated tickets)" if fc_ok else f"recent run-rate (last {RECENT_WEEKS} weeks)",
        "formula": "Priority Score = Productivity Impact + Cost Impact + Employee Impact + Risk Impact (each 0–25)",
        "definitions": {
            "productivity": f"Σ resolution hours × productivity loss factor ({loss}) = employee hours lost",
            "cost": f"Σ support touches × ${ticket_cost:g} per ticket (touch = 1 + escalated + reopened)",
            "employee": "Σ frustration score: how much negative sentiment the issue generated",
            "risk": ("forecast frustrated tickets next week for the category, split by the sub-cause's share of "
                     f"the last {RECENT_WEEKS} weeks" if fc_ok else f"tickets per week over the last {RECENT_WEEKS} weeks"),
            "scaling": "each part = 25 × issue value ÷ the largest issue type's value on that measure",
            "critical_few": f"smallest set of top-priority issue types that together hold {TARGET:.0f}% of the combined impact",
            "roi": "annualised (IT cost + productivity cost) × observed ticket-rate reduction of past fixes in the category",
        },
    }
