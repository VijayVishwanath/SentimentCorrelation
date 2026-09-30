import anyio
import pytest
from sqlalchemy import select, update

from app import db
from app.remediation import audit, engine, mailbox
from app.remediation.engine import RemediationError
from app.remediation.inventory import _base_inventory, device_inventory, version_matches, version_prefix
from app.remediation.parser import parse_email

ALLOWED = ["security-team@company.com"]
DOTNET = "Microsoft .NET Runtime"


@pytest.fixture(scope="module")
def inbox(store):
    mailbox.seed_demo_inbox(store)
    return {m["message_id"]: m for m in mailbox.list_emails(None)}


def _carrier(store, pred):
    for d in store.device_ids():
        for i in _base_inventory(d):
            if pred(i, d):
                return d, i
    pytest.skip("no device in the fleet matches")


# ------------------------------------------------------------------ parsing
def test_parses_structured_email():
    body = ("Software: Microsoft .NET Runtime\nVersion: 6.0.36\nUrgency: IMMEDIATE (24 hours)\n"
            "Affected Devices:\n- Device IDs: DEV-0042, DEV-0043, DEV-0042\nReason: EOL\nReplace with: .NET 8.0.16 LTS\n")
    r = parse_email("m1", "Security <security-team@company.com>", "[EOL-SOFTWARE] .NET 6.0.36", body, [], ALLOWED)
    assert r.valid and r.sender_authorized
    assert (r.software_name, r.software_version, r.urgency) == (DOTNET, "6.0.36", "critical")
    assert r.device_ids == ["DEV-0042", "DEV-0043"]
    assert r.request_type == "end_of_life" and r.replacement == ".NET 8.0.16 LTS"


def test_lookalike_sender_is_rejected():
    r = parse_email("m2", "security-team@company.com.attacker.io", "[UNAUTHORIZED-SOFTWARE] X 1.0",
                    "Software: X\nVersion: 1.0\nAffected Devices: all\n", [], ALLOWED)
    assert not r.sender_authorized and not r.valid


def test_subject_fallback_csv_attachment_and_fleet_scope():
    csv = "device_id,software_name,software_version\nDEV-00001,WinRAR,5.61.0\nDEV-00002,WinRAR,5.61.0\n"
    r = parse_email("m3", "security-team@company.com", "[SECURITY-PATCH] WinRAR 5.61.0 CVE", "see attachment",
                    [{"filename": "devices.csv", "content": csv}], ALLOWED)
    assert r.valid and r.software_name == "WinRAR" and r.device_ids == ["DEV-00001", "DEV-00002"]
    fleet = parse_email("m4", "security-team@company.com", "[UNAUTHORIZED-SOFTWARE] uTorrent 3.6.0",
                        "Affected Devices: all", [], ALLOWED)
    assert fleet.valid and fleet.scope == "fleet"


def test_version_is_required():
    r = parse_email("m5", "security-team@company.com", "[UNAUTHORIZED-SOFTWARE] TeamViewer",
                    "Software: TeamViewer\nAffected Devices: all\n", [], ALLOWED)
    assert not r.valid and any("version" in e for e in r.errors)


def test_version_matching_is_exact():
    assert version_matches("6.0.36 (x64)", "6.0.36") and version_matches("6.0.36.0", "6.0.36")
    assert not version_matches("6.0.37", "6.0.36") and not version_matches("6.0.3", "6.0.36")
    assert version_prefix("6.0.36", "6.0") and not version_prefix("3.5.1", "3.0")


# ------------------------------------------------------------------ targeting and safety
def test_matcher_leaves_other_versions(store):
    m = engine.match_versions(DOTNET, "6.0.36")
    assert m["matching_installations"] > 0
    assert all(x["version"] == "6.0.36" for x in m["matches"])
    assert "8.0.16" in m["other_versions_left_untouched"]


def test_short_device_ids_are_normalized(store):
    d = store.device_ids()[0]
    short = f"DEV-{int(d.split('-')[1])}"
    assert engine.normalize_device_ids(store, [short, "DEV-99999999"]) == ([d], ["DEV-99999999"])


def test_system_critical_software_is_blocked(store):
    d, i = _carrier(store, lambda i, d: i.system_critical)
    s = engine.validate_safety(i.display_name, i.version, [d])
    assert s["devices"][0]["status"] == "blocked" and not s["safe_to_proceed"]


