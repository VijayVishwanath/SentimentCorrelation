"""Analytics API: executive dashboard, experience, telemetry, correlation, DEX score, outcomes, devices."""
from __future__ import annotations

import io
import threading
from typing import Literal

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..copilot.tools import effective_config, find_at_risk_devices
from ..data.store import DataStore
from ..engines import correlation as corr
from ..engines import dex_score, insights, outcomes
from ..engines import telemetry as tel
from ..engines.thresholds import (ACTION_BY_CATEGORY, CATEGORIES, CATEGORY_PRIMARY_SIGNAL, THRESHOLDS,
                                  TELEMETRY_SIGNALS, signal_state)
from .deps import CleanRoute, Filters, filters, scoped, store_dep, table_query

router = APIRouter(route_class=CleanRoute)

# --------------------------------------------------------------- memo cache
_cache: dict = {}
_cache_lock = threading.Lock()
_generation = 0  # bumped by clear_cache: a result computed before a settings/data change is never stored


def memo(store: DataStore, name: str, key: tuple, fn):
    k = (id(store), name, key)
    with _cache_lock:
        if k in _cache:
            return _cache[k]
        gen = _generation
    val = fn()
    with _cache_lock:
        if gen == _generation:
            if len(_cache) > 256:
                _cache.clear()
            _cache[k] = val
    return val


def clear_cache() -> None:
    global _generation
    with _cache_lock:
        _cache.clear()
        _generation += 1


def _sla() -> float:
    return float(effective_config()["resolution_sla_hours"])


def _by_group(dw: pd.DataFrame, tk: pd.DataFrame, col: str) -> list[dict]:
    out = []
    for val, g in dw.groupby(col):
        c = dex_score.compute_components(g, tk[tk[col] == val], _sla())
        out.append({"group": val, "dex_score": c["dex_score"], "band": c["band"], **c["components"],
                    "devices": c["supporting"]["devices"], "tickets": c["supporting"]["tickets"],
                    "avg_frustration": c["supporting"]["avg_frustration"]})
    return sorted(out, key=lambda d: d["dex_score"])


