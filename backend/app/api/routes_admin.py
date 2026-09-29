"""Admin API: health, metadata, business-assumption settings, dataset upload/reset."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .. import db
from ..config import get_settings
from ..copilot.tools import effective_config
from ..data import store as store_mod
from ..data.store import DataStore
from ..engines.thresholds import THRESHOLDS
from .deps import CleanRoute, store_dep
from .routes_analytics import clear_cache

router = APIRouter(route_class=CleanRoute)

EDITABLE = ("cost_per_ticket_usd", "hourly_employee_cost_usd", "productivity_loss_factor", "resolution_sla_hours")


class SettingsIn(BaseModel):
    cost_per_ticket_usd: float | None = Field(None, ge=0, le=10000)
    hourly_employee_cost_usd: float | None = Field(None, ge=0, le=10000)
    productivity_loss_factor: float | None = Field(None, ge=0, le=1)
    resolution_sla_hours: float | None = Field(None, gt=0, le=720)


@router.get("/meta", summary="Dataset version, dimensions and thresholds for UI filters")
def meta(store: DataStore = Depends(store_dep)):
    return {"app": get_settings().app_name, "dataset": db.latest_dataset_version(),
            "counts": {"devices": len(store.devices), "telemetry_rows": len(store.telemetry),
                       "tickets": len(store.tickets), "remediations": len(store.remediations)},
            "dimensions": store.dimensions(), "thresholds": THRESHOLDS}


@router.get("/settings", summary="Business-impact assumptions")
def get_app_settings():
    cfg = effective_config()
    return {k: cfg[k] for k in EDITABLE}


@router.put("/settings", summary="Update business-impact assumptions")
def put_app_settings(body: SettingsIn):
    values = {k: v for k, v in body.model_dump().items() if v is not None}
    db.put_setting_overrides(values)
    clear_cache()
    return get_app_settings()


@router.post("/data/upload", summary="Replace the dataset (synchronous; Module 8 uses /datasets/analyze)")
async def upload(file: UploadFile = File(...)):
    import shutil
    import tempfile
    from pathlib import Path

    from ..data.jobs import JobBusyError, manager, max_upload_bytes
    from .routes_datasets import _save
    workdir = Path(tempfile.mkdtemp(prefix="dex_upload_"))
    try:
        saved = await _save(file, workdir, max_upload_bytes())
        job = manager.submit([saved], "replace", workdir, background=False)
    except JobBusyError as e:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(409, str(e))
    except HTTPException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    if job.state != "succeeded":
        raise HTTPException(422, {"message": job.error or "dataset validation failed", "issues": job.issues})
    return {"status": "loaded", "rows": job.result["rows"], "warnings": job.result["report"]["warnings"],
            "dataset": db.latest_dataset_version(), "job_id": job.id}


@router.post("/data/reset", summary="Reload the bundled simulated dataset")
def reset():
    store_mod.init_store(force_seed=True)
    clear_cache()
    return {"status": "reset", "dataset": db.latest_dataset_version()}