def test_dependency_blocks_unless_acknowledged(store):
    d, _ = _carrier(store, lambda i, d: i.catalog_key == "expense" and i.version.startswith("3.0")
                    and any(x.catalog_key == "dotnet" and x.version == "6.0.36" for x in _base_inventory(d)))
    blocked = engine.validate_safety(DOTNET, "6.0.36", [d])["devices"][0]
    assert blocked["status"] == "blocked" and blocked["dependencies"]
    ok = engine.validate_safety(DOTNET, "6.0.36", [d], acknowledge_dependencies=True)["devices"][0]
    assert ok["status"] == "warning"


# ------------------------------------------------------------------ removal
def _removable(store, locked: bool):
    """A standalone (no dependents, single-arch) install whose simulated uninstaller succeeds or fails."""
    return _carrier(store, lambda i, d: i.catalog_key in ("teamviewer", "anydesk", "utorrent", "winrar", "python")
                    and i.uninstaller_locked == locked)


def _run(approver="Jane Doe", **kw):
    """The real flow: dry run -> a human reviews it -> execute that exact plan with a fresh single-use token."""
    plan = engine.remove(**kw)
    return engine.remove(**kw, dry_run=False, approved_by=approver, token_id=engine.issue_token()["token_id"],
                         plan_hash_=plan["plan_hash"])


def test_dry_run_changes_nothing(store):
    d, i = _removable(store, locked=False)
    plan = engine.remove(i.display_name, i.version, [d])
    assert plan["status"] == "planned" and plan["devices"][0]["steps"][0]["step"] == "restore_point"
    assert any(x.installation_id == i.installation_id for x in device_inventory(d))


def test_execution_needs_approver_and_valid_token(store):
    d, i = _removable(store, locked=False)
    with pytest.raises(RemediationError, match="approved_by"):
        engine.remove(i.display_name, i.version, [d], dry_run=False, token_id="x")
    with pytest.raises(RemediationError, match="token"):
        engine.remove(i.display_name, i.version, [d], dry_run=False, approved_by="Jane Doe", token_id="tok_forged")
    with pytest.raises(RemediationError):
        engine.issue_token(["domain_admin"])


def test_execute_removes_only_target_and_verifies(store):
    d, i = _removable(store, locked=False)
    others = [x.installation_id for x in device_inventory(d) if x.installation_id != i.installation_id]
    run = _run(software_name=i.display_name, version=i.version, device_ids=[d])
    assert run["status"] == "completed" and run["removed"] == 1
    assert engine.verify(i.display_name, i.version, [d])["all_removed"]
    assert [x.installation_id for x in device_inventory(d)] == others
    again = _run(software_name=i.display_name, version=i.version, device_ids=[d])
    assert again["status"] == "nothing_to_remove"
    report = engine.report_outcome(run["run_id"])
    assert report["devices_removed"] == 1 and "Jane Doe" in report["security_team_summary"]
    assert report["devices"][0]["user_notification"].startswith("Hi ")


def test_failed_uninstall_rolls_device_back(store):
    d, i = _removable(store, locked=True)
    run = _run(software_name=i.display_name, version=i.version, device_ids=[d])
    assert run["status"] == "failed" and run["devices"][0]["status"] == "rolled_back"
    assert run["devices"][0]["escalate"] is True
    assert any(x.installation_id == i.installation_id for x in device_inventory(d))


def test_email_driven_run_closes_the_email(store, inbox):
    mid = "<demo-001@company.com>"
    run = _run(message_id=mid)
    assert run["removed"] >= 1 and run["urgency"] == "critical"
    engine.report_outcome(run["run_id"])
    assert mailbox.get_email(mid)["status"] == "processed"
    assert inbox["<demo-004@company.com>"]["status"] == "rejected"
    with pytest.raises(RemediationError, match="not actionable"):
        engine.remove(message_id="<demo-004@company.com>")


def test_tokens_are_single_use_and_bound_to_the_reviewed_plan(store):
    # an install still present (earlier tests remove the first matching one)
    d, i = _carrier(store, lambda i, d: i.catalog_key in ("teamviewer", "anydesk", "utorrent", "winrar", "python")
                    and not i.uninstaller_locked and any(x.installation_id == i.installation_id for x in device_inventory(d)))
    kw = {"software_name": i.display_name, "version": i.version, "device_ids": [d]}
    plan = engine.remove(**kw)
    tok = engine.issue_token()["token_id"]
    with pytest.raises(RemediationError, match="dry_run=true first"):
        engine.remove(**kw, dry_run=False, approved_by="Jane Doe", token_id=tok)
    with pytest.raises(RemediationError, match="plan changed"):
        engine.remove(**kw, dry_run=False, approved_by="Jane Doe", token_id=tok, plan_hash_="0" * 16)
    run = engine.remove(**kw, dry_run=False, approved_by="Jane Doe", token_id=tok, plan_hash_=plan["plan_hash"])
    assert run["removed"] == 1  # the refused attempts above did not spend the token
    with pytest.raises(RemediationError, match="already-used"):
        engine.remove(**kw, dry_run=False, approved_by="Jane Doe", token_id=tok, plan_hash_=plan["plan_hash"])


