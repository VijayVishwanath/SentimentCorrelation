"""Module 8 — Upload Dataset: real-world style uploads, modes, limits and failure isolation."""
import io
import time

import pandas as pd
import pytest

from app.data import store as store_mod


def wait(client, job_id, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/v1/datasets/jobs/{job_id}").json()
        if j["state"] in ("succeeded", "failed"):
            return j
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def csv_bytes(df: pd.DataFrame, sep: str = ",") -> bytes:
    return df.to_csv(index=False, sep=sep).encode("utf-8")


def realworld_files(store, n_devices=80):
    """ServiceNow / DEX-platform style exports: aliases, dates instead of weeks, daily telemetry, no categories."""
    devs = store.devices["device_id"].head(n_devices).tolist()
    tel = store.telemetry[store.telemetry["device_id"].isin(devs)].copy()
    daily = []
    for offset in (0, 2):  # two readings per device-week -> must be rolled up
        d = tel.copy()
        d["Date"] = (pd.to_datetime(d["week_start"]) + pd.Timedelta(days=offset)).dt.strftime("%d-%b-%Y")
        daily.append(d)
    tel = pd.concat(daily).rename(columns={
        "device_id": "Device ID", "boot_duration_sec": "Boot Time (sec)", "network_latency_ms": "Latency (ms)",
        "app_hang_count": "App Hangs", "packet_loss_pct": "Packet Loss", "policy_compliant": "Compliance Status",
        "hardware_health_score": "Hardware Health"})
    tel["Compliance Status"] = tel["Compliance Status"].map({True: "Compliant", False: "Non-compliant"})
    tel = tel[["Device ID", "Date", "Boot Time (sec)", "Latency (ms)", "App Hangs", "Packet Loss",
               "Compliance Status", "Hardware Health"]]
    tk = store.tickets[store.tickets["device_id"].isin(devs)].copy()
    wk = store.telemetry.drop_duplicates("week").set_index("week")["week_start"]
    tk["Opened At"] = pd.to_datetime(tk["week"].map(wk)) + pd.Timedelta(days=1)
    tk = tk.rename(columns={"ticket_id": "Number", "device_id": "Configuration Item", "ticket_text": "Short Description",
                            "channel": "Contact Type", "outcome_status": "State", "employee_name": "Caller"})
    tk = tk[["Number", "Configuration Item", "Caller", "Opened At", "Contact Type", "Short Description", "State"]]
    return csv_bytes(tel, sep=";"), csv_bytes(tk)


def test_schema_templates_and_active(client):
    assert {t["table"] for t in client.get("/api/v1/datasets/schema").json()["tables"]} == {
        "devices", "telemetry", "tickets", "remediations"}
    r = client.get("/api/v1/datasets/templates/tickets.csv")
    assert r.status_code == 200 and "ticket_text" in r.text.splitlines()[0]
    a = client.get("/api/v1/datasets/active").json()
    assert a["limits"]["max_file_mb"] == 200 and a["metrics"]["tickets"] > 0


def test_realworld_csv_replace_updates_everything(client, store):
    tel_b, tk_b = realworld_files(store)
    r = client.post("/api/v1/datasets/analyze", data={"mode": "replace"}, files=[
        ("files", ("dex_export_telemetry.csv", tel_b, "text/csv")),
        ("files", ("servicenow_incidents.csv", tk_b, "text/csv"))])
    assert r.status_code == 202, r.text
    j = wait(client, r.json()["id"])
    assert j["state"] == "succeeded", (j["error"], j["issues"])
    rep = j["result"]["report"]
    derived = " ".join(rep["derived"])
    assert "rolled up" in derived and "week number derived" in derived and "category inferred" in derived
    assert "devices" in derived  # devices derived from ids
    assert j["result"]["after"]["devices"] == 80
    assert j["result"]["before"]["devices"] == 260
    # every module now reflects the new data
    assert client.get("/api/v1/meta").json()["counts"]["devices"] == 80
    k = client.get("/api/v1/dashboard/executive").json()["kpis"]
    assert k["dex_score"] is not None and k["correlation_score"] is not None
    assert client.get("/api/v1/correlation/analysis").status_code == 200
    assert client.get("/api/v1/outcomes").json()["cases"] == 0  # no remediations uploaded
    dev = client.get("/api/v1/telemetry/devices?limit=1").json()["items"][0]["device_id"]
    assert client.post("/api/v1/diagnosis", json={"ticket_text": "wifi keeps dropping", "device_id": dev}).status_code == 200
    assert client.post("/api/v1/copilot/ask", json={"question": "fleet overview"}).status_code == 200


def test_append_mode_adds_rows(client, store):
    before = client.get("/api/v1/meta").json()["counts"]["tickets"]
    dev = client.get("/api/v1/telemetry/devices?limit=1").json()["items"][0]["device_id"]
    new = pd.DataFrame({"ticket_id": ["NEW-1", "NEW-2"], "device_id": [dev, dev], "week": [12, 12],
                        "ticket_text": ["This is unacceptable, VPN keeps failing", "Following up again — no change"]})
    rem = pd.DataFrame({"remediation_id": ["R-NEW"], "device_id": [dev], "week_of_remediation": [6],
                        "root_cause_category": ["Network"], "action_taken": ["Replaced Wi-Fi adapter"]})
    r = client.post("/api/v1/datasets/analyze", data={"mode": "append"}, files=[
        ("files", ("new_tickets.csv", csv_bytes(new), "text/csv")),
        ("files", ("fixes.csv", csv_bytes(rem), "text/csv"))])
    j = wait(client, r.json()["id"])
    assert j["state"] == "succeeded", (j["error"], j["issues"])
    assert client.get("/api/v1/meta").json()["counts"]["tickets"] == before + 2
    out = client.get("/api/v1/outcomes").json()
    assert out["cases"] == 1 and out["rows"][0]["ticket_rate_pre"] is not None  # derived before/after


def test_validation_failure_leaves_live_data(client):
    before = client.get("/api/v1/meta").json()["counts"]
    bad = pd.DataFrame({"foo": [1, 2], "bar": [3, 4]})
    r = client.post("/api/v1/datasets/analyze", data={"mode": "replace"},
                    files=[("files", ("random.csv", csv_bytes(bad), "text/csv"))])
    j = wait(client, r.json()["id"])
    assert j["state"] == "failed" and j["issues"]
    assert client.get("/api/v1/meta").json()["counts"] == before


def test_limits(client, monkeypatch):
    from app.config import get_settings
    r = client.post("/api/v1/datasets/analyze", files=[("files", ("x.json", b"{}", "application/json"))])
    assert r.status_code == 415
    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    big = b"device_id,week,ticket_id,ticket_text\n" + b"D1,1,T1,hello world\n" * 70000
    r = client.post("/api/v1/datasets/analyze", files=[("files", ("big.csv", big, "text/csv"))])
    assert r.status_code == 413
    assert client.post("/api/v1/datasets/analyze", data={"mode": "merge"},
                       files=[("files", ("a.csv", b"a,b\n1,2\n", "text/csv"))]).status_code == 422


def test_restore_sample_restores_golden(client):
    r = client.post("/api/v1/datasets/restore-sample")
    j = wait(client, r.json()["id"])
    assert j["state"] == "succeeded"
    assert client.get("/api/v1/meta").json()["counts"] == {"devices": 260, "telemetry_rows": 3120, "tickets": 326,
                                                           "remediations": 46}
    agg = client.get("/api/v1/outcomes").json()["aggregate"]
    assert round(agg["frustration"]["pre"], 1) == 69.0 and round(agg["repeat_rate"]["post"], 1) == 0.7
    # later tests / modules use the module-level store
    assert len(store_mod.get_store().tickets) == 326
