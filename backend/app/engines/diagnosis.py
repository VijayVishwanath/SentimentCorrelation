"""Module 4 — Diagnosis Assist + Root Cause Engine.

Stage 1 (category): fuse telemetry severity (65%) with ticket-text category
signal (35%) — ported unchanged from the validated prototype.
  * likelihood  = share of the fused score across categories (sums to 100)
  * confidence  = absolute evidence strength of that category (0-99), boosted
                  when the telemetry breach has persisted over recent weeks

Stage 2 (sub-cause): rule-based refinement inside each category using ticket
language, device attributes and telemetry history — e.g. an Outlook crash that
survives repeat contacts points at profile corruption rather than the binary.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from . import experience as exp
from . import telemetry as tel
from .thresholds import ACTION_BY_CATEGORY, CATEGORIES, CATEGORY_PRIMARY_SIGNAL, THRESHOLDS, TELEMETRY_SIGNALS, signal_state

TELEMETRY_WEIGHT = 0.65
TEXT_WEIGHT = 0.35

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Performance": ["boot", "start up", "startup", "freeze", "freezes", "slow", "lags", "login"],
    "Network": ["wifi", "wi-fi", "vpn", "connection", "connect", "drop", "network", "call"],
    "Login/Auth": ["log in", "login", "locked out", "mfa", "authentication", "compliant", "account"],
    "Hardware": ["battery", "overheat", "noise", "charge", "screen", "trackpad", "fan"],
    "Application Crash": ["outlook", "excel", "teams", "crm", "crash", "hang", "freezes"],
}


def text_category_scores(text: str) -> dict[str, int]:
    t = (text or "").lower()
    return {cat: sum(1 for kw in kws if kw in t) for cat, kws in CATEGORY_KEYWORDS.items()}


def rank_categories(text: str, row: dict) -> list[dict]:
    """Prototype-identical fusion. Returns categories sorted by fused score."""
    sev = tel.category_severity(row)
    cats = text_category_scores(text)
    max_cat = max(1, *cats.values())
    combined = {}
    for c in sev:
        sev_norm = min(max(sev[c], 0), tel.SEVERITY_CAP) / tel.SEVERITY_CAP
        text_norm = cats[c] / max_cat
        combined[c] = {"score": TELEMETRY_WEIGHT * sev_norm + TEXT_WEIGHT * text_norm,
                       "telemetry_component": round(sev_norm, 3), "text_component": round(text_norm, 3),
                       "keyword_hits": cats[c], "raw_severity": round(sev[c], 3)}
    ranked = sorted(combined.items(), key=lambda kv: kv[1]["score"], reverse=True)
    total = sum(v["score"] for _, v in ranked) or 1
    return [{"category": c, "likelihood": round(v["score"] / total * 100), **v} for c, v in ranked]


# ---------------------------------------------------------------- sub-causes
@dataclass
class Ctx:
    text: str
    row: dict
    device: dict
    history: pd.DataFrame  # trailing device-weeks up to the diagnosis week
    prior_contacts: int

    def has(self, *words: str) -> bool:
        return any(w in self.text for w in words)

    def trend(self, col: str) -> float:
        h = self.history[col].astype(float)
        return float(h.iloc[-1] - h.iloc[0]) if len(h) >= 2 else 0.0


@dataclass
class SubCause:
    name: str
    fix: str
    kb_id: str
    weight: Callable[[Ctx], float]


SUBCAUSES: dict[str, list[SubCause]] = {
    "Application Crash": [
        SubCause("Application crash / hang loop", "Reinstall and patch the affected application", "KB-APP-001",
                 lambda c: 0.6 + (0.6 if c.row["app_hang_count"] > THRESHOLDS["hangs"]["warn"] else 0)
                 + (0.3 if c.has("crash") else 0)),
        SubCause("Memory leak / resource exhaustion", "Apply app memory hotfix; cap add-in memory; schedule restart policy",
                 "KB-APP-002",
                 lambda c: (0.5 if c.has("freez", "hang", "few sheets", "lags") else 0.1)
                 + (0.4 if c.trend("app_hang_count") >= 2 else 0)),
        SubCause("Mail profile corruption", "Repair / rebuild the Outlook profile (new OST)", "KB-APP-003",
                 lambda c: (0.9 if c.has("outlook") else 0) + (0.3 if c.has("outlook") and c.prior_contacts > 0 else 0)),
        SubCause("Add-in / plugin conflict", "Disable non-essential add-ins; update CRM connector", "KB-APP-004",
                 lambda c: (0.5 if c.has("outlook", "excel", "teams", "crm") else 0) + (0.3 if c.has("save") else 0)),
        SubCause("Outdated / unpatched build", "Push latest application build via software center", "KB-APP-005",
                 lambda c: (0.35 if c.device.get("age_months", 0) >= 36 else 0.1) + (0.3 if not c.row["policy_compliant"] else 0)),
    ],
    "Performance": [
        SubCause("Startup bloat / boot degradation", "Reimage device (fresh OS + SSD optimization)", "KB-PERF-001",
                 lambda c: 0.6 + (0.5 if c.row["boot_duration_sec"] > THRESHOLDS["boot"]["warn"] else 0)
                 + (0.3 if c.has("boot", "start up", "turn it on") else 0)),
        SubCause("Disk degradation", "Run disk diagnostics; replace SSD if SMART errors", "KB-PERF-002",
                 lambda c: 0.9 if c.row["disk_health_pct"] < THRESHOLDS["disk"]["warn"] else 0.1),
        SubCause("Aging hardware (end of refresh cycle)", "Prioritise device in refresh wave", "KB-PERF-003",
                 lambda c: 0.6 if c.device.get("age_months", 0) >= 36 else 0.05),
        SubCause("Post-login policy / script processing", "Optimise GPO/Intune login scripts; stagger updates",
                 "KB-PERF-004", lambda c: (0.5 if c.has("after login", "after i turn it on", "first 10 minutes") else 0)
                 + (0.3 if not c.row["policy_compliant"] else 0)),
    ],
    "Network": [
        SubCause("Wi-Fi adapter / driver instability", "Replace Wi-Fi adapter / update WLAN driver", "KB-NET-001",
                 lambda c: 0.5 + (0.4 if c.has("wi-fi", "wifi", "drop") else 0)
                 + (0.3 if c.row["network_latency_ms"] > THRESHOLDS["latency"]["warn"] else 0)),
        SubCause("VPN tunnel instability", "Re-provision VPN profile; move to split-tunnel gateway", "KB-NET-002",
                 lambda c: (0.8 if c.has("vpn") else 0)
                 + (0.5 if c.row["packet_loss_pct"] >= THRESHOLDS["packet_loss"]["warn"] else 0)),
        SubCause("Home ISP / last-mile quality", "Run home-network assessment; offer 4G/5G fallback", "KB-NET-003",
                 lambda c: (0.5 if c.device.get("work_mode") == "Remote" else 0) + (0.4 if c.has("home") else 0)),
        SubCause("Collaboration traffic QoS", "Push QoS network profile for Teams/video", "KB-NET-004",
                 lambda c: 0.7 if c.has("call", "video", "meeting") else 0.1),
    ],
    "Login/Auth": [
        SubCause("Compliance policy drift", "Push compliance policy update and re-enroll device", "KB-AUTH-001",
                 lambda c: (1.2 if not c.row["policy_compliant"] else 0) + (0.4 if c.has("compliant") else 0)),
        SubCause("MFA token / authenticator desync", "Re-register MFA method; resync device clock", "KB-AUTH-002",
                 lambda c: 0.9 if c.has("mfa", "code") else 0.05),
        SubCause("Account lockout (stale cached credentials)", "Clear cached credentials; unlock account", "KB-AUTH-003",
                 lambda c: 0.9 if c.has("locked out", "account") else 0.05),
        SubCause("VPN certificate / authentication", "Renew device certificate; reissue VPN auth profile", "KB-AUTH-004",
                 lambda c: 0.8 if c.has("vpn authentication") else 0.05),
    ],
    "Hardware": [
        SubCause("Battery degradation", "Replace battery", "KB-HW-001",
                 lambda c: (0.8 if c.row["battery_health_pct"] < THRESHOLDS["battery"]["warn"] else 0.1)
                 + (0.5 if c.has("battery", "charge", "drains") else 0)),
        SubCause("Disk failure risk", "Replace disk; restore user data from backup", "KB-HW-002",
                 lambda c: 0.8 if c.row["disk_health_pct"] < THRESHOLDS["disk"]["warn"] else 0.1),
        SubCause("Thermal / fan failure", "Clean or replace fan; update thermal firmware", "KB-HW-003",
                 lambda c: 0.9 if c.has("overheat", "fan", "noise") else 0.05),
        SubCause("Display / input peripheral fault", "Replace display cable / trackpad assembly", "KB-HW-004",
                 lambda c: 0.9 if c.has("screen", "trackpad", "flicker") else 0.05),
    ],
}


def rank_subcauses(category: str, ctx: Ctx) -> list[dict]:
    scored = [(s, max(0.0, s.weight(ctx))) for s in SUBCAUSES.get(category, [])]
    total = sum(w for _, w in scored) or 1
    ranked = sorted(scored, key=lambda x: x[1], reverse=True)
    return [{"name": s.name, "share": round(100 * w / total), "fix": s.fix, "kb_id": s.kb_id} for s, w in ranked]


# ---------------------------------------------------------------- evidence
def _evidence_for(key: str, row: dict, history: pd.DataFrame, fleet: pd.DataFrame) -> dict:
    if key == "noncompliant":
        weeks = int(history["non_compliant"].sum())
        return {"signal": "policy", "label": "Policy state",
                "value": "Compliant" if row["policy_compliant"] else "Non-compliant",
                "state": "ok" if row["policy_compliant"] else "critical",
                "threshold": "must be compliant", "weeks_breached": weeks, "window_weeks": len(history),
                "fleet_median": f"{100 * (1 - fleet['non_compliant'].mean()):.0f}% of fleet compliant",
                "text": (f"Device is {'compliant' if row['policy_compliant'] else 'NON-compliant'}; "
                         f"non-compliant in {weeks} of the last {len(history)} weeks.")}
    col, label, unit, higher_worse = TELEMETRY_SIGNALS[key]
    th = THRESHOLDS[key]
    if pd.isna(row.get(col)):
        return {"signal": key, "label": label, "value": None, "unit": unit, "state": "na", "threshold": "",
                "weeks_breached": 0, "window_weeks": len(history), "fleet_median": None, "trend": 0.0,
                "text": f"{label} is not measured in this dataset."}
    v = float(row[col])
    breached = history[col].map(lambda x: signal_state(key, x) != "ok")
    med = float(fleet[col].median()) if fleet[col].notna().any() else float("nan")
    cmp = ">" if higher_worse else "<"
    return {"signal": key, "label": label, "value": round(v, 1), "unit": unit, "state": signal_state(key, v),
            "threshold": f"warn {cmp} {th['warn']}{unit}, critical {cmp} {th['critical']}{unit}",
            "weeks_breached": int(breached.sum()), "window_weeks": len(history), "fleet_median": round(med, 1),
            "trend": round(float(history[col].iloc[-1] - history[col].iloc[0]), 1) if len(history) >= 2 else 0.0,
            "text": (f"{label} {v:.1f}{unit} (fleet median {med:.1f}{unit}; {th['warn']}{unit} warn / "
                     f"{th['critical']}{unit} critical); breached {int(breached.sum())} of last {len(history)} weeks.")}


CATEGORY_EVIDENCE_SIGNALS = {
    "Performance": ["boot", "disk"],
    "Network": ["latency", "packet_loss"],
    "Login/Auth": ["noncompliant"],
    "Hardware": ["hw_health", "battery", "disk"],
    "Application Crash": ["hangs"],
}


def expected_outcome(category: str, remediations: pd.DataFrame) -> dict | None:
    r = remediations[remediations["root_cause_category"] == category]
    if r.empty:
        return None

    def red(pre, post):
        p, q = float(r[pre].mean()), float(r[post].mean())
        return round(100 * (p - q) / p, 1) if p else 0.0

    return {"based_on_cases": int(len(r)),
            "repeat_contact_reduction_pct": red("pre_repeat_contact_rate_pct", "post_repeat_contact_rate_pct"),
            "ticket_rate_reduction_pct": red("pre_ticket_rate_per_week", "post_ticket_rate_per_week"),
            "frustration_reduction_pct": red("pre_frustration_score", "post_frustration_score"),
            "typical_action": r["action_taken"].mode().iat[0]}


def diagnose(text: str, device_id: str, store, week: int | None = None,
             repeat_contacts: int = 0, escalations: int = 0, lookback_weeks: int = 4) -> dict:
    device = store.device(device_id)
    if device is None:
        raise KeyError(f"unknown device {device_id}")
    row = store.telemetry_at(device_id, week)
    if row is None:
        raise KeyError(f"no telemetry for device {device_id}")
    hist_all = store.device_history(device_id)
    hist = hist_all[hist_all["week"] <= row["week"]].tail(lookback_weeks)
    fleet = store.device_weeks[store.device_weeks["week"] == row["week"]]
    low = (text or "").lower()

    experience = exp.analyze_text(text, repeat_contacts, escalations).as_dict()
    ranked = rank_categories(text, row)
    ctx = Ctx(low, row, device, hist, repeat_contacts)

    causes = []
    for rc in ranked:
        cat = rc["category"]
        key = CATEGORY_PRIMARY_SIGNAL[cat]
        persist = 0.0
        if key == "noncompliant":
            persist = float(hist["non_compliant"].mean())
        else:
            col = TELEMETRY_SIGNALS[key][0]
            persist = float(hist[col].map(lambda x: signal_state(key, x) != "ok").mean())
        conf = 100 * rc["score"] + (10 * persist if rc["telemetry_component"] > 0 else 0)
        evidence = [_evidence_for(k, row, hist, fleet) for k in CATEGORY_EVIDENCE_SIGNALS[cat]]
        causes.append({**rc, "confidence": int(min(99, round(conf))),
                       "subcauses": rank_subcauses(cat, ctx), "evidence": evidence,
                       "default_action": ACTION_BY_CATEGORY[cat]})

    top = causes[0]
    inconclusive = top["score"] < 0.15
    top_sub = top["subcauses"][0] if top["subcauses"] else None
    prior_tickets = store.device_tickets(device_id)
    prior_tickets = prior_tickets[prior_tickets["week"] <= row["week"]]
    health = tel.device_health_row(row, row.get("crash_events", 0) or 0)
    return {
        "device": {**device, "week": int(row["week"]), "week_start": store.week_dates.get(int(row["week"]))},
        "experience": experience,
        "telemetry": {"vitals": tel.vitals(row), "device_health": health, "health_band": tel.health_band(health),
                      "telemetry_severity": tel.telemetry_severity_score(row)},
        "root_causes": causes,
        "primary": {"category": top["category"], "likelihood": top["likelihood"], "confidence": top["confidence"],
                    "subcause": top_sub["name"] if top_sub else None, "kb_id": top_sub["kb_id"] if top_sub else None},
        "recommendation": ("No telemetry anomaly and no symptom keywords matched — treat as a how-to / request "
                           "and route to L1 knowledge." if inconclusive
                           else (top_sub["fix"] if top_sub else top["default_action"])),
        "standard_action": top["default_action"],
        "inconclusive": inconclusive,
        "expected_outcome": expected_outcome(top["category"], store.remediations),
        "history": {"prior_tickets": int(len(prior_tickets)),
                    "prior_same_category": int((prior_tickets["category"] == top["category"]).sum()),
                    "last_tickets": prior_tickets.sort_values("week", ascending=False).head(5)[
                        ["ticket_id", "week", "category", "ticket_text", "frustration_score", "outcome_status"]
                    ].to_dict("records")},
        "method": {"fusion": f"{int(TELEMETRY_WEIGHT * 100)}% telemetry severity + {int(TEXT_WEIGHT * 100)}% text category",
                   "lookback_weeks": lookback_weeks},
    }


def rank_root_causes(device: dict) -> list[tuple[str, int]]:
    """Spec-compatible helper (requirements.md). Expects crashes/memory_usage/profile_corruption keys."""
    causes = []
    if device.get("crashes", 0) > 5:
        causes.append(("Application Crash", 92))
    if device.get("memory_usage", 0) > 90:
        causes.append(("Memory Leak", 88))
    if device.get("profile_corruption"):
        causes.append(("Profile Corruption", 83))
    return sorted(causes, key=lambda x: x[1], reverse=True)


__all__ = ["diagnose", "rank_categories", "text_category_scores", "rank_root_causes", "CATEGORIES"]
