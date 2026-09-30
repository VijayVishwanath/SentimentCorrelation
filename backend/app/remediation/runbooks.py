"""Runbook actions: the "Fix now" behind every recommended fix.

One runbook per root-cause category (the same actions Diagnosis Assist and the
Command Center recommend). Targets are the devices whose telemetry breaches the
category's signal. Execution reuses the remediation safeguards: a dry-run plan,
a scoped service-account token, per-device atomic steps with rollback, a
verification step and the hash-chained audit log.

Risk policy: low-risk runbooks (policy push, network profile) are auto-approved;
high-risk ones (reinstall, reimage, hardware swap) need a named human approver.
Like software removal, execution is simulated: the steps are what an endpoint
agent would run, and nothing runs on the machine hosting DEX Sentinel.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

import pandas as pd
from sqlalchemy import insert, select

from .. import db
from ..copilot.tools import effective_config
from ..data.store import get_store
from ..engines import outcomes
from ..engines.correlation import _breach
from ..engines.thresholds import TELEMETRY_SIGNALS
from . import audit
from .engine import (RUNS, RemediationError, _check_token, _new_run_id, check_approver, check_plan, issue_token,
                     normalize_device_ids, plan_hash)

MAX_BATCH = 500


@dataclass(frozen=True)
class Runbook:
    runbook_id: str
    category: str
    title: str
    risk: str                  # low = auto-approved, high = needs a named approver
    signals: tuple[str, ...]   # telemetry signals that make a device a target
    steps: tuple[tuple[str, str], ...]
    kb_id: str
    fail_rate: float           # simulated share of devices where a step fails (exercises rollback)


RUNBOOKS: tuple[Runbook, ...] = (
    Runbook("RB-NET-01", "Network", "Push QoS network profile and reset Wi-Fi adapter", "low", ("latency", "packet_loss"),
            (("snapshot", "Export-NetAdapterAdvancedProperty -Name 'Wi-Fi' > C:\\ProgramData\\DEX\\{run}\\wifi.bak"),
             ("apply", "New-NetQosPolicy -Name 'DEX-Collab' -AppPathNameMatchCondition Teams.exe -DSCPAction 46"),
             ("apply", "Restart-NetAdapter -Name 'Wi-Fi'; ipconfig /flushdns"),
             ("verify", "Test-NetConnection -ComputerName gateway -InformationLevel Detailed  # latency < 90 ms")),
            "KB-NET-001", 0.01),
    Runbook("RB-AUTH-01", "Login/Auth", "Push compliance policy and re-sync device enrollment", "low", ("noncompliant",),
            (("snapshot", "dsregcmd /status > C:\\ProgramData\\DEX\\{run}\\enroll.txt"),
             ("apply", "gpupdate /force"),
             ("apply", "Get-ScheduledTask -TaskName 'PushLaunch' | Start-ScheduledTask  # Intune MDM sync"),
             ("verify", "Get-CimInstance -Namespace root/cimv2/mdm/dmmap -ClassName MDM_DevDetail_Ext01  # compliant")),
            "KB-AUTH-001", 0.01),
    Runbook("RB-APP-01", "Application Crash", "Reinstall and patch the crashing application suite", "high", ("hangs",),
            (("snapshot", "Checkpoint-Computer -Description 'DEX {run}' -RestorePointType APPLICATION_INSTALL"),
             ("apply", "winget upgrade --all --silent --accept-package-agreements"),
             ("apply", "Start-Process msiexec -ArgumentList '/fa {AppSuiteProductCode} /qn' -Wait  # repair"),
             ("verify", "Get-WinEvent -LogName Application -MaxEvents 200 | ? Id -eq 1002  # no new hangs")),
            "KB-APP-001", 0.04),
    Runbook("RB-PERF-01", "Performance", "Reimage device (fresh OS install and SSD optimization)", "high", ("boot",),
            (("snapshot", "Start-OSDBackup -UserState -Destination \\\\backup\\{device}  # user data"),
             ("apply", "Invoke-AutopilotReset -Device {device}  # fresh OS, apps and policies re-applied"),
             ("apply", "Optimize-Volume -DriveLetter C -ReTrim"),
             ("verify", "Get-WinEvent Microsoft-Windows-Diagnostics-Performance/Operational | ? Id -eq 100  # boot < 55 s")),
            "KB-PERF-001", 0.04),
    Runbook("RB-HW-01", "Hardware", "Hardware swap: replace battery and disk", "high", ("hw_health", "battery", "disk"),
            (("snapshot", "Start-OSDBackup -UserState -Destination \\\\backup\\{device}"),
             ("apply", "New-FieldServiceOrder -Device {device} -Parts Battery,SSD -Priority High"),
             ("apply", "Send-LoanerDevice -User (Get-DeviceOwner {device})"),
             ("verify", "Get-CimInstance Win32_Battery; Get-PhysicalDisk | Select HealthStatus")),
            "KB-HW-001", 0.03),
)
BY_ID = {r.runbook_id: r for r in RUNBOOKS}
BY_CATEGORY = {r.category: r for r in RUNBOOKS}


def get_runbook(runbook_id: str | None = None, category: str | None = None) -> Runbook:
    rb = BY_ID.get(runbook_id or "") or BY_CATEGORY.get(category or "")
    if rb is None:
        raise RemediationError(f"no runbook for {runbook_id or category!r}")
    return rb


def catalog() -> list[dict]:
    return [{**asdict(r), "steps": [{"step": s, "command": c} for s, c in r.steps],
             "approval": "auto-approved (low risk)" if r.risk == "low" else "named human approver required"}
            for r in RUNBOOKS]


def _applied(runbook_id: str) -> set[str]:
    t = db.runbook_applications
    with db.get_engine().connect() as conn:
        return {r[0] for r in conn.execute(select(t.c.device_id).where(t.c.runbook_id == runbook_id)).all()}


def mark_fix_applied(items: list[dict], key: str = "category") -> list[dict]:
    """Copy of watchlist-style rows with fix_applied: the category's runbook already ran on that device (the model
    only sees it once post-fix telemetry arrives, so the UI says so instead of offering the same fix again)."""
    done = {cat: _applied(rb.runbook_id) for cat, rb in BY_CATEGORY.items()}
    return [{**i, "fix_applied": i["device_id"] in done.get(i.get(key) or "", set())} for i in items]


def targets(runbook_id: str | None = None, category: str | None = None, signal: str | None = None,
            device_ids: list[str] | None = None, department: str | None = None, limit: int = 100) -> dict:
    """Devices whose telemetry breaches the runbook's signal(s) in the data window, most recent first."""
    rb = get_runbook(runbook_id, category)
    signals = (signal,) if signal in rb.signals else rb.signals
    store = get_store()
    dw = store.device_weeks
    if department:
        dw = dw[dw["department"] == department]
    known, unknown = normalize_device_ids(store, device_ids)
    if device_ids:
        dw = dw[dw["device_id"].isin(known)]
    mask = pd.Series(False, index=dw.index)
    for s in signals:
        mask |= _breach(dw, s).fillna(False).astype(bool)
    hit = dw[mask]
    done = _applied(rb.runbook_id)
    rows = []
    for dev, g in hit.groupby("device_id"):
        last = g.sort_values("week").iloc[-1]
        ev = []
        for s in signals:
            col, label, unit, _ = TELEMETRY_SIGNALS[s]
            v = last.get(col)
            if s == "noncompliant":
                ev.append(f"{label}: non-compliant in {int(_breach(g, s).sum())} week(s)")
            elif v is not None and pd.notna(v):
                ev.append(f"{label} {float(v):.1f}{unit} (W{int(last['week'])})")
        rows.append({"device_id": dev, "employee_name": last.get("employee_name"), "department": last.get("department"),
                     "breached_weeks": int(len(g)), "last_breach_week": int(last["week"]), "evidence": "; ".join(ev),
                     "already_fixed": dev in done})
    for dev in (d for d in known if d not in set(hit["device_id"])):  # explicitly chosen, e.g. from Diagnosis Assist
        info = store.device(dev) or {}
        rows.append({"device_id": dev, "employee_name": info.get("employee_name"), "department": info.get("department"),
                     "breached_weeks": 0, "last_breach_week": 0, "already_fixed": dev in done,
                     "evidence": "selected by analyst (no telemetry breach on this runbook's signals)"})
    rows.sort(key=lambda r: (r["already_fixed"], -r["last_breach_week"], -r["breached_weeks"]))
    pending = [r for r in rows if not r["already_fixed"]]
    return {"runbook": catalog()[RUNBOOKS.index(rb)], "signals": list(signals), "devices_affected": len(rows),
            "pending": len(pending), "already_fixed": len(rows) - len(pending), "unknown_device_ids": unknown,
            "devices": rows[:limit], "truncated": len(rows) > limit}