# --------------------------------------------------------------- executive
@router.get("/dashboard/executive", summary="Executive Dashboard KPIs, trends, drivers and insights")
def executive_dashboard(f: Filters = Depends(filters), store: DataStore = Depends(store_dep)):
    def build():
        dw, tk = scoped(store, f)
        if dw.empty:
            raise HTTPException(404, "no data for the selected filters")
        cfg = effective_config()
        sla = cfg["resolution_sla_hours"]
        comp = dex_score.compute_components(dw, tk, sla)
        weeks = sorted(dw["week"].unique().tolist())
        half = max(1, len(weeks) // 2)
        prev = dex_score.compute_components(dw[dw["week"].isin(weeks[:half])], tk[tk["week"].isin(weeks[:half])], sla)
        curr = dex_score.compute_components(dw[dw["week"].isin(weeks[half:])], tk[tk["week"].isin(weeks[half:])], sla)
        oc = outcomes.outcome_report(store, cfg, department=f.department)
        head = corr.headline_correlation(tk, dw) if len(tk) >= 3 else {"score": None, "strength": "n/a"}
        drivers = corr.experience_drivers(tk) if len(tk) else {"phrases": [], "behaviours": []}
        risk = find_at_risk_devices(department=f.department, limit=8)
        weekly = [{"week": w, "week_start": store.week_dates.get(w),
                   "tickets": int((tk["week"] == w).sum()),
                   "avg_frustration": round(float(tk.loc[tk["week"] == w, "frustration_score"].mean()), 1)
                   if (tk["week"] == w).any() else None,
                   "repeat_rate_pct": round(100 * float(tk.loc[tk["week"] == w, "repeat_contact"].mean()), 1)
                   if (tk["week"] == w).any() else None} for w in weeks]
        return {
            "filters": f.describe(),
            "scope": {"devices": int(dw["device_id"].nunique()), "tickets": int(len(tk)), "weeks": weeks},
            "kpis": {
                "dex_score": comp["dex_score"], "dex_band": comp["band"],
                "dex_delta": round(curr["dex_score"] - prev["dex_score"], 1) if prev.get("available") and curr.get("available") else None,
                "components": comp["components"], "contributions": comp["contributions"],
                "employee_experience_index": comp["components"]["eei"],
                "device_health_score": comp["components"]["dhs"],
                "experience_recovery_pct": oc.get("dex", {}).get("experience_recovery_pct"),
                "correlation_score": head["score"], "correlation_strength": head["strength"],
                "repeat_contact_rate_pct": comp["supporting"]["repeat_contact_rate_pct"],
                "avg_frustration": comp["supporting"]["avg_frustration"],
                "business_impact_savings_usd": (oc.get("business_impact") or {}).get("total_annual_savings_usd"),
                "at_risk_devices": len([d for d in risk["devices"] if d["risk_score"] >= 30]),
            },
            "dex_trend": dex_score.weekly_series(dw, tk, sla),
            "frustration_trend": weekly,
            "top_experience_drivers": {"phrases": drivers["phrases"][:6], "behaviours": drivers["behaviours"],
                                       "by_channel": drivers.get("by_channel", [])},
            "top_telemetry_drivers": corr.impact_ranking(tk, dw)[:6] if len(tk) else [],
            "departments": _by_group(dw, tk, "department"),
            "outcome_summary": {"cases": oc.get("cases"), "aggregate": oc.get("aggregate"),
                                "dex_before": oc.get("dex", {}).get("before", {}).get("dex_score"),
                                "dex_after": oc.get("dex", {}).get("after", {}).get("dex_score"),
                                "business_impact": oc.get("business_impact")},
            "at_risk": risk,
            "insights": insights.executive_insights(store, dw, tk, oc, sla),
        }
    return memo(store, "exec", f.key(), build)


# --------------------------------------------------------------- command center
# telemetry signal -> root-cause category whose runbook fixes it
SIGNAL_CATEGORY = {sig: cat for cat, sig in CATEGORY_PRIMARY_SIGNAL.items()} | {"packet_loss": "Network",
                                                                                  "battery": "Hardware", "disk": "Hardware"}


def _action_plan(exec_d: dict, oc: dict, cfg: dict, total_devices: int, n_weeks: int, cost: float) -> list[dict]:
    """Rank fixes by projected value: the top telemetry drivers, costed with the observed before/after
    effect of the matching remediation category."""
    by_cat = {c["category"]: c for c in oc.get("by_category") or []}
    plan, seen = [], set()
    for drv in exec_d["top_telemetry_drivers"]:
        cat = SIGNAL_CATEGORY.get(drv["signal"])
        if not cat or cat in seen:
            continue
        seen.add(cat)
        eff = by_cat.get(cat, {})
        reduction = outcomes.ticket_reduction_pct(eff)  # 0 when this fix type did not cut tickets
        per_year = drv["excess_tickets"] / max(1, n_weeks) * 52 * reduction / 100
        dex_gain = ((eff.get("dex_after") or 0) - (eff.get("dex_before") or 0)) * drv["devices_affected"] / max(1, total_devices)
        plan.append({
            "category": cat, "signal": drv["signal"], "problem": drv["label"], "devices_affected": drv["devices_affected"],
            "excess_tickets": round(drv["excess_tickets"]), "avg_frustration": drv["avg_frustration"],
            "action": eff.get("action") or ACTION_BY_CATEGORY[cat], "evidence_cases": eff.get("cases", 0),
            "ticket_reduction_pct": round(reduction, 1), "tickets_avoided_per_year": round(per_year),
            "savings_per_year_usd": round(per_year * cost), "dex_gain_pts": round(max(0.0, dex_gain), 1),
        })
    return sorted(plan, key=lambda a: a["savings_per_year_usd"], reverse=True)


@router.get("/dashboard/command-center", summary="Outcome-first landing view: headline numbers and the next best actions")
def command_center(f: Filters = Depends(filters), store: DataStore = Depends(store_dep)):
    exec_d = executive_dashboard(f, store)

    def build():
        from ..engines import forecast
        cfg = effective_config()
        k = exec_d["kpis"]
        oc = outcomes.outcome_report(store, cfg, department=f.department)
        cost = outcomes.cost_per_ticket(store, cfg)
        plan = _action_plan(exec_d, oc, cfg, exec_d["scope"]["devices"], len(exec_d["scope"]["weeks"]), cost)
        wl = forecast.get_forecaster(store).watchlist(cfg, top=5, department=f.department)
        top3 = plan[:3]
        target = min(100.0, k["dex_score"] + sum(a["dex_gain_pts"] for a in top3))
        agg = (oc.get("aggregate") or {}).get("ticket_rate") or {}
        from ..engines import roi as roi_engine
        ben = roi_engine.annual_benefits(store, cfg, f.department)
        return {
            "scope": exec_d["scope"], "filters": exec_d["filters"],
            "headline": {
                "dex_score": k["dex_score"], "dex_band": k["dex_band"], "dex_delta": k["dex_delta"],
                "dex_target": round(target, 1),
                "predicted": {"available": wl.get("available", False), "week": wl.get("predicts_week"),
                              "frustrated_tickets": (wl.get("summary") or {}).get("expected_frustrated_tickets"),
                              "devices_elevated": (wl.get("summary") or {}).get("flagged")},
                "value": {"annual_savings_usd": k["business_impact_savings_usd"], "fixes": oc.get("cases"),
                          "ticket_reduction_pct": outcomes.ticket_reduction_pct({"ticket_rate": agg}),
                          "hours_recovered": (oc.get("business_impact") or {}).get("productivity_hours_recovered")},
                "top_problem": plan[0] if plan else None,
                "benefits": {k: ben[k] for k in ("total_usd", "data_backed_usd")}
                            | {"components": [{"label": c["label"], "value_usd": c["value_usd"]} for c in ben["components"]]},
            },
            "trend": [{"week": t["week"], "dex_score": t["dex_score"], "avg_frustration": t["avg_frustration"]}
                      for t in exec_d["dex_trend"]],
            "actions": plan,
            "roadmap": {"from": k["dex_score"], "to": round(target, 1), "levers": len(top3),
                        "savings_per_year_usd": sum(a["savings_per_year_usd"] for a in top3),
                        "tickets_avoided_per_year": sum(a["tickets_avoided_per_year"] for a in top3)},
            "departments": [{"group": d["group"], "dex_score": d["dex_score"], "avg_frustration": d["avg_frustration"]}
                            for d in exec_d["departments"]],
            "watchlist": [{k2: i[k2] for k2 in ("device_id", "employee_name", "department", "risk_pct", "band",
                                                 "category", "action")} for i in wl.get("items", [])],
            "insights": [{"severity": i["severity"], "title": i["title"]} for i in exec_d["insights"][:4]],
            "cost_per_ticket_usd": round(cost, 2),
        }
    from ..remediation.runbooks import mark_fix_applied
    d = memo(store, "command", f.key(), build)
    return {**d, "watchlist": mark_fix_applied(d["watchlist"])}  # live: a Fix now run shows at once


# --------------------------------------------------------------- annual benefits (ROI)
@router.get("/roi", summary="Annual Benefits: ticket cost + productivity + license + hardware refresh savings")
def roi(f: Filters = Depends(filters), store: DataStore = Depends(store_dep),
        scenario: Literal["realized", "with_plan"] = "realized",
        tickets_avoided: float | None = Query(None, ge=0), cost_per_ticket_usd: float | None = Query(None, ge=0),
        affected_employees: float | None = Query(None, ge=0), minutes_saved_per_day: float | None = Query(None, ge=0, le=480),
        working_days_per_year: float | None = Query(None, ge=0, le=366),
        hourly_employee_cost_usd: float | None = Query(None, ge=0), unused_licenses: float | None = Query(None, ge=0),
        annual_license_cost_usd: float | None = Query(None, ge=0), avoided_replacements: float | None = Query(None, ge=0),
        device_cost_usd: float | None = Query(None, ge=0)):
    """Query values are what-if overrides for this view only; save defaults with PUT /settings."""
    from ..engines import roi as roi_engine
    plan = None
    if scenario == "with_plan":
        top3 = command_center(f, store)["actions"][:3]
        plan = {"devices": sum(a["devices_affected"] for a in top3),
                "tickets_avoided_per_year": sum(a["tickets_avoided_per_year"] for a in top3)}
    overrides = {k: v for k, v in locals().items() if k in roi_engine.INPUT_KEYS and v is not None}
    return roi_engine.annual_benefits(store, effective_config(), f.department, plan, overrides)


@router.get("/roi/critical-few", summary="Pareto 80/20: the few issue types behind most of the impact, with priority score and ROI")
def roi_critical_few(f: Filters = Depends(filters), store: DataStore = Depends(store_dep)):
    from ..engines import pareto
    return memo(store, "critical_few", f.key(), lambda: pareto.critical_few(
        store, effective_config(), scoped(store, f)[1], f.department, outcome_report(None, f.department, store)))


# --------------------------------------------------------------- experience
@router.get("/experience/summary", summary="Module 1 — Experience Analytics summary")
def experience_summary(f: Filters = Depends(filters), store: DataStore = Depends(store_dep)):
    def build():
        dw, tk = scoped(store, f)
        if tk.empty:
            return {"filters": f.describe(), "kpis": {"tickets": 0}}
        comp = dex_score.compute_components(dw, tk, _sla())
        hist = np.histogram(tk["frustration_score"], bins=range(0, 110, 10))
        weekly = tk.groupby("week").agg(tickets=("ticket_id", "count"), avg_frustration=("frustration_score", "mean"),
                                        repeat_contacts=("repeat_contact", "sum"), escalations=("escalated", "sum"),
                                        avg_sentiment=("sentiment", "mean")).reset_index().round(2)

        def dist(col, order=None):
            g = tk.groupby(col).agg(count=("ticket_id", "count"), avg_frustration=("frustration_score", "mean")).reset_index()
            if order:
                g[col] = pd.Categorical(g[col], order, ordered=True)
                g = g.sort_values(col)
            return [{"value": str(r[col]), "count": int(r["count"]), "share_pct": round(100 * r["count"] / len(tk), 1),
                     "avg_frustration": round(float(r["avg_frustration"]), 1)} for _, r in g.iterrows()]

        return {
            "filters": f.describe(),
            "kpis": {"tickets": int(len(tk)), "avg_frustration": round(float(tk["frustration_score"].mean()), 1),
                     "employee_experience_index": comp["components"]["eei"],
                     "repeat_contact_rate_pct": round(100 * float(tk["repeat_contact"].mean()), 1),
                     "escalation_rate_pct": round(100 * float(tk["escalated"].mean()), 1),
                     "critical_high_share_pct": round(100 * float(tk["severity"].isin(["Critical", "High"]).mean()), 1),
                     "negative_sentiment_share_pct": round(100 * float((tk["sentiment"] < -0.2).mean()), 1),
                     "avg_sentiment": round(float(tk["sentiment"].mean()), 3)},
            "severity": dist("severity", ["Low", "Medium", "High", "Critical"]),
            "emotion": dist("emotion"), "channel": dist("channel"), "category": dist("category"),
            "outcome_status": dist("outcome_status"),
            "histogram": [{"bin": f"{int(hist[1][i])}-{int(hist[1][i + 1])}", "count": int(hist[0][i])}
                          for i in range(len(hist[0]))],
            "weekly": weekly.to_dict("records"),
            "by_department": _by_group(dw, tk, "department"),
            "drivers": corr.experience_drivers(tk),
            "repeat_ladder": [{"contact_number": int(k), "tickets": int(v),
                               "avg_frustration": round(float(tk.loc[tk["repeat_number"] == k, "frustration_score"].mean()), 1)}
                              for k, v in tk["repeat_number"].value_counts().sort_index().items()],
        }
    return memo(store, "exp", f.key(), build)


TICKET_COLUMNS = {"ticket_id": "text", "device_id": "text", "employee_name": "text", "department": "enum",
                  "week": "num", "channel": "enum", "category": "enum", "ticket_text": "text", "emotion": "enum",
                  "severity": "enum", "frustration_score": "num", "outcome_status": "enum", "repeat_number": "num"}


@router.get("/experience/tickets", summary="Search / page tickets with experience scores")
def experience_tickets(request: Request, f: Filters = Depends(filters), store: DataStore = Depends(store_dep),
                       severity: str | None = None, emotion: str | None = None, channel: str | None = None,
                       category: str | None = None, q: str | None = None, device_id: str | None = None,
                       sort: Literal["frustration", "week", "ticket_id"] = "frustration",
                       sort_by: str | None = None, order: Literal["asc", "desc"] = "asc",
                       limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    """Header sorting/filtering: sort_by + order, and f_<column> filters (see deps.table_query)."""
    _, tk = scoped(store, f)
    for col, val in (("severity", severity), ("emotion", emotion), ("channel", channel), ("category", category),
                     ("device_id", device_id)):
        if val:
            tk = tk[tk[col] == val]
    if q:
        tk = tk[tk["ticket_text"].str.contains(q, case=False, regex=False)
                | tk["ticket_id"].str.contains(q, case=False, regex=False)
                | tk["employee_name"].str.contains(q, case=False, regex=False)]
    tk, options, sorted_ = table_query(tk, request.query_params, TICKET_COLUMNS)
    if not sorted_:
        key = {"frustration": ["frustration_score", False], "week": ["week", False], "ticket_id": ["ticket_id", True]}[sort]
        tk = tk.sort_values(key[0], ascending=key[1])
    cols = ["ticket_id", "device_id", "employee_name", "department", "week", "date", "channel", "category",
            "repeat_contact", "repeat_number", "ticket_text", "resolution_time_hours", "outcome_status",
            "text_score", "frustration_score", "sentiment", "severity", "emotion", "telemetry_severity"]
    return {"total": int(len(tk)), "offset": offset, "limit": limit, "options": options,
            "items": tk[cols].iloc[offset:offset + limit]}


@router.get("/experience/tickets/{ticket_id}/explain", summary="How one ticket's frustration score was computed")
def explain_ticket(ticket_id: str, store: DataStore = Depends(store_dep)):
    from ..engines import experience as exp
    tk = store.tickets_enriched
    row = tk[tk["ticket_id"] == ticket_id]
    if row.empty:
        raise HTTPException(404, f"unknown ticket_id {ticket_id}")
    r = row.iloc[0]
    out = exp.explain(r["ticket_text"], int(r["prior_contacts"]), int(bool(r["escalated"])))
    out["ticket"] = {k: r[k] for k in ("ticket_id", "device_id", "employee_name", "department", "week", "channel",
                                       "category", "outcome_status", "repeat_number", "frustration_score")}
    out["inputs"] = {"prior_contacts": int(r["prior_contacts"]), "escalated": bool(r["escalated"]),
                     "reopened": bool(r["reopened"]),
                     "prior_contacts_rule": "repeat number − 1, plus 1 if the ticket was reopened"}
    return out


# --------------------------------------------------------------- telemetry
def _latest_per_device(dw: pd.DataFrame) -> pd.DataFrame:
    return dw.sort_values("week").groupby("device_id").tail(1)


@router.get("/telemetry/summary", summary="Module 2 — Telemetry Intelligence summary")
def telemetry_summary(f: Filters = Depends(filters), store: DataStore = Depends(store_dep)):
    def build():
        dw, tk = scoped(store, f)
        if dw.empty:
            raise HTTPException(404, "no data for the selected filters")
        latest = _latest_per_device(dw)
        bands = latest["device_health"].map(tel.health_band).value_counts()
        weekly = dw.groupby("week").agg(
            boot_duration_sec=("boot_duration_sec", "mean"), app_hang_count=("app_hang_count", "mean"),
            network_latency_ms=("network_latency_ms", "mean"), packet_loss_pct=("packet_loss_pct", "mean"),
            hardware_health_score=("hardware_health_score", "mean"), device_health=("device_health", "mean"),
            telemetry_severity=("telemetry_severity", "mean"), compliance_pct=("policy_compliant", "mean"),
            vpn_failures=("vpn_failure", "sum"), crash_events=("crash_events", "sum")).reset_index()
        weekly["compliance_pct"] *= 100
        breaches = []
        for key in ["boot", "latency", "packet_loss", "hangs", "hw_health", "battery", "disk"]:
            col = TELEMETRY_SIGNALS[key][0]
            th = THRESHOLDS[key]
            v = pd.to_numeric(dw[col], errors="coerce")
            if th["critical"] < th["warn"]:  # lower is worse
                crit, warn = v < th["critical"], (v < th["warn"]) & (v >= th["critical"])
            else:
                crit, warn = v > th["critical"], (v > th["warn"]) & (v <= th["critical"])
            breaches.append({"signal": key, "label": TELEMETRY_SIGNALS[key][1], "warn": int(warn.sum()),
                             "critical": int(crit.sum()),
                             "devices_affected": int(dw.loc[warn | crit, "device_id"].nunique()),
                             "thresholds": th})
        nc = dw["non_compliant"].astype(bool)
        breaches.append({"signal": "noncompliant", "label": "Policy non-compliance", "warn": 0, "critical": int(nc.sum()),
                         "devices_affected": int(dw.loc[nc, "device_id"].nunique()), "thresholds": None})
        by_model = dw.groupby("device_model").agg(devices=("device_id", "nunique"), device_health=("device_health", "mean"),
                                                   boot=("boot_duration_sec", "mean"), hangs=("app_hang_count", "mean"),
                                                   latency=("network_latency_ms", "mean"),
                                                   hw=("hardware_health_score", "mean"),
                                                   tickets=("ticket_count", "sum")).reset_index().round(2)
        return {
            "filters": f.describe(),
            "kpis": {"device_health_score": round(float(dw["device_health"].mean()), 1),
                     "telemetry_severity_score": round(float(dw["telemetry_severity"].mean()), 1),
                     "healthy_devices_pct": round(100 * float((latest["device_health"] >= 80).mean()), 1),
                     "compliance_pct": round(100 * float(dw["policy_compliant"].mean()), 1),
                     "vpn_failure_weeks": int(dw["vpn_failure"].sum()), "crash_events": int(dw["crash_events"].sum()),
                     "avg_boot_sec": round(float(dw["boot_duration_sec"].mean()), 1),
                     "avg_latency_ms": round(float(dw["network_latency_ms"].mean()), 1),
                     "devices": int(dw["device_id"].nunique())},
            "health_bands": [{"band": b, "devices": int(bands.get(b, 0))} for b in ["Healthy", "Degraded", "Poor"]],
            "weekly": weekly.round(2).to_dict("records"),
            "breaches": breaches,
            "by_model": by_model.to_dict("records"),
            "derived_signal_notes": {"crash_events": "Application-Crash tickets logged for the device-week",
                                     "vpn_failure": "device-weeks with packet loss >= 1.5% (warn)"},
        }
    return memo(store, "tel", f.key(), build)


DEVICE_COLUMNS = {"device_id": "text", "employee_name": "text", "department": "enum", "work_mode": "enum",
                  "device_model": "enum", "device_health": "num", "health_band": "enum", "boot_duration_sec": "num",
                  "network_latency_ms": "num", "app_hang_count": "num", "policy_compliant": "bool", "tickets": "num",
                  "risk_score": "num", "remediated": "bool", "age_months": "num"}


@router.get("/telemetry/devices", summary="Device list with latest vitals, health and DEX")
def telemetry_devices(request: Request, f: Filters = Depends(filters), store: DataStore = Depends(store_dep),
                      q: str | None = None, band: str | None = None,
                      sort: Literal["risk", "health", "dex", "tickets", "device_id"] = "risk",
                      sort_by: str | None = None, order: Literal["asc", "desc"] = "asc",
                      limit: int = Query(50, ge=1, le=300), offset: int = Query(0, ge=0)):
    """Header sorting/filtering: sort_by + order, and f_<column> filters (see deps.table_query)."""
    def build():
        dw, tk = scoped(store, f)
        latest = _latest_per_device(dw).set_index("device_id")
        agg = dw.groupby("device_id").agg(tickets=("ticket_count", "sum"), avg_health=("device_health", "mean"),
                                          avg_severity=("telemetry_severity", "mean"),
                                          burden=("experience_burden", "mean"))
        # vectorised: one row per device (latest-week vitals + window aggregates)
        j = latest.join(agg, how="left")
        h = j["device_health"].astype(float)
        out = pd.DataFrame({
            "device_id": j.index.astype(str), "employee_name": j["employee_name"].values,
            "department": j["department"].values, "device_model": j["device_model"].values,
            "work_mode": j["work_mode"].values, "age_months": j["age_months"].fillna(0).astype(int).values,
            "latest_week": j["week"].astype(int).values, "device_health": h.round(1).values,
            "health_band": np.where(h >= 80, "Healthy", np.where(h >= 65, "Degraded", "Poor")),
            "avg_device_health": j["avg_health"].round(1).values,
            "telemetry_severity": j["avg_severity"].round(1).values, "tickets": j["tickets"].fillna(0).astype(int).values,
            "eei": (100 - j["burden"]).round(1).values,
            "risk_score": (j["avg_severity"] * 0.6 + j["burden"] * 0.4).round(1).values,
            "boot_duration_sec": j["boot_duration_sec"].values,
            "app_hang_count": j["app_hang_count"].round().astype("Int64").values,
            "network_latency_ms": j["network_latency_ms"].values,
            "policy_compliant": j["policy_compliant"].astype(bool).values,
            "hardware_health_score": j["hardware_health_score"].values,
        })
        out["remediated"] = out["device_id"].isin(store.remediated_devices)
        return out
    df = memo(store, "devs", f.key(), build)
    if q:
        m = df["device_id"].str.contains(q, case=False) | df["employee_name"].str.contains(q, case=False)
        df = df[m]
    if band:
        df = df[df["health_band"] == band]
    df, options, sorted_ = table_query(df, request.query_params, DEVICE_COLUMNS)
    if not sorted_:
        key = {"risk": ("risk_score", False), "health": ("avg_device_health", True), "dex": ("eei", True),
               "tickets": ("tickets", False), "device_id": ("device_id", True)}[sort]
        df = df.sort_values(key[0], ascending=key[1])
    return {"total": int(len(df)), "offset": offset, "limit": limit, "options": options,
            "items": df.iloc[offset:offset + limit]}


@router.get("/devices/{device_id}", summary="Device 360: profile, weekly telemetry, tickets, remediations, DEX")
def device_detail(device_id: str, store: DataStore = Depends(store_dep)):
    d = store.device(device_id)
    if d is None:
        raise HTTPException(404, f"device {device_id} not found")
    h = store.device_history(device_id)
    if h.empty:
        raise HTTPException(404, f"no telemetry recorded yet for device {device_id}")
    tk = store.device_tickets(device_id).sort_values("week")
    rem = store.remediations[store.remediations["device_id"] == device_id]
    comp = dex_score.compute_components(h, tk, _sla())
    last = h.iloc[-1].to_dict()
    cols = ["week", "week_start", "boot_duration_sec", "app_hang_count", "network_latency_ms", "packet_loss_pct",
            "policy_compliant", "hardware_health_score", "battery_health_pct", "disk_health_pct", "device_health",
            "telemetry_severity", "ticket_count", "experience_burden"]
    rem_rows = []
    for r in rem.to_dict("records"):
        cd = outcomes.case_dex(store, r, _sla())
        rem_rows.append({**r, "dex_before": cd["before"].get("dex_score"), "dex_after": cd["after"].get("dex_score")})
    return {"device": d, "dex": comp, "vitals": tel.vitals(last),
            "category_severity": tel.category_severity(last), "history": h[cols],
            "tickets": tk[["ticket_id", "week", "date", "channel", "category", "ticket_text", "frustration_score",
                           "severity", "emotion", "repeat_number", "outcome_status", "resolution_time_hours"]],
            "remediations": rem_rows}


# --------------------------------------------------------------- correlation
@router.get("/correlation/analysis", summary="Module 3 — Correlation Engine")
def correlation_analysis(f: Filters = Depends(filters), store: DataStore = Depends(store_dep),
                         score: Literal["frustration", "text"] = "frustration"):
    def build():
        dw, tk = scoped(store, f)
        if len(tk) < 5:
            raise HTTPException(422, "not enough tickets in scope for correlation (need >= 5)")
        col = "frustration_score" if score == "frustration" else "text_score"
        return {"filters": f.describe(), "score_basis": col,
                "headline": corr.headline_correlation(tk, dw),
                "lift": corr.lift_analysis(tk, dw, col),
                "matrix": corr.correlation_matrix(tk, dw),
                "impact_ranking": corr.impact_ranking(tk, dw),
                "experience_drivers": corr.experience_drivers(tk),
                "category_evidence": corr.category_evidence(tk)}
    return memo(store, f"corr-{score}", f.key(), build)


@router.get("/correlation/heatmap", summary="Risk heatmap: cohort x telemetry signal")
def correlation_heatmap(by: Literal["department", "device_model", "work_mode"] = "department",
                        f: Filters = Depends(filters), store: DataStore = Depends(store_dep)):
    def build():
        dw, tk = scoped(store, f)
        return {"risk": corr.risk_heatmap(dw, tk, by),
                "trend": corr.frustration_trend_heatmap(tk, sorted(dw["week"].unique().tolist()), by)}
    return memo(store, f"heat-{by}", f.key(), build)


@router.get("/correlation/scatter", summary="Ticket-level scatter: telemetry reading vs frustration")
def correlation_scatter(signal: Literal["boot", "latency", "packet_loss", "hangs", "hw_health", "battery", "disk",
                                        "severity"] = "severity",
                        f: Filters = Depends(filters), store: DataStore = Depends(store_dep)):
    _, tk = scoped(store, f)
    col = "telemetry_severity" if signal == "severity" else TELEMETRY_SIGNALS[signal][0]
    pts = tk[["ticket_id", "device_id", "category", col, "frustration_score"]].rename(columns={col: "x", "frustration_score": "y"})
    fit = None
    if len(pts) >= 3 and pts["x"].nunique() > 1:
        m, b = np.polyfit(pts["x"].astype(float), pts["y"].astype(float), 1)
        fit = {"slope": round(float(m), 4), "intercept": round(float(b), 2)}
    return {"signal": signal, "label": "Telemetry severity (composite)" if signal == "severity" else TELEMETRY_SIGNALS[signal][1],
            "points": pts, "fit": fit, "correlation": corr._corr(pts["y"], pts["x"])}


# --------------------------------------------------------------- DEX score
@router.get("/dex-score", summary="Module 7 — DEX Score with components, trend and cohort breakdown")
def dex(f: Filters = Depends(filters), store: DataStore = Depends(store_dep)):
    def build():
        dw, tk = scoped(store, f)
        if dw.empty:
            raise HTTPException(404, "no data for the selected filters")
        sla = _sla()
        return {"filters": f.describe(), "score": dex_score.compute_components(dw, tk, sla),
                "weekly": dex_score.weekly_series(dw, tk, sla),
                "by_department": _by_group(dw, tk, "department"),
                "by_device_model": _by_group(dw, tk, "device_model"),
                "by_work_mode": _by_group(dw, tk, "work_mode"),
                "formula": {"expression": "DEX = 0.35·EEI + 0.25·DHS + 0.20·RSS + 0.10·TRE + 0.10·STS",
                            "weights": dex_score.WEIGHTS, "labels": dex_score.COMPONENT_LABELS,
                            "definitions": {
                                "eei": "100 − mean weekly frustration burden per employee-week (0 when no contact)",
                                "dhs": "Mean Device Health Score = (100 − 0.1·boot − 3·hangs − 4·crashes − 0.05·latency)·0.8 + 0.2·hardware health",
                                "rss": "100 × (1 − repeat-contact rate), repeats recomputed within the window",
                                "tre": "Mean of first-time-resolution × SLA attainment per ticket",
                                "sts": "50 − 50·tanh(weekly burden slope / 10): 50 = flat, higher = improving"}}}
    return memo(store, "dex", f.key(), build)


# --------------------------------------------------------------- outcomes
@router.get("/outcomes/uplift", summary="Causal uplift of fixes: difference-in-differences vs matched never-fixed devices")
def outcome_uplift(category: str | None = None, department: str | None = None, store: DataStore = Depends(store_dep)):
    from ..engines import uplift
    return uplift.causal_uplift(store, category or None, department or None)


@router.get("/outcomes", summary="Module 6 — Outcome Reporting (before vs after remediation)")
def outcome_report(category: str | None = None, department: str | None = None, store: DataStore = Depends(store_dep)):
    known = sorted(set(CATEGORIES) | set(store.remediations["root_cause_category"].dropna()))
    if category and category not in known:
        raise HTTPException(422, f"category must be one of {known}")
    return memo(store, "outcomes", (category, department),
                lambda: outcomes.outcome_report(store, effective_config(), category, department))


@router.get("/outcomes/export.csv", summary="Download remediation outcome register as CSV")
def outcome_export(category: str | None = None, department: str | None = None, store: DataStore = Depends(store_dep)):
    rep = outcomes.outcome_report(store, effective_config(), category, department)
    buf = io.StringIO()
    pd.DataFrame(rep["rows"]).to_csv(buf, index=False)
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=dex_sentinel_outcomes.csv"})