@pytest.mark.parametrize("who", ["agent", "Claude", "DEX Copilot", "system"])
def test_agent_cannot_approve_its_own_execution(store, who):
    d, i = _removable(store, locked=False)
    with pytest.raises(RemediationError, match="human approver"):
        engine.remove(i.display_name, i.version, [d], dry_run=False, approved_by=who,
                      token_id=engine.issue_token()["token_id"])


def test_audit_chain_detects_tampering(store):
    audit.record("test_event", {"x": 1})
    assert audit.verify_chain()["intact"]
    t = db.remediation_audit
    with db.get_engine().begin() as conn:
        row_id, original = conn.execute(select(t.c.id, t.c.payload_json).order_by(t.c.id).limit(1)).one()
        conn.execute(update(t).where(t.c.id == row_id).values(payload_json='{"tampered": true}'))
    broken = audit.verify_chain()
    assert not broken["intact"] and broken["first_broken_id"] == row_id
    with db.get_engine().begin() as conn:  # restore so later tests see an intact chain
        conn.execute(update(t).where(t.c.id == row_id).values(payload_json=original))
    assert audit.verify_chain()["intact"]  # must not read a stale snapshot left by the early-exit check above


# ------------------------------------------------------------------ MCP surface
def test_mcp_server_exposes_workflow_tools(store, inbox):
    from mcp.client.client import Client

    from app.remediation.mcp_server import server

    async def run():
        async with Client(server) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            parsed = await c.call_tool("email_parser", {"message_id": "<demo-002@company.com>"})
            refused = await c.call_tool("removal_orchestrator", {"message_id": "<demo-002@company.com>",
                                                                 "dry_run": False})
            return names, parsed.structured_content, refused
    names, parsed, refused = anyio.run(run)
    assert {"email_monitor", "email_parser", "software_inventory", "version_matcher", "safety_validator",
            "credential_manager", "removal_orchestrator", "verify_removal", "outcome_reporter", "audit_trail"} <= names
    assert parsed["software_name"] == "TeamViewer" and parsed["scope"] == "fleet"
    assert refused.is_error and "approved_by" in refused.content[0].text


# ------------------------------------------------------------------ REST API (web UI)
def test_api_inbox_and_request(client, inbox):
    from urllib.parse import quote
    r = client.get("/api/v1/remediation/emails")
    assert r.status_code == 200 and {m["status"] for m in r.json()["items"]} >= {"rejected"}
    req = client.get(f"/api/v1/remediation/emails/{quote('<demo-003@company.com>', safe='')}/request").json()
    assert req["software_name"] == "WinRAR archiver" and req["device_ids"] and req["valid"]
    bad = client.get(f"/api/v1/remediation/emails/{quote('<demo-004@company.com>', safe='')}/request").json()
    assert bad["valid"] is False and not bad["sender_authorized"]


def test_api_plan_approve_execute_report(client, inbox):
    mid = "<demo-003@company.com>"
    plan = client.post("/api/v1/remediation/runs", json={"message_id": mid})
    assert plan.status_code == 200 and plan.json()["status"] == "planned"
    refused = client.post("/api/v1/remediation/runs", json={"message_id": mid, "dry_run": False})
    assert refused.status_code == 422 and "approved_by" in refused.json()["error"]
    tok = client.post("/api/v1/remediation/token").json()
    run = client.post("/api/v1/remediation/runs", json={"message_id": mid, "dry_run": False, "approved_by": "Jane Doe",
                                                        "token_id": tok["token_id"], "plan_hash": plan.json()["plan_hash"]}).json()
    assert run["status"] in ("completed", "partial", "failed") and run["devices_targeted"] >= 1
    assert client.get(f"/api/v1/remediation/runs/{run['run_id']}").json()["run_id"] == run["run_id"]
    assert any(x["run_id"] == run["run_id"] for x in client.get("/api/v1/remediation/runs").json()["items"])
    out = client.post(f"/api/v1/remediation/runs/{run['run_id']}/outcome").json()
    assert "security_team_summary" in out
    a = client.get("/api/v1/remediation/audit").json()
    assert a["integrity"]["intact"] and a["items"]
    assert client.get("/api/v1/remediation/runs/SWR-NOPE").status_code == 404
