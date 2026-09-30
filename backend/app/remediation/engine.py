"""Software remediation workflow: parse -> inventory -> match -> safety -> credentials -> remove -> verify -> report.

Removal is version-specific and atomic per device: every step for a device must
succeed, otherwise that device is rolled back to its restore point and nothing
about it changes. Execution always targets the simulated fleet inventory; the
commands a real endpoint agent would run are returned for review, never run here.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
from dataclasses import dataclass
from datetime import timedelta

import pandas as pd
from sqlalchemy import insert, select

from .. import db
from ..config import get_settings
from ..data.store import DataStore, get_store
from . import audit, mailbox
from .inventory import CATALOG_BY_KEY, Installation, device_inventory, name_matches, removed_ids, \
    version_matches, version_prefix
from .parser import RemovalRequest, parse_email

REMOVAL_PERMISSIONS = ["process_stop", "msi_uninstall", "file_delete", "registry_delete", "restore_point"]
# Projected share of boot time freed by removing each package (autostart services, update agents).
BOOT_FOOTPRINT = {"dotnet": 0.06, "java": 0.05, "teamviewer": 0.08, "anydesk": 0.05, "utorrent": 0.07,
                  "winrar": 0.01, "python": 0.01, "chrome": 0.03, "expense": 0.02, "vcredist": 0.0}
HANG_FOOTPRINT = {"dotnet": 0.10, "java": 0.12, "expense": 0.05, "utorrent": 0.05}
RUNS = db.remediation_runs


class RemediationError(ValueError):
    """A request the workflow refuses to act on (bad input, missing approval, invalid token)."""


# ------------------------------------------------------------------ targeting
def normalize_device_ids(store: DataStore, ids: list[str] | None) -> tuple[list[str], list[str]]:
    """Map 'DEV-0042' to the fleet's 'DEV-00042' form; return (known, unknown)."""
    if not ids:
        return [], []
    width = len(store.device_ids()[0].split("-")[-1]) if store.device_ids() else 5
    known, unknown = [], []
    for raw in ids:
        m = re.fullmatch(r"DEV-(\d+)", raw.strip().upper())
        d = f"DEV-{int(m.group(1)):0{width}d}" if m else raw.strip()
        (known if store.device(d) is not None else unknown).append(d)
    return list(dict.fromkeys(known)), unknown


def _installations(software_name: str, device_ids: list[str] | None, version: str | None = None,
                   store: DataStore | None = None) -> list[Installation]:
    store = store or get_store()
    devices = device_ids if device_ids else store.device_ids()
    gone = removed_ids(devices if device_ids else None)
    out = []
    for d in devices:
        for inst in device_inventory(d, removed=gone):
            if name_matches(inst.display_name, software_name) and (version is None or version_matches(inst.version, version)):
                out.append(inst)
    return out


def software_inventory(software_name: str, version: str | None = None, device_ids: list[str] | None = None,
                       limit: int = 25) -> dict:
    store = get_store()
    known, unknown = normalize_device_ids(store, device_ids)
    if device_ids and not known:
        return {"error": "none of the device IDs exist in the fleet", "unknown_device_ids": unknown}
    found = _installations(software_name, known or None, version, store)
    by_version: dict[str, set] = {}
    for i in found:
        by_version.setdefault(i.version, set()).add(i.device_id)
    return {
        "software_name": software_name, "version_filter": version, "scan_methods": ["registry", "filesystem", "wmi", "processes"],
        "devices_scanned": len(known) if known else len(store.device_ids()), "unknown_device_ids": unknown,
        "installations_found": len(found), "devices_with_software": len({i.device_id for i in found}),
        "versions": {v: len(ds) for v, ds in sorted(by_version.items())},
        "installations": [i.as_dict() for i in found[:limit]], "truncated": len(found) > limit,
        "source": "simulated fleet inventory",
    }