def _fails(device_id: str, rb: Runbook) -> bool:
    h = int(hashlib.sha256(f"{device_id}|{rb.runbook_id}".encode()).hexdigest()[:8], 16)
    return h / 0xFFFFFFFF < rb.fail_rate


def _projection(rb: Runbook, device_ids: list[str]) -> dict:
    """Projected effect from past fixes of the same category (observed before/after) on these devices' ticket rates."""
    store, cfg = get_store(), effective_config()
    oc = outcomes.outcome_report(store, cfg)
    eff = next((c for c in oc.get("by_category") or [] if c["category"] == rb.category), {})
    reduction = outcomes.ticket_reduction_pct(eff) / 100
    dw = store.device_weeks[store.device_weeks["device_id"].isin(device_ids)]
    weekly = float(dw.groupby("device_id")["ticket_count"].mean().sum()) if len(dw) else 0.0
    cost = outcomes.cost_per_ticket(store, cfg)
    avoided = weekly * 52 * reduction
    return {"based_on_cases": eff.get("cases", 0), "ticket_reduction_pct": round(100 * reduction, 1),
            "frustration_reduction_pct": (eff.get("frustration") or {}).get("change_pct"),
            "repeat_contact_reduction_pct": (eff.get("repeat_rate") or {}).get("change_pct"),
            "tickets_avoided_per_year": round(avoided), "savings_per_year_usd": round(avoided * cost),
            "dex_before": eff.get("dex_before"), "dex_after": eff.get("dex_after")}


