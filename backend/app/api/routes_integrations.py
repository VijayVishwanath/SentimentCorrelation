"""Integrations API: one-click and scheduled ServiceNow incident sync."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from .. import db
from ..data.jobs import JobBusyError
from ..integrations.servicenow import sync
from ..integrations.servicenow.client import ServiceNowError
from .deps import CleanRoute

router = APIRouter(route_class=CleanRoute)


class SyncSettingsIn(BaseModel):
    mode: str | None = Field(None, description="auto | live | mock")
    auto_sync_minutes: int | None = Field(None, ge=0, le=1440, description="0 turns auto-sync off")


@router.get("/integrations/servicenow/status", summary="ServiceNow sync: mode, instance, last run, schedule")
def servicenow_status():
    return sync.status()


@router.post("/integrations/servicenow/sync", status_code=202,
             summary="Sync with ServiceNow — pull incidents changed since the last sync and analyse them")
async def servicenow_sync():
    try:
        return await run_in_threadpool(sync.start_sync, "manual")
    except JobBusyError as e:
        raise HTTPException(409, str(e))
    except ServiceNowError as e:
        raise HTTPException(502, str(e))


@router.post("/integrations/servicenow/test", summary="Check that the ServiceNow instance can be read")
async def servicenow_test():
    try:
        return await run_in_threadpool(lambda: sync.get_client().test_connection())
    except ServiceNowError as e:
        raise HTTPException(502, str(e))


@router.get("/integrations/servicenow/runs", summary="Recent ServiceNow sync runs")
def servicenow_runs(limit: int = 20):
    return {"items": sync.list_runs(min(max(limit, 1), 100))}


@router.put("/integrations/servicenow/settings", summary="Change the sync mode or the auto-sync interval")
def servicenow_settings(body: SyncSettingsIn):
    values = {}
    if body.mode is not None:
        if body.mode not in sync.MODES:
            raise HTTPException(422, "mode must be auto, live or mock")
        if body.mode == "live" and not sync.live_configured():
            raise HTTPException(422, "live mode needs DEX_SERVICENOW_INSTANCE, USERNAME and PASSWORD in .env")
        values[sync.OVERRIDE_MODE] = body.mode
    if body.auto_sync_minutes is not None:
        values[sync.OVERRIDE_MINUTES] = body.auto_sync_minutes
    db.put_setting_overrides(values)
    return sync.status()