def match_versions(software_name: str, target_version: str, device_ids: list[str] | None = None) -> dict:
    store = get_store()
    known, unknown = normalize_device_ids(store, device_ids)
    if device_ids and not known:
        return {"error": "none of the device IDs exist in the fleet", "unknown_device_ids": unknown}
    every = _installations(software_name, known or None, None, store)
    hits = [i for i in every if version_matches(i.version, target_version)]
    others = [i for i in every if not version_matches(i.version, target_version)]
    hit_devices = {i.device_id for i in hits}
    return {
        "software_name": software_name, "target_version": target_version,
        "matching_installations": len(hits), "matching_devices": len(hit_devices),
        "matches": [{k: i.as_dict()[k] for k in ("installation_id", "device_id", "display_name", "version",
                                                  "architecture", "install_location", "registry_key")} for i in hits],
        "other_versions_left_untouched": {v: sum(1 for i in others if i.version == v) for v in sorted({i.version for i in others})},
        "listed_devices_without_target_version": [d for d in known if d not in hit_devices],
        "unknown_device_ids": unknown,
    }


# ------------------------------------------------------------------ safety
def _dependents(inst: Installation, inventory: list[Installation]) -> list[dict]:
    deps = []
    for other in inventory:
        item = CATALOG_BY_KEY[other.catalog_key]
        for own_prefix, key, req_prefix in item.requires:
            if key == inst.catalog_key and version_prefix(other.version, own_prefix) and version_prefix(inst.version, req_prefix):
                still_ok = any(o.catalog_key == key and o.installation_id != inst.installation_id
                               and version_prefix(o.version, req_prefix) and not version_matches(o.version, inst.version)
                               for o in inventory)
                if not still_ok:
                    deps.append({"dependent_software": other.display_name, "dependent_version": other.version,
                                 "requires": f"{CATALOG_BY_KEY[key].name} {req_prefix}.x",
                                 "recommendation": f"Upgrade {item.name} to a release that supports the replacement first"})
    return deps


def validate_safety(software_name: str, version: str, device_ids: list[str] | None = None,
                    acknowledge_dependencies: bool = False) -> dict:
    store = get_store()
    known, unknown = normalize_device_ids(store, device_ids)
    hits = _installations(software_name, known or None, version, store)
    per_device: dict[str, list[Installation]] = {}
    for i in hits:
        per_device.setdefault(i.device_id, []).append(i)
    devices = []
    for d, insts in per_device.items():
        inventory = device_inventory(d)
        blockers, warnings, deps = [], [], []
        for i in insts:
            if i.system_critical:
                blockers.append(f"{i.display_name} is system-critical; removal needs a change request, not automation")
            deps += [x for x in _dependents(i, inventory) if x not in deps]  # x64 + x86 copies share dependents
            for p in i.running_processes:
                warnings.append(f"{p['name']} (PID {p['pid']}) is running and will be stopped before uninstall")
        if deps and not acknowledge_dependencies:
            blockers.append(f"{len(deps)} installed application(s) depend on this version")
        elif deps:
            warnings.append(f"{len(deps)} dependent application(s) acknowledged; they may stop working")
        devices.append({"device_id": d, "status": "blocked" if blockers else ("warning" if warnings else "safe"),
                        "installations": len(insts), "blockers": blockers, "warnings": warnings,
                        "dependencies": deps, "system_critical": any(i.system_critical for i in insts),
                        "rollback_available": True})
    counts = {s: sum(1 for x in devices if x["status"] == s) for s in ("safe", "warning", "blocked")}
    return {"software_name": software_name, "version": version, "devices_checked": len(devices), **counts,
            "safe_to_proceed": bool(devices) and counts["blocked"] < len(devices),
            "devices": devices, "listed_devices_without_target_version": [d for d in known if d not in per_device],
            "unknown_device_ids": unknown}


# ------------------------------------------------------------------ credentials
@dataclass
class _Token:
    token_id: str
    service_account: str
    permissions: list[str]
    expires_at: object


_tokens: dict[str, _Token] = {}
_tokens_lock = threading.Lock()


