"""Software remediation API: the web UI's view of the email-driven removal workflow (same engine as the MCP server)."""
from __future__ import annotations

import imaplib

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..config import get_settings
from ..data.store import get_store
from ..remediation import audit, engine, mailbox, runbooks
from ..remediation.engine import RemediationError
from .deps import CleanRoute

router = APIRouter(route_class=CleanRoute)


class EmailIn(BaseModel):
    sender: str = Field(..., min_length=3, max_length=255)
    subject: str = Field(..., min_length=1, max_length=998)
    body: str = Field(..., max_length=100_000)
    attachments: list[dict] = Field(default_factory=list, max_length=10)


class RunIn(BaseModel):
    message_id: str | None = Field(None, max_length=255)
    software_name: str | None = Field(None, max_length=255)
    version: str | None = Field(None, max_length=64)
    device_ids: list[str] | None = Field(None, max_length=5000)
    dry_run: bool = True
    approved_by: str | None = Field(None, max_length=255)
    token_id: str | None = Field(None, max_length=128)
    acknowledge_dependencies: bool = False
    plan_hash: str | None = Field(None, max_length=64, description="from the reviewed dry run; required to execute")


def _ready() -> None:
    if get_settings().remediation_seed_inbox:
        mailbox.seed_demo_inbox(get_store())


def _devices(devices: str | None) -> list[str] | None:
    ids = [d.strip() for d in (devices or "").split(",") if d.strip()]
    return ids or None


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except RemediationError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/remediation/emails", summary="Removal-request inbox")
def list_emails(status: str | None = Query(None, pattern="^(pending|processed|rejected)$"),
                limit: int = Query(50, ge=1, le=500)):
    _ready()
    return {"imap_configured": mailbox.imap_configured(),
            "authorized_senders": get_settings().remediation_allowed_senders,
            "items": mailbox.list_emails(status, limit)}


@router.post("/remediation/emails", status_code=201, summary="Add an email to the inbox")
def submit_email(body: EmailIn):
    _ready()
    m = mailbox.add_email(body.sender, body.subject, body.body, body.attachments, source="submitted")
    audit.record("email_received", {"message_id": m["message_id"], "sender": body.sender, "status": m["status"]})
    return m


@router.post("/remediation/emails/poll", summary="Fetch tagged messages from the configured IMAP mailbox")
def poll_mailbox():
    _ready()
    try:
        return mailbox.poll_imap()
    except (OSError, imaplib.IMAP4.error) as e:
        raise HTTPException(502, f"IMAP poll failed: {e}") from e


@router.get("/remediation/emails/{message_id:path}/request", summary="Parse one email into a removal request")
def parse_request(message_id: str):
    _ready()
    return _call(engine.request_from_email, message_id).as_dict()


@router.get("/remediation/match", summary="Installations of exactly this version")
def match(software_name: str, version: str, devices: str | None = Query(None, description="comma-separated device IDs")):
    return _call(engine.match_versions, software_name, version, _devices(devices))


@router.get("/remediation/safety", summary="Per-device safety checks before removal")
def safety(software_name: str, version: str, devices: str | None = None, acknowledge_dependencies: bool = False):
    return _call(engine.validate_safety, software_name, version, _devices(devices), acknowledge_dependencies)


@router.post("/remediation/token", summary="Short-lived execution token for the removal service account")
def token():
    return _call(engine.issue_token)


@router.post("/remediation/runs", summary="Plan (dry run) or execute a version-specific removal")
def run(body: RunIn):
    _ready()
    return _call(engine.remove, body.software_name, body.version, body.device_ids, body.message_id, body.dry_run,
                 body.approved_by, body.token_id, body.acknowledge_dependencies, body.plan_hash)


@router.get("/remediation/runs", summary="Recent removal runs")
def runs(limit: int = Query(20, ge=1, le=200)):
    return {"items": engine.list_runs(limit)}


@router.get("/remediation/runs/{run_id}", summary="One removal run")
def get_run(run_id: str):
    r = engine.get_run(run_id)
    if r is None:
        raise HTTPException(404, f"unknown run_id {run_id}")
    return r


@router.post("/remediation/runs/{run_id}/outcome", summary="Outcome report for an executed run")
def outcome(run_id: str):
    return _call(engine.report_outcome, run_id)


# ---------------------------------------------------------------- runbook actions ("Fix now")
class RunbookRunIn(BaseModel):
    runbook_id: str | None = Field(None, max_length=32)
    category: str | None = Field(None, max_length=64)
    signal: str | None = Field(None, max_length=32)
    device_ids: list[str] | None = Field(None, max_length=500)
    department: str | None = Field(None, max_length=64)
    dry_run: bool = True
    approved_by: str | None = Field(None, max_length=255)
    token_id: str | None = Field(None, max_length=128)
    max_devices: int = Field(50, ge=1, le=500)
    plan_hash: str | None = Field(None, max_length=64, description="from the reviewed dry run; required to execute")


@router.get("/remediation/runbooks", summary="Runbook catalog with risk and approval policy")
def runbook_catalog():
    return {"items": runbooks.catalog()}


@router.get("/remediation/runbooks/targets", summary="Devices a runbook would fix")
def runbook_targets(runbook_id: str | None = None, category: str | None = None, signal: str | None = None,
                    devices: str | None = None, department: str | None = None, limit: int = Query(100, ge=1, le=1000)):
    return _call(runbooks.targets, runbook_id, category, signal, _devices(devices), department, limit)


@router.post("/remediation/runbooks/runs", summary="Plan (dry run) or execute a runbook on its target devices")
def runbook_run(body: RunbookRunIn):
    return _call(runbooks.run, body.runbook_id, body.category, body.signal, body.device_ids, body.department,
                 body.dry_run, body.approved_by, body.token_id, body.max_devices, body.plan_hash)


@router.get("/remediation/audit", summary="Hash-chained audit trail and its integrity")
def audit_trail(run_id: str | None = None, limit: int = Query(50, ge=1, le=500)):
    return {"integrity": audit.verify_chain(), "items": audit.trail(run_id=run_id, limit=limit)}
