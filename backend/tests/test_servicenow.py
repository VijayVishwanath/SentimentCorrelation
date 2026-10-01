"""ServiceNow incident sync: field mapping, the live Table API client, the demo instance and the scheduler."""
import base64
import time
from datetime import datetime, timedelta, timezone

import httpx
import pandas as pd
import pytest

from app import db
from app.data.jobs import manager
from app.integrations.servicenow import sync
from app.integrations.servicenow.client import LiveClient, ServiceNowError
from app.integrations.servicenow.mapper import incidents_to_tickets
from app.integrations.servicenow.scheduler import scheduler


def wait(client, job_id, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/v1/datasets/jobs/{job_id}").json()
        if j["state"] in ("succeeded", "failed"):
            return j
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def f(value, display=None):
    return {"value": value, "display_value": value if display is None else display}


def incident(number, **kw):
    rec = {"number": f(number), "sys_updated_on": f("2026-09-20 10:00:00"), "opened_at": f("2026-09-20 09:00:00"),
           "resolved_at": f("2026-09-20 13:30:00"), "state": f("6", "Resolved"),
           "short_description": f("VPN drops"), "description": f("VPN drops every hour, very frustrating"),
           "cmdb_ci": f("abc123", "DEV-00001"), "caller_id": f("u1", "Elena Petrov"),
           "contact_type": f("phone", "Phone"), "category": f("network", "Network"), "subcategory": f("vpn", "VPN"),
           "reopen_count": f("0"), "escalation": f("0")}
    rec.update(kw)
    return rec


@pytest.fixture(autouse=True)
def clean_runs(store):
    with db.get_engine().begin() as conn:
        conn.execute(db.servicenow_sync_runs.delete())
    db.delete_setting_overrides([sync.OVERRIDE_MODE, sync.OVERRIDE_MINUTES])
    yield


# ---------------------------------------------------------------- mapper
def test_mapper_fields_and_states():
    recs = [incident("INC1"),
            incident("INC2", state=f("2", "In Progress"), resolved_at=f("")),
            incident("INC3", reopen_count=f("1")),
            incident("INC4", escalation=f("1"), sys_updated_on=f("2026-09-22 08:00:00")),
            incident("INC5", state=f("8", "Canceled")),
            incident("INC6", short_description=f(""), description=f("")),
            incident("INC7", cmdb_ci=f("", "")),
            incident("INC8", category=f("software", "Software"), subcategory=f("os", "Operating System"))]
    df, st = incidents_to_tickets(recs)
    by = df.set_index("ticket_id")
    assert list(by.index) == ["INC1", "INC2", "INC3", "INC4", "INC8"]
    assert by.loc["INC1", "device_id"] == "DEV-00001" and by.loc["INC1", "employee_name"] == "Elena Petrov"
    assert by.loc["INC1", "category"] == "Network" and by.loc["INC1", "channel"] == "Phone"
    assert by.loc["INC1", "resolution_time_hours"] == 4.5 and by.loc["INC1", "date"] == "2026-09-20"
    assert by.loc["INC1", "ticket_text"] == "VPN drops every hour, very frustrating"  # description already leads with it
    assert by.loc["INC2", "ticket_text"] == "VPN drops every hour, very frustrating"
    assert by["outcome_status"].to_dict() == {"INC1": "Resolved", "INC2": "Pending", "INC3": "Reopened",
                                              "INC4": "Escalated", "INC8": "Resolved"}
    assert by.loc["INC3", "repeat_contact"] is True
    assert pd.isna(by.loc["INC8", "category"])  # left for text inference downstream
    assert (st.fetched, st.mapped, st.skipped_canceled, st.skipped_no_text, st.skipped_no_device) == (8, 5, 1, 1, 1)
    assert st.watermark == "2026-09-22 08:00:00"


# ---------------------------------------------------------------- live client
def test_live_client_pages_auth_and_watermark():
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        offset = int(req.url.params["sysparm_offset"])
        page = [incident(f"INC{offset + i}") for i in range(2 if offset == 0 else 1)]
        return httpx.Response(200, json={"result": page})

    c = LiveClient("dev1.service-now.com", "svc", "pw", extra_query="active=true", page_size=2,
                   transport=httpx.MockTransport(handler))
    out = c.fetch_incidents(datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc))
    assert [r["number"]["value"] for r in out] == ["INC0", "INC1", "INC2"]
    assert len(seen) == 2 and c.instance == "dev1.service-now.com"
    q = seen[0].url.params
    assert q["sysparm_query"] == "sys_updated_on>2026-09-01 12:00:00^active=true^ORDERBYsys_updated_on"
    assert q["sysparm_display_value"] == "all"
    assert seen[0].headers["authorization"] == "Basic " + base64.b64encode(b"svc:pw").decode()


