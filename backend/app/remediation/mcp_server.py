"""DEX Sentinel software-remediation MCP server (stdio).

Run from the backend directory:  python -m app.remediation.mcp_server

Tools follow the email-driven workflow: email_monitor -> email_parser ->
software_inventory -> version_matcher -> safety_validator -> credential_manager
-> removal_orchestrator -> verify_removal -> outcome_reporter, plus audit_trail.
Removal runs against the simulated fleet inventory only.
"""
from __future__ import annotations

import logging
import sys
from typing import Annotated, Any, Literal

from pydantic import Field

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from ..config import get_settings
from ..data.store import get_store
from . import audit, engine, mailbox, runbooks
from .engine import RemediationError

# stdout carries the MCP protocol, so all logging goes to stderr
logging.basicConfig(stream=sys.stderr, level=get_settings().log_level,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

INSTRUCTIONS = """\
DEX Sentinel software remediation. Removes a SPECIFIC software version, named in an email from an authorized
security sender, from devices in the DEX Sentinel fleet.

Workflow for each pending email:
1. email_monitor(action="list") to find pending requests; email_parser(message_id) to read one.
   Rejected senders or requests with errors are never actioned; report them instead.
2. software_inventory and version_matcher to see which devices carry the exact version (other versions stay).
3. safety_validator. Blocked devices are skipped; surface dependencies and system-critical findings.
4. removal_orchestrator with dry_run=true to produce the plan, and show it to the human.
5. Only after a named human approves: credential_manager, then removal_orchestrator with dry_run=false,
   approved_by=<that person>, token_id=<token>, plan_hash=<from the dry run they reviewed>. Tokens are single-use,
   and the approver must be a named human (never yourself, "agent" or the service account).
6. verify_removal, then outcome_reporter(run_id). Escalate any rolled-back device to a human.
Never invent an approver, and stop at the first failed step.
"""

server = MCPServer(name="dex-sentinel-remediation", title="DEX Sentinel Software Remediation",
                   instructions=INSTRUCTIONS, version="1.0.0")

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
DeviceIds = Annotated[list[str] | None, Field(description="Device IDs such as DEV-00042; omit for the whole fleet")]


def _ready() -> None:
    store = get_store()
    if get_settings().remediation_seed_inbox:
        mailbox.seed_demo_inbox(store)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except RemediationError as e:
        raise ToolError(str(e)) from e


def _summary(m: dict) -> dict[str, Any]:
    return {k: m[k] for k in ("message_id", "received_at", "sender", "subject", "source", "status", "note")}


@server.tool(annotations=ToolAnnotations(title="Email monitor", destructive_hint=False, open_world_hint=True))
def email_monitor(action: Annotated[Literal["poll", "list", "mark_processed"],
                                    Field(description="poll = fetch from IMAP (if configured) then list pending; "
                                                      "list = list inbox; mark_processed = close a request")] = "list",
                  status: Annotated[Literal["pending", "processed", "rejected"] | None,
                                    Field(description="Filter for list/poll")] = "pending",
                  message_id: Annotated[str | None, Field(description="Required for mark_processed")] = None,
                  note: str | None = None) -> dict[str, Any]:
    """Watch the removal-request inbox for security-team emails ([UNAUTHORIZED-SOFTWARE], [EOL-SOFTWARE],
    [SECURITY-PATCH]). Mail from senders outside the allowlist is kept as 'rejected' and never actioned."""
    _ready()
    if action == "mark_processed":
        if not message_id:
            raise ToolError("message_id is required for mark_processed")
        if not mailbox.mark(message_id, "processed", note):
            raise ToolError(f"no email with message_id {message_id}")
        audit.record("email_marked_processed", {"message_id": message_id, "note": note})
        return {"message_id": message_id, "status": "processed"}
    polled = None
    if action == "poll":
        try:
            polled = mailbox.poll_imap()
        except (OSError, mailbox.imaplib.IMAP4.error) as e:
            raise ToolError(f"IMAP poll failed: {e}") from e
    emails = mailbox.list_emails(status)
    return {"imap": polled if polled is not None else {"configured": mailbox.imap_configured()},
            "authorized_senders": get_settings().remediation_allowed_senders,
            "count": len(emails), "emails": [_summary(m) for m in emails]}


@server.tool(annotations=ToolAnnotations(title="Submit email", destructive_hint=False, idempotent_hint=False,
                                         open_world_hint=False))
def submit_email(sender: str, subject: str, body: str,
                 attachments: Annotated[list[dict] | None, Field(
                     description="Optional [{filename, content}] with CSV (device_id column) or JSON content")] = None
                 ) -> dict[str, Any]:
    """Add an email to the removal-request inbox (for testing or forwarding a message by hand)."""
    _ready()
    m = mailbox.add_email(sender, subject, body, attachments, source="submitted")
    audit.record("email_received", {"message_id": m["message_id"], "sender": sender, "status": m["status"]})
    return _summary(m)


@server.tool(annotations=READ)
def email_parser(message_id: str) -> dict[str, Any]:
    """Parse one inbox email into a removal request: software, exact version, target devices (or fleet scope),
    reason, replacement and urgency, plus validation errors that make it non-actionable."""
    _ready()
    req = _call(engine.request_from_email, message_id)
    return req.as_dict()


@server.tool(annotations=READ)
def software_inventory(software_name: str, version: str | None = None, device_ids: DeviceIds = None,
                       limit: Annotated[int, Field(ge=1, le=200)] = 25) -> dict[str, Any]:
    """Scan device inventory (registry HKLM/WOW6432Node/HKCU, Program Files, AppData, WMI/MSI, processes)
    for a software name, optionally filtered to one version."""
    return _call(engine.software_inventory, software_name, version, device_ids, limit)


@server.tool(annotations=READ)
def version_matcher(software_name: str, target_version: str, device_ids: DeviceIds = None) -> dict[str, Any]:
    """Find installations of exactly target_version (6.0.36 never matches 6.0.37). Reports other versions,
    which are left untouched, and listed devices that don't carry the target version."""
    return _call(engine.match_versions, software_name, target_version, device_ids)


@server.tool(annotations=READ)
def safety_validator(software_name: str, version: str, device_ids: DeviceIds = None,
                     acknowledge_dependencies: bool = False) -> dict[str, Any]:
    """Check each device before removal: system-critical packages and dependent applications block it,
    running processes are warnings (they are stopped first)."""
    return _call(engine.validate_safety, software_name, version, device_ids, acknowledge_dependencies)


@server.tool(annotations=ToolAnnotations(title="Credential manager", destructive_hint=False, open_world_hint=False))
def credential_manager(permissions: Annotated[list[str] | None, Field(
        description=f"Subset of {engine.REMOVAL_PERMISSIONS}; defaults to all removal permissions")] = None) -> dict[str, Any]:
    """Issue a short-lived execution token for the removal service account. No password is ever returned."""
    return _call(engine.issue_token, permissions)


@server.tool(annotations=ToolAnnotations(title="Removal orchestrator", destructive_hint=True, idempotent_hint=False,
                                         open_world_hint=False))
def removal_orchestrator(message_id: Annotated[str | None, Field(description="Take software, version and devices "
                                                                             "from this parsed email")] = None,
                         software_name: str | None = None, version: str | None = None, device_ids: DeviceIds = None,
                         dry_run: Annotated[bool, Field(description="true = plan only (default); false = execute")] = True,
                         approved_by: Annotated[str | None, Field(description="Name of the human who approved "
                                                                              "execution; required when dry_run=false")] = None,
                         token_id: Annotated[str | None, Field(description="From credential_manager; required when "
                                                                           "dry_run=false")] = None,
                         acknowledge_dependencies: bool = False,
                         plan_hash: Annotated[str | None, Field(description="plan_hash returned by the dry run the "
                                                                            "human reviewed; required when dry_run=false")] = None) -> dict[str, Any]:
    """Plan or execute a version-specific removal. Per device: restore point, stop processes, MSI/EXE uninstall,
    delete files, registry cleanup, verify. A device where any step fails is rolled back as a whole."""
    _ready()
    return _call(engine.remove, software_name, version, device_ids, message_id, dry_run, approved_by, token_id,
                 acknowledge_dependencies, plan_hash)


@server.tool(annotations=READ)
def verify_removal(software_name: str, version: str, device_ids: list[str]) -> dict[str, Any]:
    """Re-scan devices and confirm no installation of the version remains."""
    return _call(engine.verify, software_name, version, device_ids)


@server.tool(annotations=ToolAnnotations(title="Outcome reporter", destructive_hint=False, open_world_hint=False))
def outcome_reporter(run_id: str) -> dict[str, Any]:
    """Report an executed run: before/projected-after telemetry, recent tickets, user notifications,
    security-team summary and escalations. Closes the originating email."""
    return _call(engine.report_outcome, run_id)


@server.tool(annotations=READ)
def runbook_catalog() -> dict[str, Any]:
    """List the fix-it runbooks (one per root-cause category) with their steps and risk: low-risk runbooks are
    auto-approved, high-risk ones need a named human approver."""
    return {"items": runbooks.catalog()}


@server.tool(annotations=READ)
def runbook_targets(runbook_id: str | None = None,
                    category: Annotated[str | None, Field(description="Performance, Network, Login/Auth, Hardware "
                                                                      "or Application Crash")] = None,
                    device_ids: DeviceIds = None, department: str | None = None,
                    limit: Annotated[int, Field(ge=1, le=500)] = 50) -> dict[str, Any]:
    """Devices whose telemetry breaches the runbook's signal, most recent first, with already-fixed devices flagged."""
    return _call(runbooks.targets, runbook_id, category, None, device_ids, department, limit)


@server.tool(annotations=ToolAnnotations(title="Run runbook", destructive_hint=True, idempotent_hint=False,
                                         open_world_hint=False))
def run_runbook(runbook_id: str | None = None, category: str | None = None, device_ids: DeviceIds = None,
                department: str | None = None, dry_run: bool = True, approved_by: str | None = None,
                token_id: str | None = None, max_devices: Annotated[int, Field(ge=1, le=500)] = 50,
                plan_hash: str | None = None) -> dict[str, Any]:
    """Plan (dry_run, default) or execute a runbook on its target devices. High-risk runbooks need approved_by and
    a credential_manager token; low-risk ones are auto-approved. Failed devices are rolled back and escalated."""
    return _call(runbooks.run, runbook_id, category, None, device_ids, department, dry_run, approved_by, token_id,
                 max_devices, plan_hash)


@server.tool(annotations=READ)
def audit_trail(run_id: str | None = None, event: str | None = None, device_id: str | None = None,
                limit: Annotated[int, Field(ge=1, le=500)] = 50) -> dict[str, Any]:
    """Read the hash-chained audit log and check that it has not been altered."""
    return {"integrity": audit.verify_chain(), "entries": audit.trail(run_id, event, device_id, limit)}


def main() -> None:
    _ready()
    server.run("stdio")


if __name__ == "__main__":
    main()
