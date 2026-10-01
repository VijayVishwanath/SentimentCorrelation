"""DEX Copilot tool registry — provider-neutral definitions over the analytics engines.

Every number the Copilot reports must come from one of these tools, so the
LLM grounds its narrative in DEX Sentinel data instead of inventing figures.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from ..config import get_settings
from ..data.store import get_store
from ..engines import correlation as corr
from ..engines import dex_score
from ..engines import experience as exp
from ..engines import forecast
from ..engines import outcomes
from ..engines import telemetry as tel
from ..engines.diagnosis import diagnose
from ..engines.thresholds import CATEGORIES, ISSUE_LABEL
from .retriever import get_kb


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., Any]


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def effective_config() -> dict:
    from .. import db
    cfg = get_settings().model_dump()
    cfg.update(db.get_setting_overrides())
    return cfg


# ---------------------------------------------------------------- handlers
def score_ticket_text(text: str, repeat_contacts: int = 0, escalations: int = 0) -> dict:
    r = exp.analyze_text(text, int(repeat_contacts or 0), int(escalations or 0)).as_dict()
    from ..engines import dimensions as dims
    d = dims.score_dimensions(text, int(repeat_contacts or 0), int(escalations or 0) > 0)
    return {**{k: r[k] for k in ("frustration_score", "text_score", "sentiment", "severity", "emotion", "matched_phrases")},
            "dimensions": {k: {"score": d[k]["score"], "level": d[k]["level"],
                               "cues": [c["family"] for c in d[k]["cues"]]} for k in dims.DIMENSIONS},
            "primary_concern": d["primary_concern"]}


def get_device_profile(device_id: str) -> dict:
    s = get_store()
    d = s.device(device_id)
    if d is None:
        return {"error": f"unknown device_id {device_id}"}
    h = s.device_history(device_id)
    last = h.iloc[-1]
    tk = s.device_tickets(device_id)
    comp = dex_score.compute_components(h, tk, effective_config()["resolution_sla_hours"])
    rem = s.remediations[s.remediations["device_id"] == device_id]
    trend = h[["week", "boot_duration_sec", "app_hang_count", "network_latency_ms", "packet_loss_pct",
               "hardware_health_score", "policy_compliant", "device_health", "ticket_count"]]
    return {
        "device": d, "latest_week": int(last["week"]),
        "dex_score": comp.get("dex_score"), "dex_components": comp.get("components"),
        "device_health_latest": float(last["device_health"]),
        "weekly_trend": trend.round(2).to_dict("records"),
        "tickets": tk.sort_values("week")[["ticket_id", "week", "category", "channel", "ticket_text",
                                           "frustration_score", "outcome_status"]].to_dict("records"),
        "remediations": rem[["remediation_id", "week_of_remediation", "action_taken", "root_cause_category"]].to_dict("records"),
    }


def diagnose_ticket(text: str, device_id: str, week: int | None = None,
                    repeat_contacts: int = 0, escalations: int = 0) -> dict:
    s = get_store()
    if s.device(device_id) is None:
        return {"error": f"unknown device_id {device_id}"}
    d = diagnose(text, device_id, s, week=week, repeat_contacts=int(repeat_contacts or 0),
                 escalations=int(escalations or 0))
    return {
        "device": d["device"], "experience": {k: d["experience"][k] for k in
                                              ("frustration_score", "severity", "emotion", "sentiment")},
        "device_health": d["telemetry"]["device_health"], "telemetry_severity": d["telemetry"]["telemetry_severity"],
        "vitals": d["telemetry"]["vitals"],
        "root_causes": [{"category": c["category"], "likelihood": c["likelihood"], "confidence": c["confidence"],
                         "top_subcauses": c["subcauses"][:3], "evidence": [e["text"] for e in c["evidence"]]}
                        for c in d["root_causes"][:3]],
        "primary": d["primary"], "recommendation": d["recommendation"], "standard_action": d["standard_action"],
        "expected_outcome": d["expected_outcome"], "history": {k: d["history"][k] for k in
                                                                ("prior_tickets", "prior_same_category")},
        "inconclusive": d["inconclusive"],
    }


def search_knowledge_base(query: str, category: str | None = None, subcause: str | None = None) -> dict:
    return {"results": get_kb().search(query, top_k=3, category=category, subcause=subcause)}


def get_remediation_outcomes(category: str | None = None) -> dict:
    rep = outcomes.outcome_report(get_store(), effective_config(), category=category or None)
    if not rep["cases"]:
        return {"cases": 0}
    return {"cases": rep["cases"], "improved_cases": rep["improved_cases"],
            "aggregate": {k: rep["aggregate"][k] for k in ("frustration", "repeat_rate", "ticket_rate")},
            "dex_before": rep["dex"]["before"]["dex_score"], "dex_after": rep["dex"]["after"]["dex_score"],
            "experience_recovery_pct": rep["dex"]["experience_recovery_pct"],
            "business_impact": rep["business_impact"],
            "by_category": [{k: c[k] for k in ("category", "cases", "action", "recovery_pct")} for c in rep["by_category"]]}


def get_fleet_overview(department: str | None = None) -> dict:
    s = get_store()
    dw, tk = s.device_weeks, s.tickets_enriched
    if department:
        dw, tk = dw[dw["department"] == department], tk[tk["department"] == department]
    if dw.empty:
        return {"error": f"no data for department {department}"}
    cfg = effective_config()
    comp = dex_score.compute_components(dw, tk, cfg["resolution_sla_hours"])
    ranking = corr.impact_ranking(tk, dw)[:4]
    by_dept = []
    for dep, g in s.device_weeks.groupby("department"):
        c = dex_score.compute_components(g, s.tickets_enriched[s.tickets_enriched["department"] == dep],
                                         cfg["resolution_sla_hours"])
        by_dept.append({"department": dep, "dex_score": c["dex_score"], "eei": c["components"]["eei"]})
    return {"scope": department or "fleet", "dex_score": comp["dex_score"], "band": comp["band"],
            "components": comp["components"], "supporting": comp["supporting"],
            "correlation": corr.headline_correlation(tk, dw),
            "top_telemetry_drivers": [{k: r[k] for k in ("label", "excess_tickets", "avg_frustration", "devices_affected",
                                                         "impact_score")} for r in ranking],
            "departments": sorted(by_dept, key=lambda d: d["dex_score"])}


def find_at_risk_devices(department: str | None = None, limit: int = 5) -> dict:
    s = get_store()
    latest_w = max(s.weeks)
    window = s.device_weeks[s.device_weeks["week"] > latest_w - 4]
    if department:
        window = window[window["department"] == department]
    g = window.groupby("device_id").agg(device_health=("device_health", "mean"),
                                        telemetry_severity=("telemetry_severity", "mean"),
                                        tickets=("ticket_count", "sum"),
                                        burden=("experience_burden", "mean")).reset_index()
    g["risk"] = tel.rule_risk(g["telemetry_severity"], g["burden"])
    sev_cols = [f"sev_{c}" for c in CATEGORIES]
    sevf = tel.category_severity_frame(window)
    sev = window[["device_id"]].join(sevf.add_prefix("sev_")).groupby("device_id")[sev_cols].mean()
    primary = (sev.idxmax(axis=1).str.replace("sev_", "", regex=False).map(ISSUE_LABEL)
               .where(sev.max(axis=1) > 0, "No telemetry breach"))
    g = g.sort_values("risk", ascending=False).head(max(1, min(int(limit or 5), 20)))
    dev = s.devices.set_index("device_id")
    return {"window_weeks": f"{latest_w - 3}-{latest_w}", "devices": [
        {"device_id": r.device_id, "employee_name": dev.at[r.device_id, "employee_name"],
         "department": dev.at[r.device_id, "department"], "device_health": round(r.device_health, 1),
         "telemetry_severity": round(r.telemetry_severity, 1), "tickets_last_4w": int(r.tickets),
         "primary_issue": primary.get(r.device_id, "n/a"),
         "risk_score": round(r.risk, 1)} for r in g.itertuples()]}


def predict_next_week_risk(department: str | None = None, limit: int = 5) -> dict:
    fc = forecast.get_forecaster(get_store())
    w = fc.watchlist(effective_config(), top=max(1, min(int(limit or 5), 20)), department=department or None)
    if not w["available"]:
        return {"available": False, "reason": w["reason"]}
    bt = fc.metrics["backtest"]
    return {"available": True, "as_of_week": w["as_of_week"], "predicts_week": w["predicts_week"],
            "summary": w["summary"],
            "model_backtest": {"ml_recall_pct": bt["ml"]["recall_pct"], "rules_recall_pct": bt["rules"]["recall_pct"],
                               "ml_roc_auc": bt["ml"]["roc_auc"], "operating_point": "top 5% of devices per week",
                               "low_sample": fc.metrics["low_sample"]},
            "devices": [{k: i[k] for k in ("device_id", "employee_name", "department", "risk_pct", "band", "category",
                                           "action", "kb_id")} | {"drivers": [d["text"] for d in i["drivers"]]}
                        for i in w["items"]]}


TOOLS: list[Tool] = [
    Tool("score_ticket_text", "Score employee ticket/call/chat text for frustration (0-100), sentiment, emotion and "
         "severity, including repeat-contact and escalation boosts, plus three dimensions beyond frustration: "
         "business impact, urgency and trust in IT (each 0-100 with the cues behind it).",
         _obj({"text": {"type": "string"}, "repeat_contacts": {"type": "integer", "description": "prior contacts"},
               "escalations": {"type": "integer"}}, ["text"]), score_ticket_text),
    Tool("get_device_profile", "Get a device's owner, 12-week telemetry trend, DEX score, tickets and remediation history.",
         _obj({"device_id": {"type": "string", "description": "e.g. DEV-0002"}}, ["device_id"]), get_device_profile),
    Tool("diagnose_ticket", "Run the Diagnosis Assist root-cause engine for a ticket on a device: ranked causes with "
         "confidence, sub-causes, telemetry evidence, recommended fix and expected outcome from past remediations.",
         _obj({"text": {"type": "string"}, "device_id": {"type": "string"},
               "week": {"type": "integer", "description": "telemetry week 1-12; omit for latest"},
               "repeat_contacts": {"type": "integer"}, "escalations": {"type": "integer"}}, ["text", "device_id"]),
         diagnose_ticket),
    Tool("search_knowledge_base", "Search remediation runbooks (RAG). Returns article id, title, snippet and "
         "remediation steps. Cite article ids you use.",
         _obj({"query": {"type": "string"}, "category": {"type": "string", "enum": CATEGORIES + ["General"]},
               "subcause": {"type": "string"}}, ["query"]), search_knowledge_base),
    Tool("get_remediation_outcomes", "Before/after remediation outcomes: frustration, repeat-contact rate, ticket rate, "
         "DEX score recovery and business-impact savings, optionally for one root-cause category.",
         _obj({"category": {"type": "string", "enum": CATEGORIES}}, []), get_remediation_outcomes),
    Tool("get_fleet_overview", "Fleet or department DEX score, components, correlation strength, top telemetry drivers "
         "and department ranking.", _obj({"department": {"type": "string"}}, []), get_fleet_overview),
    Tool("find_at_risk_devices", "List devices with the highest combined telemetry severity and experience burden "
         "over the last 4 weeks (proactive remediation candidates).",
         _obj({"department": {"type": "string"}, "limit": {"type": "integer"}}, []), find_at_risk_devices),
    Tool("predict_next_week_risk", "Predictive ML model: devices most likely to raise a frustrated ticket NEXT week "
         "(before the employee calls), with calibrated risk %, the telemetry/experience drivers behind each "
         "prediction, the recommended proactive fix and runbook, and backtest accuracy vs the rule baseline.",
         _obj({"department": {"type": "string"}, "limit": {"type": "integer"}}, []), predict_next_week_risk),
]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}


def run_tool(name: str, args: dict) -> tuple[str, bool]:
    """Execute a tool; returns (json_result, is_error)."""
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        return json.dumps({"error": f"unknown tool {name}"}), True
    allowed = set(tool.parameters["properties"])
    clean = {k: v for k, v in (args or {}).items() if k in allowed and v is not None}
    missing = [r for r in tool.parameters["required"] if r not in clean]
    if missing:
        return json.dumps({"error": f"missing required argument(s): {missing}"}), True
    try:
        out = tool.handler(**clean)
    except Exception as e:  # tool failures are reported to the model, not raised
        return json.dumps({"error": f"{type(e).__name__}: {e}"}), True
    return json.dumps(out, default=str)[:20000], "error" in out if isinstance(out, dict) else False