def issue_token(permissions: list[str] | None = None, service_account: str | None = None) -> dict:
    """Short-lived, scoped execution token for the removal service account. The secret itself never leaves the vault."""
    s = get_settings()
    account = service_account or s.remediation_service_account
    if account != s.remediation_service_account:
        raise RemediationError(f"unknown service account {account!r}")
    perms = permissions or REMOVAL_PERMISSIONS
    bad = [p for p in perms if p not in REMOVAL_PERMISSIONS]
    if bad:
        raise RemediationError(f"permissions not grantable to {account}: {bad}")
    tok = _Token(f"tok_{secrets.token_urlsafe(18)}", account, list(perms), db.now() + timedelta(seconds=s.remediation_token_ttl_sec))
    with _tokens_lock:
        _tokens[tok.token_id] = tok
    audit.record("credential_issued", {"service_account": account, "permissions": perms,
                                       "expires_at": tok.expires_at.isoformat(), "token_hint": tok.token_id[:8]})
    return {"token_id": tok.token_id, "service_account": account, "permissions": perms,
            "expires_at": tok.expires_at.isoformat(), "ttl_seconds": s.remediation_token_ttl_sec,
            "vault": "simulated (no password is ever returned)"}


def _check_token(token_id: str | None, consume: bool = False) -> _Token:
    """consume=True spends the token: one token authorises exactly one execution."""
    with _tokens_lock:
        tok = _tokens.pop(token_id or "", None) if consume else _tokens.get(token_id or "")
    if tok is None:
        raise RemediationError("invalid or already-used execution token; call credential_manager for a new one")
    if tok.expires_at <= db.now():
        raise RemediationError("execution token expired; request a new one")
    missing = [p for p in REMOVAL_PERMISSIONS if p not in tok.permissions]
    if missing:
        raise RemediationError(f"token lacks permissions {missing}")
    return tok


# ------------------------------------------------------------------ approval
# Identities that can never approve an execution: approval must come from a named human, not the agent itself.
NON_HUMAN_APPROVERS = {"agent", "ai", "assistant", "bot", "claude", "copilot", "dex copilot", "llm", "mcp", "system",
                       "auto", "automation", "admin", "root"}


def check_approver(approved_by: str | None, what: str = "this removal") -> str:
    name = (approved_by or "").strip()
    if not name:
        raise RemediationError(f"execution needs approved_by: the name of the human who approved {what}")
    low = name.lower()
    if low in NON_HUMAN_APPROVERS or low == get_settings().remediation_service_account.lower() or "auto-approval" in low:
        raise RemediationError(f"approved_by must name a human approver, not an agent or service identity ({name!r})")
    return name


def plan_hash(*parts) -> str:
    """Fingerprint of exactly what a dry run would change; execution must present the same one."""
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def check_plan(expected: str, given: str | None) -> None:
    if not given:
        raise RemediationError("execution must match a reviewed plan: run with dry_run=true first and pass its plan_hash")
    if given != expected:
        raise RemediationError("the plan changed since it was reviewed (plan_hash mismatch): create and review a new dry run")


# ------------------------------------------------------------------ removal
def _plan_steps(run_id: str, software: str, version: str, insts: list[Installation]) -> list[dict]:
    steps = [{"step": "restore_point",
              "command": f"Checkpoint-Computer -Description 'DEX Sentinel {run_id}: before removing {software} {version}' "
                         "-RestorePointType APPLICATION_UNINSTALL"}]
    for i in insts:
        for p in i.running_processes:
            steps.append({"step": "stop_process", "installation_id": i.installation_id,
                          "command": f"Stop-Process -Id {p['pid']} -Force  # {p['name']}"})
    for i in insts:
        if i.uninstall_method == "msi":
            cmd = f"msiexec.exe /x {i.product_code} /qn /norestart /l*v C:\\Windows\\Temp\\{run_id}.log"
        else:
            cmd = f"{i.uninstall_string} /S"
        steps.append({"step": "uninstall", "installation_id": i.installation_id, "method": i.uninstall_method, "command": cmd})
        for path in [i.install_location, *i.residual_paths]:
            steps.append({"step": "delete_files", "installation_id": i.installation_id,
                          "command": f"Remove-Item -LiteralPath '{path}' -Recurse -Force -ErrorAction SilentlyContinue"})
        steps.append({"step": "registry_cleanup", "installation_id": i.installation_id,
                      "command": f"reg delete \"{i.registry_key}\" /f"})
    steps.append({"step": "verify", "command": f"rescan registry, file system, WMI and processes for {software} {version}"})
    return steps