def test_live_client_errors_and_retry():
    calls = {"n": 0}

    def flaky(req):
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "0"}) if calls["n"] == 1 else httpx.Response(200, json={"result": []})

    c = LiveClient("https://dev1.service-now.com", "u", "p", transport=httpx.MockTransport(flaky), retry_wait=0)
    assert c.fetch_incidents(datetime.now(timezone.utc)) == [] and calls["n"] == 2
    bad = LiveClient("dev1.service-now.com", "u", "p", transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    with pytest.raises(ServiceNowError, match="credentials"):
        bad.fetch_incidents(datetime.now(timezone.utc))
    html = LiveClient("dev1.service-now.com", "u", "p",
                      transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>hibernating</html>")))
    with pytest.raises(ServiceNowError, match="JSON"):
        html.test_connection()


# ---------------------------------------------------------------- end to end (demo instance)
def test_mock_sync_is_incremental_and_upserts(client):
    st = client.get("/api/v1/integrations/servicenow/status").json()
    assert st["mode"] == "mock" and st["live_configured"] is False and st["last_run"] is None
    before = client.get("/api/v1/meta").json()["counts"]["tickets"]

    r = client.post("/api/v1/integrations/servicenow/sync")
    assert r.status_code == 202, r.text
    first = r.json()
    assert first["run"]["created"] == 36 and first["run"]["updated"] == 0
    assert wait(client, first["job"]["id"])["state"] == "succeeded"
    assert client.get("/api/v1/meta").json()["counts"]["tickets"] == before + 36
    run1 = sync.get_run(first["run"]["id"])
    assert run1["status"] == "succeeded" and run1["watermark"]
    assert client.get("/api/v1/datasets/active").json()["dataset"]["source"] == "ServiceNow · demo instance"

    time.sleep(1.1)  # ServiceNow timestamps have one-second resolution
    second = client.post("/api/v1/integrations/servicenow/sync").json()
    assert second["run"]["since"] == run1["watermark"]
    assert second["run"]["updated"] > 0 and second["run"]["created"] > 0
    assert wait(client, second["job"]["id"])["state"] == "succeeded"
    after = client.get("/api/v1/meta").json()["counts"]["tickets"]
    assert after == before + 36 + second["run"]["created"]  # updated incidents replaced, not duplicated

    runs = client.get("/api/v1/integrations/servicenow/runs").json()["items"]
    assert [x["status"] for x in runs] == ["succeeded", "succeeded"]


def test_failed_job_keeps_watermark(client, monkeypatch):
    from app.data import jobs
    monkeypatch.setattr(jobs, "validate_frames", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    r = client.post("/api/v1/integrations/servicenow/sync").json()
    assert wait(client, r["job"]["id"])["state"] == "failed"
    run = sync.get_run(r["run"]["id"])
    assert run["status"] == "failed" and "boom" in run["error"] and run["watermark"] is None
    since = sync.watermark("mock", "demo instance")
    assert since < datetime.now(timezone.utc) - timedelta(days=80)  # still the lookback window


def test_sync_while_busy_returns_409(client, monkeypatch):
    monkeypatch.setattr(manager, "running", lambda: object())
    assert client.post("/api/v1/integrations/servicenow/sync").status_code == 409
    assert sync.list_runs() == []


def test_settings_and_live_mode_errors(client):
    r = client.put("/api/v1/integrations/servicenow/settings", json={"mode": "live"})
    assert r.status_code == 422
    r = client.put("/api/v1/integrations/servicenow/settings", json={"auto_sync_minutes": 15})
    assert r.json()["auto_sync_minutes"] == 15 and r.json()["next_run_at"]
    assert client.put("/api/v1/integrations/servicenow/settings", json={"auto_sync_minutes": -1}).status_code == 422


def test_scheduler_tick(client):
    assert scheduler.tick() == "off"
    db.put_setting_overrides({sync.OVERRIDE_MINUTES: 5})
    assert scheduler.tick() == "started"  # never synced: due immediately
    run = sync.list_runs(1)[0]
    assert run["trigger"] == "scheduled"
    wait(client, run["job_id"])
    assert scheduler.tick() == "waiting"
    assert scheduler.tick(datetime.now(timezone.utc) + timedelta(minutes=6)) in ("started", "busy")
    j = sync.list_runs(1)[0].get("job_id")
    if j:
        wait(client, j)


def test_restart_closes_interrupted_runs(client):
    rid = sync._insert(trigger="scheduled", mode="mock", instance="demo instance", status="running", since="x")
    assert sync.recover_interrupted() == 1
    run = sync.get_run(rid)
    assert run["status"] == "failed" and "restarted" in run["error"] and run["watermark"] is None


def test_zz_restore_sample(client):
    r = client.post("/api/v1/datasets/restore-sample")
    assert wait(client, r.json()["id"])["state"] == "succeeded"
    assert client.get("/api/v1/meta").json()["counts"]["tickets"] == 326
