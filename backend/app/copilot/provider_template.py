"""Deterministic DEX Copilot — grounded narrative composed directly from tool outputs.

Used when no LLM is configured, or as the automatic fallback when an LLM call
fails. It calls the same tools as the LLM providers, so its trace, citations
and numbers are identical in provenance.
"""
from __future__ import annotations

import json
import re

from ..data.store import get_store
from .tools import effective_config, run_tool


def _call(name: str, args: dict, trace: list[dict]) -> dict:
    out, is_err = run_tool(name, args)
    trace.append({"tool": name, "input": args, "is_error": is_err, "output_preview": out[:300]})
    return json.loads(out)


def _prediction_block(pred: dict) -> str:
    if not pred.get("available"):
        return ""
    bt = pred["model_backtest"]
    lines = [f"{d['device_id']} ({d['employee_name']}) — {d['risk_pct']}% risk"
             + (f"; {d['drivers'][0]}" if d["drivers"] else "") + f" → {d['action']}"
             + (f" ({d['kb_id']})" if d.get("kb_id") else "") for d in pred["devices"][:3]]
    return (f"\n\n**Predicted for week {pred['predicts_week']} (ML):** {pred['summary']['flagged']} devices at elevated "
            f"risk of a frustrated ticket; in backtest the model caught {bt['ml_recall_pct']}% of them a week early "
            f"vs {bt['rules_recall_pct']}% for the rule score.\n" + "\n".join(f"- {line}" for line in lines))


def _steps(markdown: str) -> list[str]:
    return [re.sub(r"^\d+\.\s*", "", ln).strip() for ln in (markdown or "").splitlines() if re.match(r"^\d+\.", ln)]