def run(runbook_id: str | None = None, category: str | None = None, signal: str | None = None,
        device_ids: list[str] | None = None, department: str | None = None, dry_run: bool = True,
        approved_by: str | None = None, token_id: str | None = None, max_devices: int = 50,
        plan_hash_: str | None = None) -> dict:
    """High-risk runbooks execute only with a named human approver, a single-use token and the plan_hash of the
    reviewed dry run. Low-risk runbooks run under the auto-approval policy with their own audited token."""
    rb = get_runbook(runbook_id, category)
    if not dry_run and rb.risk == "high":
        approved_by = check_approver(approved_by, f"{rb.title} (high-risk)")
        _check_token(token_id)
    tg = targets(rb.runbook_id, signal=signal, device_ids=device_ids, department=department, limit=10_000)
    todo = [d for d in tg["devices"] if not d["already_fixed"]][:min(max_devices, MAX_BATCH)]
    fingerprint = plan_hash("runbook", rb.runbook_id, sorted(d["device_id"] for d in todo))
    if not dry_run:
        if rb.risk == "high":
            check_plan(fingerprint, plan_hash_)
            tok = _check_token(token_id, consume=True)
        else:  # low risk: auto-approval policy still runs under a scoped, audited, single-use token
            tok = _check_token(token_id or issue_token()["token_id"], consume=True)
            approved_by = approved_by or "auto-approval policy (low-risk runbook)"
    run_id = _new_run_id()
    results = []
    for d in todo:
        dev = d["device_id"]
        steps = [{"step": s, "command": c.replace("{run}", run_id).replace("{device}", dev)} for s, c in rb.steps]
        entry = {"device_id": dev, "employee_name": d["employee_name"], "evidence": d["evidence"], "steps": steps}
        if dry_run:
            results.append({**entry, "status": "planned"})
            continue
        if _fails(dev, rb):
            failed_at = next(i for i, s in enumerate(steps) if s["step"] == "apply")
            for i, st in enumerate(steps):
                st["result"] = "ok" if i < failed_at else ("failed: exit code 1603" if i == failed_at else "rolled_back")
            results.append({**entry, "status": "rolled_back", "escalate": True,
                            "error": "apply step failed; device restored from the pre-change snapshot"})
            audit.record("runbook_rolled_back", {"device_id": dev, "runbook_id": rb.runbook_id}, run_id, tok.service_account)
            continue
        for st in steps:
            st["result"] = "ok"
        with db.get_engine().begin() as conn:
            conn.execute(insert(db.runbook_applications).values(device_id=dev, runbook_id=rb.runbook_id,
                                                                run_id=run_id, applied_at=db.now()))
        results.append({**entry, "status": "fixed", "verified": True})
        audit.record("runbook_applied", {"device_id": dev, "runbook_id": rb.runbook_id}, run_id, tok.service_account)

    fixed = [r["device_id"] for r in results if r["status"] == "fixed"]
    counts = {k: sum(1 for r in results if r["status"] == k) for k in ("planned", "fixed", "rolled_back")}
    if dry_run:
        status = "planned"
    elif not results:
        status = "nothing_to_fix"
    else:
        status = "completed" if counts["fixed"] == len(results) else ("partial" if counts["fixed"] else "failed")
    result = {"run_id": run_id, "kind": "runbook", "status": status, "dry_run": dry_run, "plan_hash": fingerprint,
              "runbook_id": rb.runbook_id,
              "title": rb.title, "category": rb.category, "risk": rb.risk, "approved_by": approved_by,
              "devices_targeted": len(todo), "devices_pending_total": tg["pending"], **counts,
              "projected": _projection(rb, fixed if not dry_run else [d["device_id"] for d in todo]),
              "devices": results, "executor": "simulated fleet (commands shown are what an endpoint agent would run)"}
    with db.get_engine().begin() as conn:
        conn.execute(insert(RUNS).values(run_id=run_id, created_at=db.now(), message_id=None, software_name=rb.title,
                                         software_version=rb.runbook_id, dry_run=int(dry_run), status=status,
                                         approved_by=approved_by, result_json=json.dumps(result, default=str)))
    audit.record("runbook_planned" if dry_run else "runbook_executed",
                 {"runbook_id": rb.runbook_id, "status": status, "devices_targeted": len(todo), **counts},
                 run_id, approved_by if not dry_run else "agent")
    return result
