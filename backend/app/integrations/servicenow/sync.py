"""ServiceNow sync runs: fetch incidents changed since the last watermark and analyse them like an upload.

A sync is fetch -> map -> hand the rows to the Module 8 dataset job in append mode, so validation, the
upsert by ticket id, sentiment scoring, correlation and the dashboard refresh are the exact same code path
as a manual upload. The watermark only advances when that job succeeds, so a failed sync re-pulls the same
window next time. Live failures are reported, never papered over with demo data.
"""
from __future__ import annotations

import logging
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, insert, select, update

from ... import db
from ...config import get_settings
from ...data import store as store_mod
from ...data.jobs import Job, JobBusyError, manager
from .client import LiveClient, MockClient, ServiceNowError, SN_TIME, host_of, sn_time
from .mapper import incidents_to_tickets

log = logging.getLogger(__name__)
runs = db.servicenow_sync_runs
MODES = ("auto", "live", "mock")
_lock = threading.Lock()  # one sync start at a time (the dataset job adds its own one-job guard)

OVERRIDE_MODE, OVERRIDE_MINUTES = "servicenow_mode", "servicenow_auto_sync_minutes"


# ---------------------------------------------------------------- configuration
def live_configured() -> bool:
    s = get_settings()
    return bool(s.servicenow_instance and s.servicenow_username and s.servicenow_password)


def effective_settings() -> dict:
    s, o = get_settings(), db.get_setting_overrides()
    mode = o.get(OVERRIDE_MODE, s.servicenow_mode)
    minutes = int(o.get(OVERRIDE_MINUTES, s.servicenow_auto_sync_minutes) or 0)
    return {"mode_setting": mode if mode in MODES else "auto", "auto_sync_minutes": max(0, minutes)}


def resolve_mode() -> str:
    m = effective_settings()["mode_setting"]
    return ("live" if live_configured() else "mock") if m == "auto" else m


def get_client(mode: str | None = None):
    mode = mode or resolve_mode()
    s = get_settings()
    if mode == "live":
        if not live_configured():
            raise ServiceNowError("live mode needs DEX_SERVICENOW_INSTANCE, DEX_SERVICENOW_USERNAME and "
                                  "DEX_SERVICENOW_PASSWORD in .env")
        return LiveClient(s.servicenow_instance, s.servicenow_username, s.servicenow_password,
                          extra_query=s.servicenow_query, page_size=s.servicenow_page_size,
                          max_records=s.servicenow_max_records, timeout=s.servicenow_timeout_sec)
    return MockClient(store_mod.get_store(), batch=_successful_runs("mock", MockClient.instance))


# ---------------------------------------------------------------- run records
def _row(r) -> dict:
    d = dict(r._mapping)
    for k in ("started_at", "finished_at"):
        if d[k] is not None:
            v = d[k] if d[k].tzinfo else d[k].replace(tzinfo=timezone.utc)
            d[k] = v.isoformat()
    return d


def _insert(**values) -> int:
    with db.get_engine().begin() as conn:
        return conn.execute(insert(runs).values(started_at=db.now(), **values)).inserted_primary_key[0]


def _update(run_id: int, **values) -> None:
    with db.get_engine().begin() as conn:
        conn.execute(update(runs).where(runs.c.id == run_id).values(**values))


def get_run(run_id: int) -> dict | None:
    with db.get_engine().connect() as conn:
        r = conn.execute(select(runs).where(runs.c.id == run_id)).first()
    return _row(r) if r else None


def list_runs(limit: int = 20) -> list[dict]:
    with db.get_engine().connect() as conn:
        rows = conn.execute(select(runs).order_by(runs.c.id.desc()).limit(limit)).all()
    return [_row(r) for r in rows]


def _successful_runs(mode: str, instance: str | None) -> int:
    with db.get_engine().connect() as conn:
        return int(conn.execute(select(func.count()).select_from(runs).where(
            runs.c.mode == mode, runs.c.instance == instance, runs.c.status == "succeeded")).scalar() or 0)


