"""Admin API: metadata and business-assumption settings."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..config import get_settings
from ..copilot.tools import effective_config
from ..data.store import DataStore
from ..engines.thresholds import THRESHOLDS
from .deps import CleanRoute, store_dep
from .routes_analytics import clear_cache
from .warmup import warm_in_background

router = APIRouter(route_class=CleanRoute)

EDITABLE = ("cost_per_ticket_usd", "hourly_employee_cost_usd", "productivity_loss_factor", "resolution_sla_hours",
            "working_days_per_year", "roi_minutes_saved_per_day", "roi_minutes_per_hang", "roi_boots_per_day",
            "roi_unused_licenses", "annual_license_cost_usd", "roi_avoided_replacements", "device_cost_usd")


class SettingsIn(BaseModel):
    cost_per_ticket_usd: float | None = Field(None, ge=0, le=10000)
    hourly_employee_cost_usd: float | None = Field(None, ge=0, le=10000)
    productivity_loss_factor: float | None = Field(None, ge=0, le=1)
    resolution_sla_hours: float | None = Field(None, gt=0, le=720)
    working_days_per_year: float | None = Field(None, ge=1, le=366)
    roi_minutes_saved_per_day: float | None = Field(None, ge=0, le=480)
    roi_minutes_per_hang: float | None = Field(None, ge=0, le=240)
    roi_boots_per_day: float | None = Field(None, ge=0, le=50)
    roi_unused_licenses: float | None = Field(None, ge=0, le=10_000_000)
    annual_license_cost_usd: float | None = Field(None, ge=0, le=100_000)
    roi_avoided_replacements: float | None = Field(None, ge=0, le=10_000_000)
    device_cost_usd: float | None = Field(None, ge=0, le=100_000)
    reset: list[str] = Field(default_factory=list, description="settings to return to their default / data-derived value")


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


def _rewarm() -> None:
    """Recompute the heavy views in the background so the next page load after a change is not the slow one."""
    warm_in_background("settings-rewarm")


@router.put("/settings", summary="Update business-impact assumptions")
def put_app_settings(body: SettingsIn):
    bad = [k for k in body.reset if k not in EDITABLE]
    if bad:
        raise HTTPException(422, f"unknown settings: {bad}")
    values = {k: v for k, v in body.model_dump(exclude={"reset"}).items() if v is not None}
    db.delete_setting_overrides(body.reset)
    db.put_setting_overrides(values)
    clear_cache()
    _rewarm()
    return get_app_settings()