def _new_run_id() -> str:
    return f"SWR-{db.now():%Y%m%d}-{secrets.token_hex(3).upper()}"


def request_from_email(message_id: str) -> RemovalRequest:
    msg = mailbox.get_email(message_id)
    if msg is None:
        raise RemediationError(f"no email with message_id {message_id}")
    return parse_email(msg["message_id"], msg["sender"], msg["subject"], msg["body"], msg["attachments"],
                       get_settings().remediation_allowed_senders)


def remove(software_name: str | None = None, version: str | None = None, device_ids: list[str] | None = None,
           message_id: str | None = None, dry_run: bool = True, approved_by: str | None = None,
           token_id: str | None = None, acknowledge_dependencies: bool = False, plan_hash_: str | None = None) -> dict:
    """Plan (dry_run) or execute a version-specific removal. Execution needs a named human approver, a single-use
    token and the plan_hash of the dry run that approver reviewed."""
    req = None
    if message_id:
        req = request_from_email(message_id)
        if not req.valid:
            raise RemediationError("email request is not actionable: " + "; ".join(req.errors))
        software_name, version = software_name or req.software_name, version or req.software_version
        if device_ids is None and req.scope != "fleet":
            device_ids = req.device_ids
    if not software_name or not version:
        raise RemediationError("software_name and version are required (removal is version-specific)")
    if not dry_run:
        approved_by = check_approver(approved_by)
        tok = _check_token(token_id)

    store = get_store()
    known, unknown = normalize_device_ids(store, device_ids)
    if device_ids and not known:
        raise RemediationError(f"none of the device IDs exist in the fleet: {unknown}")
    safety = validate_safety(software_name, version, known or None, acknowledge_dependencies)
    hits = _installations(software_name, known or None, version, store)
    by_device: dict[str, list[Installation]] = {}
    for i in hits:
        by_device.setdefault(i.device_id, []).append(i)
    status_of = {d["device_id"]: d for d in safety["devices"]}
    fingerprint = plan_hash("removal", software_name.lower(), version,
                            sorted(i.installation_id for i in hits if status_of[i.device_id]["status"] != "blocked"))
    if not dry_run:
        check_plan(fingerprint, plan_hash_)
        tok = _check_token(token_id, consume=True)
    run_id = _new_run_id()

    results = []
    for d, insts in by_device.items():
        s = status_of[d]
        steps = _plan_steps(run_id, software_name, version, insts)
        entry = {"device_id": d, "installations": [i.installation_id for i in insts], "safety": s["status"],
                 "warnings": s["warnings"], "steps": steps}
        if s["status"] == "blocked":
            results.append({**entry, "status": "skipped_blocked", "blockers": s["blockers"]})
            continue
        if dry_run:
            results.append({**entry, "status": "planned"})
            continue
        failed = next((i for i in insts if i.uninstaller_locked), None)
        if failed:  # atomic: roll the whole device back, record nothing as removed
            for st in steps:
                st["result"] = "rolled_back" if st["step"] != "restore_point" else "ok"
                if st.get("installation_id") == failed.installation_id and st["step"] == "uninstall":
                    st["result"] = "failed: exit code 1603 (fatal error during installation)"
            results.append({**entry, "status": "rolled_back", "error": f"uninstall of {failed.display_name} failed "
                            "with exit code 1603; device restored to its restore point", "escalate": True})
            audit.record("device_rolled_back", {"device_id": d, "installation_id": failed.installation_id},
                         run_id, tok.service_account)
            continue
        with db.get_engine().begin() as conn:
            for i in insts:
                conn.execute(insert(db.removed_installations).values(installation_id=i.installation_id,
                                                                     removed_at=db.now(), run_id=run_id))
        remaining = [i for i in device_inventory(d) if name_matches(i.display_name, software_name)
                     and version_matches(i.version, version)]
        for st in steps:
            st["result"] = "ok"
        results.append({**entry, "status": "removed" if not remaining else "verification_failed",
                        "verified": not remaining})
        audit.record("device_remediated", {"device_id": d, "installations": entry["installations"],
                                           "verified": not remaining}, run_id, tok.service_account)

    counts = {k: sum(1 for r in results if r["status"] == k)
              for k in ("planned", "removed", "rolled_back", "skipped_blocked", "verification_failed")}
    if dry_run:
        status = "planned"
    elif not results:
        status = "nothing_to_remove"
    elif counts["removed"] == len(results):
        status = "completed"
    elif counts["removed"]:
        status = "partial"
    else:
        status = "failed"
    result = {"run_id": run_id, "status": status, "dry_run": dry_run, "plan_hash": fingerprint, "software_name": software_name,
              "version": version, "message_id": message_id, "approved_by": approved_by,
              "urgency": req.urgency if req else None, "removal_reason": req.removal_reason if req else None,
              "devices_targeted": len(by_device), **counts,
              "listed_devices_without_target_version": safety["listed_devices_without_target_version"],
              "unknown_device_ids": unknown, "devices": results,
              "executor": "simulated fleet (commands shown are what an endpoint agent would run)"}
    with db.get_engine().begin() as conn:
        conn.execute(insert(RUNS).values(run_id=run_id, created_at=db.now(), message_id=message_id,
                                         software_name=software_name, software_version=version, dry_run=int(dry_run),
                                         status=status, approved_by=approved_by, result_json=json.dumps(result, default=str)))
    audit.record("removal_planned" if dry_run else "removal_executed",
                 {k: result[k] for k in ("status", "software_name", "version", "message_id", "devices_targeted",
                                         "removed", "rolled_back", "skipped_blocked")},
                 run_id, approved_by if not dry_run else "agent")
    return result


