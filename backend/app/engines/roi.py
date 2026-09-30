"""Annual Benefits (ROI) of DEX Sentinel.

    Annual Benefits = Ticket Cost Savings + Productivity Recovery + License Savings + Hardware Refresh Savings

    Ticket Cost Savings     = Tickets Avoided × Average Cost Per Ticket
    Productivity Recovery   = (Affected Employees × Minutes Saved Per Day × Working Days Per Year) ÷ 60
                              × Average Hourly Employee Cost
    License Savings         = Unused Licenses × Annual License Cost
    Hardware Refresh        = Avoided Replacements × Device Cost

Every input carries its source: "measured" (from the dataset), "derived" (computed from measured data with a
stated rule) or "assumption" (a default to replace with real data). Ticket cost uses the support cost per
ticket only; the employee's lost time is counted once, in Productivity Recovery.
"""
from __future__ import annotations

from ..engines import outcomes, uplift

INPUT_KEYS = ("tickets_avoided", "cost_per_ticket_usd", "affected_employees", "minutes_saved_per_day",
              "working_days_per_year", "hourly_employee_cost_usd", "unused_licenses", "annual_license_cost_usd",
              "avoided_replacements", "device_cost_usd")
VOLUME_INPUTS = {"tickets": ("tickets_avoided",), "productivity": ("affected_employees", "minutes_saved_per_day"),
                 "licenses": ("unused_licenses",), "hardware": ("avoided_replacements",)}


def _inp(value, source: str, note: str, unit: str = "") -> dict:
    return {"value": round(float(value), 2), "source": source, "note": note, "unit": unit}


