"""Executive Insights — plain-language findings generated from the analytics, each traceable to a metric."""
from __future__ import annotations

import pandas as pd

from . import correlation as corr
from . import dex_score


def _period_split(weeks: list[int]) -> tuple[list[int], list[int]]:
    half = max(1, len(weeks) // 2)
    return weeks[:half], weeks[half:]


def executive_insights(store, device_weeks: pd.DataFrame, tickets: pd.DataFrame, outcome: dict, sla: float) -> list[dict]:
    out: list[dict] = []
    if device_weeks.empty:
        return out

    head = corr.headline_correlation(tickets, device_weeks) if len(tickets) >= 3 else {"score": None, "strength": "n/a"}
    if head["score"] is not None:
        out.append({"type": "correlation", "severity": "info", "title": "Sentiment tracks telemetry",
                    "detail": f"Ticket frustration correlates with device telemetry severity at r = {head['score']} "
                              f"({head['strength'].lower()}, n = {head['ticket_level']['n']}). What employees say is a "
                              f"reliable signal of what their devices are doing.",
                    "metric": "correlation_score", "value": head["score"]})

    ranking = corr.impact_ranking(tickets, device_weeks) if len(tickets) else []
    if ranking and ranking[0]["impact_score"] > 0:
        r = ranking[0]
        out.append({"type": "driver", "severity": "high", "title": f"{r['label']} is the #1 experience driver",
                    "detail": f"Breaches drive ~{r['excess_tickets']:.0f} excess tickets across {r['devices_affected']} "
                              f"devices, at average frustration {r['avg_frustration']} "
                              f"(+{r['frustration_uplift']} vs baseline), {r['repeat_share_pct']:.0f}% repeat contacts.",
                    "metric": "impact_score", "value": r["impact_score"]})

    pol = corr.policy_incidence(device_weeks, tickets)
    if pol["noncompliant_weeks"]:
        out.append({"type": "policy", "severity": "high", "title": "Non-compliance generates login tickets",
                    "detail": f"Non-compliant device-weeks raise a Login/Auth ticket {pol['noncompliant_rate_pct']:.1f}% "
                              f"of the time vs {pol['compliant_rate_pct']:.1f}% when compliant — policy remediation is "
                              f"ticket prevention.", "metric": "noncompliant_rate_pct", "value": pol["noncompliant_rate_pct"]})

    first, second = _period_split(sorted(device_weeks["week"].unique().tolist()))
    a = dex_score.compute_components(device_weeks[device_weeks["week"].isin(first)],
                                     tickets[tickets["week"].isin(first)], sla)
    b = dex_score.compute_components(device_weeks[device_weeks["week"].isin(second)],
                                     tickets[tickets["week"].isin(second)], sla)
    if a.get("available") and b.get("available"):
        delta = round(b["dex_score"] - a["dex_score"], 1)
        out.append({"type": "trend", "severity": "positive" if delta >= 0 else "high",
                    "title": f"DEX Score {'improved' if delta >= 0 else 'declined'} {abs(delta)} pts",
                    "detail": f"Weeks {first[0]}-{first[-1]}: {a['dex_score']} → weeks {second[0]}-{second[-1]}: "
                              f"{b['dex_score']}, driven by EEI {a['components']['eei']} → {b['components']['eei']} and "
                              f"remediation success {a['components']['rss']} → {b['components']['rss']}.",
                    "metric": "dex_delta", "value": delta})

    if outcome.get("cases") and outcome.get("dex", {}).get("available"):
        d = outcome["dex"]
        agg = outcome["aggregate"]
        out.append({"type": "outcome", "severity": "positive", "title": f"Remediation recovered experience "
                                                                          f"{d['experience_recovery_pct']:+.1f}%",
                    "detail": f"Across {outcome['cases']} fixes, cohort DEX rose {d['before']['dex_score']} → "
                              f"{d['after']['dex_score']}; repeat contacts {agg['repeat_rate']['pre']:.1f}% → "
                              f"{agg['repeat_rate']['post']:.1f}%, tickets/week {agg['ticket_rate']['pre']:.2f} → "
                              f"{agg['ticket_rate']['post']:.2f}.",
                    "metric": "experience_recovery_pct", "value": d["experience_recovery_pct"]})
        bi = outcome.get("business_impact")
        if bi:
            out.append({"type": "value", "severity": "positive", "title": f"${bi['total_annual_savings_usd']:,} annualised value",
                        "detail": f"~{bi['annual_tickets_avoided']:.0f} tickets avoided and "
                                  f"{bi['productivity_hours_recovered']:.0f} productive hours recovered per year "
                                  f"(assumptions editable in Settings).",
                        "metric": "total_annual_savings_usd", "value": bi["total_annual_savings_usd"]})

    by_dept = []
    for dep, g in device_weeks.groupby("department"):
        c = dex_score.compute_components(g, tickets[tickets["department"] == dep], sla)
        by_dept.append((dep, c["dex_score"], c["components"]["eei"]))
    if len(by_dept) > 1:
        worst = min(by_dept, key=lambda x: x[1])
        best = max(by_dept, key=lambda x: x[1])
        out.append({"type": "cohort", "severity": "medium", "title": f"{worst[0]} has the lowest DEX Score",
                    "detail": f"{worst[0]} scores {worst[1]} vs {best[1]} in {best[0]} (EEI {worst[2]} vs {best[2]}). "
                              f"Prioritise its at-risk devices in the next remediation wave.",
                    "metric": "dept_dex_gap", "value": round(best[1] - worst[1], 1)})
    return out