def verify(software_name: str, version: str, device_ids: list[str]) -> dict:
    store = get_store()
    known, unknown = normalize_device_ids(store, device_ids)
    remaining = _installations(software_name, known, version, store)
    left = {d: [i.installation_id for i in remaining if i.device_id == d] for d in known}
    return {"software_name": software_name, "version": version, "unknown_device_ids": unknown,
            "devices": [{"device_id": d, "removed": not ids, "remaining_installations": ids} for d, ids in left.items()],
            "all_removed": all(not ids for ids in left.values())}


def get_run(run_id: str) -> dict | None:
    with db.get_engine().connect() as conn:
        r = conn.execute(select(RUNS).where(RUNS.c.run_id == run_id)).first()
    return json.loads(r.result_json) if r else None


def list_runs(limit: int = 20) -> list[dict]:
    with db.get_engine().connect() as conn:
        rows = conn.execute(select(RUNS).order_by(RUNS.c.created_at.desc()).limit(limit)).all()
    out = []
    for r in rows:
        res = json.loads(r.result_json)
        out.append({"run_id": r.run_id, "created_at": r.created_at.isoformat(), "message_id": r.message_id,
                    "software_name": r.software_name, "version": r.software_version, "dry_run": bool(r.dry_run),
                    "status": r.status, "approved_by": r.approved_by, "devices_targeted": res.get("devices_targeted"),
                    "kind": res.get("kind", "software_removal"),
                    "removed": res.get("removed", res.get("fixed")), "rolled_back": res.get("rolled_back"),
                    "skipped_blocked": res.get("skipped_blocked")})
    return out


# ------------------------------------------------------------------ outcome
def _num(v) -> float | None:
    return None if v is None or pd.isna(v) else round(float(v), 2)