def watermark(mode: str, instance: str | None) -> datetime:
    """Last successful watermark for this instance, else the lookback window."""
    with db.get_engine().connect() as conn:
        w = conn.execute(select(runs.c.watermark).where(
            runs.c.mode == mode, runs.c.instance == instance, runs.c.status.in_(("succeeded", "no_changes")),
            runs.c.watermark.is_not(None)).order_by(runs.c.id.desc()).limit(1)).scalar()
    if w:
        return datetime.strptime(w, SN_TIME).replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - timedelta(days=get_settings().servicenow_lookback_days)


# ---------------------------------------------------------------- sync
def start_sync(trigger: str = "manual") -> dict:
    """Fetch and submit one sync. Returns {"run": ..., "job": ...|None}.

    Raises JobBusyError when a dataset job is already running and ServiceNowError when the instance
    cannot be read (the failed run is recorded either way except for busy, which changes nothing).
    """
    if not _lock.acquire(blocking=False):
        raise JobBusyError("a ServiceNow sync is already starting")
    try:
        if manager.running():
            raise JobBusyError("another dataset is being analysed — wait for it to finish")
        client = get_client()
        since = watermark(client.mode, client.instance)
        run_id = _insert(trigger=trigger, mode=client.mode, instance=client.instance, status="running",
                         since=sn_time(since))
        try:
            records = client.fetch_incidents(since)
        except ServiceNowError as e:
            _update(run_id, status="failed", error=str(e), finished_at=db.now())
            raise
        frame, stats = incidents_to_tickets(records)
        vals = {"fetched": stats.fetched, "skipped": stats.skipped, "watermark": stats.watermark or sn_time(since)}
        if frame.empty:
            _update(run_id, status="no_changes", finished_at=db.now(), **vals)
            return {"run": get_run(run_id), "job": None, "mapping": stats.as_dict()}

        st = store_mod.get_store()
        known = set(st.tickets["ticket_id"].astype(str))
        devices = set(st.devices["device_id"].astype(str))
        vals["updated"] = int(frame["ticket_id"].isin(known).sum())
        vals["created"] = int(len(frame) - vals["updated"])
        vals["unmatched_devices"] = int((~frame["device_id"].isin(devices)).sum())
        workdir = Path(tempfile.mkdtemp(prefix="dex_servicenow_"))
        path = workdir / "tickets.csv"
        frame.to_csv(path, index=False)
        _update(run_id, **vals)
        label = f"ServiceNow · {client.instance}"
        try:
            job = manager.submit([("servicenow_incidents.csv", path, path.stat().st_size)], "append", workdir,
                                 source=label, on_done=lambda j: _finish(run_id, vals["watermark"], j))
        except JobBusyError:
            _update(run_id, status="skipped", error="another dataset job started first", finished_at=db.now(),
                    watermark=None)
            import shutil
            shutil.rmtree(workdir, ignore_errors=True)
            raise
        _update(run_id, job_id=job.id)
        return {"run": get_run(run_id), "job": job.as_dict(), "mapping": stats.as_dict()}
    finally:
        _lock.release()


def _finish(run_id: int, mark: str, job: Job) -> None:
    if job.state == "succeeded":
        _update(run_id, status="succeeded", watermark=mark, finished_at=db.now())
    else:
        detail = "; ".join(job.issues) if job.issues else ""
        _update(run_id, status="failed", watermark=None, finished_at=db.now(),
                error=(job.error or "analysis failed") + (f": {detail}" if detail else ""))
    log.info("servicenow sync run %s finished: %s", run_id, job.state)


def status() -> dict:
    s, eff = get_settings(), effective_settings()
    mode = resolve_mode()
    from .scheduler import scheduler
    hist = list_runs(1)
    return {"mode": mode, "mode_setting": eff["mode_setting"], "live_configured": live_configured(),
            "instance": host_of(s.servicenow_instance) if mode == "live" else MockClient.instance,
            "configured_instance": host_of(s.servicenow_instance),
            "auto_sync_minutes": eff["auto_sync_minutes"], "next_run_at": scheduler.next_run_at(),
            "lookback_days": s.servicenow_lookback_days, "last_run": hist[0] if hist else None,
            "job_running": manager.running() is not None}