def annual_benefits(store, cfg: dict, department: str | None = None, plan: dict | None = None,
                    overrides: dict | None = None) -> dict:
    """plan: the Command Center roadmap ({devices, tickets_avoided_per_year}) to add planned fixes to realised ones."""
    oc = outcomes.outcome_report(store, cfg, department=department)
    bi = oc.get("business_impact") or {}
    rem = store.remediations if not department else store.remediations[store.remediations["department"] == department]
    agg = oc.get("aggregate") or {}
    employees = int(rem["device_id"].nunique()) if len(rem) else 0
    naive_tickets = float(bi.get("annual_tickets_avoided") or 0.0)
    causal = uplift.annual_tickets_avoided(uplift.causal_uplift(store, department=department))
    # causal = beyond what matched never-fixed devices did anyway; falls back to the naive count without a control group
    tickets = causal if causal is not None else naive_tickets
    causal_share = min(1.0, tickets / naive_tickets) if naive_tickets > 0 else 1.0
    days = float(cfg["working_days_per_year"])

    # Minutes saved per affected employee per day, from what the fixes actually changed (causal share of the downtime)
    downtime_min = 60 * float(bi.get("productivity_hours_recovered") or 0) * causal_share / max(1, employees) / days
    boot_min = max(0.0, -((agg.get("boot") or {}).get("change") or 0)) * cfg["roi_boots_per_day"] / 60
    hang_min = max(0.0, -((agg.get("hangs") or {}).get("change") or 0)) * cfg["roi_minutes_per_hang"] / 5
    derived_minutes = downtime_min + boot_min + hang_min

    if plan:
        employees += int(plan.get("devices") or 0)
        tickets += float(plan.get("tickets_avoided_per_year") or 0)
    fleet = len(store.devices) if not department else int((store.devices["department"] == department).sum())
    hw_repairs = int((rem["root_cause_category"] == "Hardware").sum()) if len(rem) else 0
    scope = "past fixes + the Command Center plan" if plan else "past fixes"

    inputs = {
        "tickets_avoided": _inp(round(tickets), "measured", (
            f"tickets per year removed by {scope}, beyond the trend of matched never-fixed devices "
            f"(difference-in-differences × 52; naive before/after would say {round(naive_tickets):,})")
            if causal is not None else f"tickets per year no longer raised after {scope} (pre vs post ticket rate × 52)",
            "tickets/yr"),
        "cost_per_ticket_usd": _inp(cfg["cost_per_ticket_usd"], "assumption", "service-desk handling cost per ticket (Settings)", "$"),
        "affected_employees": _inp(employees, "measured", f"employees whose device was fixed ({scope})", "people"),
        "minutes_saved_per_day": (
            _inp(cfg["roi_minutes_saved_per_day"], "assumption", "set in Settings", "min/day")
            if cfg.get("roi_minutes_saved_per_day") is not None else
            _inp(derived_minutes, "derived", f"ticket downtime avoided {downtime_min:.1f} + faster boot {boot_min:.1f} "
                 f"+ fewer app hangs {hang_min:.1f} min/day", "min/day")),
        "working_days_per_year": _inp(days, "assumption", "working days per employee per year", "days"),
        "hourly_employee_cost_usd": _inp(cfg["hourly_employee_cost_usd"], "assumption", "fully loaded hourly cost (Settings)", "$/h"),
        "unused_licenses": (
            _inp(cfg["roi_unused_licenses"], "assumption", "set in Settings", "licenses")
            if cfg.get("roi_unused_licenses") is not None else
            _inp(round(0.05 * fleet), "assumption", "illustrative 5% of the fleet: replace with software-asset-management "
                 "data (installed but unused for 90 days)", "licenses")),
        "annual_license_cost_usd": _inp(cfg["annual_license_cost_usd"], "assumption", "average annual cost per license", "$/yr"),
        "avoided_replacements": (
            _inp(cfg["roi_avoided_replacements"], "assumption", "set in Settings", "devices")
            if cfg.get("roi_avoided_replacements") is not None else
            _inp(hw_repairs, "derived", "hardware fixes that repaired the device (battery / disk) instead of replacing it",
                 "devices")),
        "device_cost_usd": _inp(cfg["device_cost_usd"], "assumption", "replacement laptop cost", "$"),
    }
    for k, v in (overrides or {}).items():  # what-if values from the page, not saved
        if k in inputs and v is not None:
            inputs[k] = {**inputs[k], "value": round(float(v), 2), "source": "what-if", "note": "entered on this page"}

    x = {k: v["value"] for k, v in inputs.items()}
    hours = x["affected_employees"] * x["minutes_saved_per_day"] * x["working_days_per_year"] / 60
    components = [
        {"key": "tickets", "label": "Ticket Cost Savings", "formula": "Tickets Avoided × Average Cost Per Ticket",
         "inputs": ["tickets_avoided", "cost_per_ticket_usd"], "value_usd": round(x["tickets_avoided"] * x["cost_per_ticket_usd"])},
        {"key": "productivity", "label": "Productivity Recovery",
         "formula": "(Affected Employees × Minutes Saved Per Day × Working Days Per Year) ÷ 60 × Hourly Employee Cost",
         "inputs": ["affected_employees", "minutes_saved_per_day", "working_days_per_year", "hourly_employee_cost_usd"],
         "recovered_hours": round(hours), "value_usd": round(hours * x["hourly_employee_cost_usd"])},
        {"key": "licenses", "label": "License Savings", "formula": "Unused Licenses × Annual License Cost",
         "inputs": ["unused_licenses", "annual_license_cost_usd"], "value_usd": round(x["unused_licenses"] * x["annual_license_cost_usd"])},
        {"key": "hardware", "label": "Hardware Refresh Savings", "formula": "Avoided Replacements × Device Cost",
         "inputs": ["avoided_replacements", "device_cost_usd"], "value_usd": round(x["avoided_replacements"] * x["device_cost_usd"])},
    ]
    total = sum(c["value_usd"] for c in components)
    for c in components:  # data-backed = the volume inputs (how many tickets / people / devices) come from the data
        c["data_backed"] = all(inputs[i]["source"] in ("measured", "derived") for i in VOLUME_INPUTS[c["key"]])
    measured = sum(c["value_usd"] for c in components if c["data_backed"])
    return {
        "scenario": "with_plan" if plan else "realized", "department": department,
        "causal": {"method": "difference-in-differences vs matched never-fixed devices",
                   "naive_tickets_avoided": round(naive_tickets), "causal_tickets_avoided": round(causal or 0),
                   "causal_share_pct": round(100 * causal_share, 1)} if causal is not None else None,
        "total_usd": total, "data_backed_usd": measured,
        "formula": "Annual Benefits = Ticket Cost Savings + Productivity Recovery + License Savings + Hardware Refresh Savings",
        "components": components, "inputs": inputs,
        "note": "Data-backed = components whose volumes come from the dataset (cost rates are your Settings). "
                "License volume is an assumption until software-asset data is connected.",
    }
