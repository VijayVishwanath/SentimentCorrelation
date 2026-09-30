import pytest

from app.remediation import audit, engine, runbooks
from app.remediation.engine import RemediationError


def test_every_category_has_a_runbook():
    from app.engines.thresholds import CATEGORIES
    assert {r.category for r in runbooks.RUNBOOKS} == set(CATEGORIES)
    assert {r.risk for r in runbooks.RUNBOOKS} == {"low", "high"}


def test_targets_match_command_center_card(client):
    card = client.get("/api/v1/dashboard/command-center").json()["actions"][0]
    t = runbooks.targets(category=card["category"], signal=card["signal"])
    assert t["devices_affected"] == card["devices_affected"]
    assert all(d["evidence"] for d in t["devices"])


def test_dry_run_changes_nothing(store):
    before = runbooks.targets(category="Network")["pending"]
    plan = runbooks.run(category="Network", max_devices=5)
    assert plan["status"] == "planned" and plan["planned"] == 5
    assert plan["devices"][0]["steps"][0]["step"] == "snapshot"
    assert runbooks.targets(category="Network")["pending"] == before


def test_low_risk_is_auto_approved_and_not_repeated(store):
    t = runbooks.targets(category="Login/Auth")
    dev = next(d["device_id"] for d in t["devices"] if not d["already_fixed"]
               and not runbooks._fails(d["device_id"], runbooks.BY_CATEGORY["Login/Auth"]))
    r = runbooks.run(category="Login/Auth", device_ids=[dev], dry_run=False)
    assert r["status"] == "completed" and r["fixed"] == 1 and "auto-approval" in r["approved_by"]
    assert r["projected"]["ticket_reduction_pct"] > 0
    again = runbooks.run(category="Login/Auth", device_ids=[dev], dry_run=False)
    assert again["status"] == "nothing_to_fix"
    flags = runbooks.mark_fix_applied([{"device_id": dev, "category": "Login/Auth"}, {"device_id": dev, "category": "Network"}])
    assert [f["fix_applied"] for f in flags] == [True, False]  # only the runbook that ran
    assert any(e["event"] == "runbook_applied" for e in audit.trail(run_id=r["run_id"]))


def test_high_risk_needs_named_approver_and_token(store):
    with pytest.raises(RemediationError, match="approved_by"):
        runbooks.run(category="Performance", dry_run=False)
    with pytest.raises(RemediationError, match="token"):
        runbooks.run(category="Performance", dry_run=False, approved_by="Jane Doe", token_id="tok_forged")
    tok = engine.issue_token()["token_id"]
    with pytest.raises(RemediationError, match="dry_run=true first"):
        runbooks.run(category="Performance", dry_run=False, approved_by="Jane Doe", token_id=tok, max_devices=3)
    plan = runbooks.run(category="Performance", max_devices=3)
    r = runbooks.run(category="Performance", dry_run=False, approved_by="Jane Doe", token_id=tok, max_devices=3,
                     plan_hash_=plan["plan_hash"])
    assert r["approved_by"] == "Jane Doe" and r["fixed"] + r["rolled_back"] == r["devices_targeted"]
    with pytest.raises(RemediationError, match="human approver"):
        runbooks.run(category="Performance", dry_run=False, approved_by="agent", token_id=engine.issue_token()["token_id"])


def test_failed_step_rolls_device_back(store):
    rb = runbooks.BY_CATEGORY["Application Crash"]
    t = runbooks.targets(rb.runbook_id, limit=10_000)
    dev = next((d["device_id"] for d in t["devices"] if runbooks._fails(d["device_id"], rb) and not d["already_fixed"]), None)
    if dev is None:
        pytest.skip("no simulated failure among targets")
    plan = runbooks.run(rb.runbook_id, device_ids=[dev])
    r = runbooks.run(rb.runbook_id, device_ids=[dev], dry_run=False, approved_by="Jane Doe",
                     token_id=engine.issue_token()["token_id"], plan_hash_=plan["plan_hash"])
    d = r["devices"][0]
    assert r["status"] == "failed" and d["status"] == "rolled_back" and d["escalate"]
    assert not runbooks.targets(rb.runbook_id, device_ids=[dev])["devices"][0]["already_fixed"]


def test_runbook_api(client):
    assert len(client.get("/api/v1/remediation/runbooks").json()["items"]) == 5
    t = client.get("/api/v1/remediation/runbooks/targets?category=Network&limit=3").json()
    assert t["runbook"]["risk"] == "low" and len(t["devices"]) <= 3
    plan = client.post("/api/v1/remediation/runbooks/runs", json={"category": "Hardware", "max_devices": 2}).json()
    assert plan["status"] == "planned" and plan["risk"] == "high"
    refused = client.post("/api/v1/remediation/runbooks/runs", json={"category": "Hardware", "dry_run": False})
    assert refused.status_code == 422
    assert client.post("/api/v1/remediation/runbooks/runs", json={"category": "Nope"}).status_code == 422