def _notification(first_name: str, device_id: str, software: str, version: str, reason: str | None) -> str:
    why = f" Why: {reason.rstrip('.')}." if reason else ""
    return (f"Hi {first_name}, we removed {software} {version} from your laptop ({device_id}).{why} "
            "Your files and other apps were not touched, and you don't need to do anything. "
            "If something you rely on stops working, reply to this message or contact the service desk "
            "and we'll sort it out with you straight away.")


def report_outcome(run_id: str) -> dict:
    run = get_run(run_id)
    if run is None:
        raise RemediationError(f"unknown run_id {run_id}")
    if run["dry_run"]:
        raise RemediationError("this run was a dry run; execute it before reporting an outcome")
    store = get_store()
    last_week = max(store.weeks)
    removed = [d for d in run["devices"] if d["status"] == "removed"]
    rows = []
    for d in removed:
        dev = store.device(d["device_id"]) or {}
        t = store.telemetry_at(d["device_id"]) or {}
        keys = {iid.split(":")[1] for iid in d["installations"]}
        boot_cut = min(0.25, sum(BOOT_FOOTPRINT.get(k, 0.02) for k in keys))
        hang_cut = min(0.3, sum(HANG_FOOTPRINT.get(k, 0.0) for k in keys))
        tk = store.device_tickets(d["device_id"])
        recent = tk[tk["week"] > last_week - 4]
        boot, hangs = (_num(t.get(c)) for c in ("boot_duration_sec", "app_hang_count"))
        rows.append({
            "device_id": d["device_id"], "employee_name": dev.get("employee_name"), "department": dev.get("department"),
            "before": {"boot_duration_sec": boot, "app_hang_count": hangs,
                       "week": int(t["week"]) if t.get("week") is not None else None},
            "after_projected": {"boot_duration_sec": round(boot * (1 - boot_cut), 1) if boot is not None else None,
                                "app_hang_count": round(hangs * (1 - hang_cut), 2) if hangs is not None else None},
            "tickets_last_4_weeks": int(len(recent)),
            "avg_frustration_last_4_weeks": round(float(recent["frustration_score"].mean()), 1) if len(recent) else None,
            "user_notification": _notification((dev.get("employee_name") or "there").split()[0], d["device_id"],
                                                run["software_name"], run["version"], run.get("removal_reason")),
        })
    boots = [(r["before"]["boot_duration_sec"], r["after_projected"]["boot_duration_sec"]) for r in rows
             if r["before"]["boot_duration_sec"] is not None]
    summary = {
        "run_id": run_id, "status": run["status"], "software_name": run["software_name"], "version": run["version"],
        "approved_by": run["approved_by"], "devices_removed": len(removed), "devices_rolled_back": run["rolled_back"],
        "devices_skipped_blocked": run["skipped_blocked"],
        "avg_boot_before_sec": round(sum(b for b, _ in boots) / len(boots), 1) if boots else None,
        "avg_boot_after_projected_sec": round(sum(a for _, a in boots) / len(boots), 1) if boots else None,
        "escalations": [{"device_id": d["device_id"], "error": d.get("error")} for d in run["devices"] if d.get("escalate")],
        "note": "Before = latest weekly telemetry. After = projected from each package's startup footprint; "
                "measure the real effect with DEX Sentinel's outcome report once post-removal telemetry arrives.",
    }
    summary["security_team_summary"] = (
        f"{run_id}: {run['software_name']} {run['version']} removed from {len(removed)} device(s)"
        + (f", {run['rolled_back']} rolled back and escalated" if run["rolled_back"] else "")
        + (f", {run['skipped_blocked']} skipped by safety checks" if run["skipped_blocked"] else "")
        + f". Approved by {run['approved_by']}.")
    if run.get("message_id"):
        mailbox.mark(run["message_id"], "processed", f"{run_id}: {run['status']}")
    audit.record("outcome_reported", {k: summary[k] for k in ("devices_removed", "devices_rolled_back",
                                                               "devices_skipped_blocked", "avg_boot_before_sec",
                                                               "avg_boot_after_projected_sec")}, run_id, "agent")
    return {**summary, "devices": rows}