class TemplateCopilot:
    name = "template"
    model = "grounded-template-v1"

    def run(self, question: str, device_id: str | None, ticket_text: str | None,
            week: int | None) -> tuple[dict, list[dict]]:
        trace: list[dict] = []
        if device_id and not ticket_text:
            prof = _call("get_device_profile", {"device_id": device_id}, trace)
            tickets = prof.get("tickets") or []
            if tickets:
                ticket_text, week = tickets[-1]["ticket_text"], tickets[-1]["week"]
            else:
                return self._device_only(question, prof, trace), trace
        if device_id and ticket_text:
            return self._ticket(question, ticket_text, device_id, week, trace), trace
        return self._fleet(question, trace), trace

    # ------------------------------------------------------------ ticket
    def _ticket(self, question, text, device_id, week, trace) -> dict:
        d = _call("diagnose_ticket", {"text": text, "device_id": device_id, "week": week}, trace)
        if "error" in d:
            return self._error(question, d["error"])
        p, exp_ = d["primary"], d["experience"]
        top = d["root_causes"][0]
        kb = _call("search_knowledge_base", {"query": f"{text} {p.get('subcause') or ''}",
                                             "category": p["category"], "subcause": p.get("subcause")}, trace)
        art = kb["results"][0] if kb.get("results") else None
        oc = _call("get_remediation_outcomes", {"category": p["category"]}, trace)
        dev = d["device"]
        cfg = effective_config()

        evidence = list(top["evidence"])
        evidence.append(f"Frustration {exp_['frustration_score']}/100 ({exp_['severity']}, {exp_['emotion'].lower()} tone)")
        if d["history"]["prior_same_category"] > 1:
            evidence.append(f"{d['history']['prior_same_category']} {p['category']} tickets on this device so far")
        if d["inconclusive"]:
            driver = "No telemetry anomaly detected"
        else:
            driver = f"{p['category']} — {p['subcause']}" if p.get("subcause") else p["category"]

        eo = d.get("expected_outcome")
        if eo:
            expected = (f"Based on {eo['based_on_cases']} past {p['category']} remediations: repeat contacts "
                        f"-{eo['repeat_contact_reduction_pct']:.0f}%, ticket rate -{eo['ticket_rate_reduction_pct']:.0f}%, "
                        + (f"DEX Score {oc.get('dex_before')} → {oc.get('dex_after')} "
                           f"({oc.get('experience_recovery_pct'):+.1f}% experience recovery)."
                           if oc.get("experience_recovery_pct") is not None else ""))
        else:
            expected = "No historical remediations of this category to benchmark against."

        weeks = max(1, int(dev.get("week", 1)))
        rate = d["history"]["prior_tickets"] / weeks
        red = (eo or {}).get("ticket_rate_reduction_pct", 0) / 100
        avoided = rate * 52 * red
        avg_hours = float(get_store().tickets_enriched["resolution_time_hours"].mean())
        per_ticket = cfg["cost_per_ticket_usd"] + avg_hours * cfg["productivity_loss_factor"] * cfg["hourly_employee_cost_usd"]
        impact = (f"{dev['employee_name']} ({dev['department']}) has raised {d['history']['prior_tickets']} ticket(s) "
                  f"in {weeks} weeks. Fixing the cause avoids ~{avoided:.1f} tickets/year for this employee "
                  f"(~${avoided * per_ticket:,.0f} in support and lost productivity) and removes a repeat-contact "
                  f"loop that drives frustration.")
        steps = _steps(art["remediation"]) if art else []
        cites = [f"diagnose_ticket:{device_id}:week{dev['week']}"] + ([art["id"]] if art else []) + \
                [f"remediation_outcomes:{p['category']}"]
        others = ", ".join(f"{c['category']} {c['likelihood']}%" for c in d["root_causes"][1:3])
        explanation = (f"The fusion engine (65% telemetry severity, 35% ticket language) ranks {p['category']} at "
                       f"{p['likelihood']}% likelihood with {p['confidence']}% confidence"
                       + (f" (next: {others})" if others else "") + ". "
                       + (f"Within {p['category']}, '{p['subcause']}' is the leading sub-cause given the ticket "
                          f"wording and device history. " if p.get("subcause") else "")
                       + ("Telemetry corroborates the complaint." if top.get("confidence", 0) >= 60
                          else "Telemetry only weakly corroborates the complaint — verify before remediating."))
        return {
            "ticket_summary": f"{dev['employee_name']} reports: \"{text.strip()}\" — {exp_['severity'].lower()} "
                              f"frustration ({exp_['frustration_score']}/100).",
            "executive_summary": (f"{driver} is the most likely cause on {device_id} ({p['confidence']}% confidence). "
                                  f"Recommended action: {d['recommendation']}. "
                                  + (f"Past fixes of this type cut repeat contacts by {eo['repeat_contact_reduction_pct']:.0f}% "
                                     f"and ticket rate by {eo['ticket_rate_reduction_pct']:.0f}%." if eo else "")),
            "primary_driver": driver,
            "root_cause_explanation": explanation,
            "supporting_evidence": evidence,
            "recommended_fix": d["recommendation"],
            "remediation_steps": steps or [d["standard_action"]],
            "expected_outcome": expected,
            "business_impact": impact,
            "confidence": int(p["confidence"]),
            "answer": (f"**Primary driver:** {driver}\n\n**Evidence:** " + "; ".join(e.rstrip(".") for e in evidence[:3])
                       + f"\n\n**Recommendation:** {d['recommendation']}"
                       + (f" (runbook {art['id']})" if art else "") + f"\n\n**Expected outcome:** {expected}"),
            "citations": cites,
        }

    # ------------------------------------------------------------ fleet
    def _fleet(self, question: str, trace) -> dict:
        q = (question or "").lower()
        f_all = _call("get_fleet_overview", {}, trace)
        depts = [d["department"] for d in f_all.get("departments", [])]
        dept = next((d for d in depts if d.lower() in q), None)
        f = _call("get_fleet_overview", {"department": dept}, trace) if dept else f_all
        risk = _call("find_at_risk_devices", {"department": dept, "limit": 5}, trace)
        oc = _call("get_remediation_outcomes", {}, trace)
        pred = _call("predict_next_week_risk", {"department": dept, "limit": 3}, trace)
        drv =f["top_telemetry_drivers"][0] if f.get("top_telemetry_drivers") else None
        worst = f_all["departments"][0] if f_all.get("departments") else None
        kb = _call("search_knowledge_base", {"query": (drv or {}).get("label", "outcome closure")}, trace)
        art = kb["results"][0] if kb.get("results") else None
        corr = f["correlation"]
        scope = dept or "the fleet"
        risk_lines = [f"{r['device_id']} ({r['employee_name']}, {r['department']}) — health {r['device_health']}, "
                      f"{r['primary_issue']}, risk {r['risk_score']}" for r in risk.get("devices", [])[:3]]
        has_oc = bool(oc.get("cases")) and oc.get("experience_recovery_pct") is not None
        bi = oc.get("business_impact") or {}
        answer = (f"**DEX Score ({scope}):** {f['dex_score']} ({f['band']})\n\n"
                  f"**Correlation:** frustration vs telemetry severity r = {corr['score']} ({corr['strength'].lower()})\n\n"
                  + (f"**Top telemetry driver:** {drv['label']} — {drv['excess_tickets']:.0f} excess tickets, "
                     f"avg frustration {drv['avg_frustration']}\n\n" if drv else "")
                  + (f"**Lowest-scoring department:** {worst['department']} (DEX {worst['dex_score']})\n\n" if worst and not dept else "")
                  + "**Proactive candidates:**\n" + "\n".join(f"- {r}" for r in risk_lines)
                  + _prediction_block(pred))
        return {
            "ticket_summary": f"Question: {question.strip()}" if question else "Fleet experience overview",
            "executive_summary": (f"{scope.capitalize()} DEX Score is {f['dex_score']} ({f['band']}). "
                                  f"Employee sentiment tracks endpoint telemetry ({corr['strength'].lower()}, r = {corr['score']}), "
                                  + (f"with {drv['label'].lower()} the largest driver of excess tickets. " if drv else "")
                                  + (f"Past remediations recovered DEX by {oc['experience_recovery_pct']:+.1f}%." if has_oc
                                     else "No remediation records are loaded yet, so recovery cannot be measured.")),
            "primary_driver": drv["label"] if drv else "n/a",
            "root_cause_explanation": ("Impact ranking weighs excess tickets on breached device-weeks (vs the healthy-week "
                                       "ticket rate) by the frustration they carry and their repeat-contact share."),
            "supporting_evidence": [f"{d['label']}: {d['excess_tickets']:.0f} excess tickets, {d['devices_affected']} devices, "
                                    f"avg frustration {d['avg_frustration']}" for d in f.get("top_telemetry_drivers", [])[:3]]
                                   + [f"EEI {f['components']['eei']}, Device Health {f['components']['dhs']}, "
                                      f"Remediation Success {f['components']['rss']}"],
            "recommended_fix": (f"Run a targeted remediation wave for {drv['label'].lower()} on the "
                                f"{drv['devices_affected']} affected devices, starting with the at-risk list."
                                if drv else "Maintain current posture."),
            "remediation_steps": _steps(art["remediation"]) if art else [],
            "expected_outcome": (f"Across {oc['cases']} past remediations, repeat-contact rate fell "
                                 f"{oc['aggregate']['repeat_rate']['pre']:.1f}% → {oc['aggregate']['repeat_rate']['post']:.1f}% "
                                 f"and DEX recovered {oc['experience_recovery_pct']:+.1f}%." if has_oc
                                 else "Upload remediation records (Module 8) to measure before/after recovery."),
            "business_impact": (f"The remediated cohort avoids ~{bi['annual_tickets_avoided']:.0f} tickets/year and "
                                f"recovers ~{bi['productivity_hours_recovered']:.0f} productive hours — "
                                f"~${bi['total_annual_savings_usd']:,} per year at current cost assumptions." if bi
                                else "Business impact is calculated once remediation outcomes are available."),
            "confidence": 80 if corr["strength"] == "Strong" else 60,
            "answer": answer,
            "citations": ["get_fleet_overview", "find_at_risk_devices", "remediation_outcomes"]
                         + (["predict_next_week_risk"] if pred.get("available") else []) + ([art["id"]] if art else []),
        }

    def _device_only(self, question, prof, trace) -> dict:
        d = prof["device"]
        return {"ticket_summary": f"Device profile for {d['device_id']} ({d['employee_name']}).",
                "executive_summary": f"{d['device_id']} has no tickets; DEX Score {prof['dex_score']}.",
                "primary_driver": "No reported issue", "root_cause_explanation": "No service-desk contact to diagnose.",
                "supporting_evidence": [f"Device health {prof['device_health_latest']}"], "recommended_fix": "None required",
                "remediation_steps": [], "expected_outcome": "n/a", "business_impact": "n/a", "confidence": 50,
                "answer": f"{d['device_id']} has no tickets in the window. Latest device health {prof['device_health_latest']}.",
                "citations": [f"get_device_profile:{d['device_id']}"]}

    @staticmethod
    def _error(question, msg) -> dict:
        return {"ticket_summary": question, "executive_summary": msg, "primary_driver": "n/a",
                "root_cause_explanation": msg, "supporting_evidence": [], "recommended_fix": "n/a",
                "remediation_steps": [], "expected_outcome": "n/a", "business_impact": "n/a", "confidence": 0,
                "answer": msg, "citations": []}
