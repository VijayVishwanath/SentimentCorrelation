"""Shared API dependencies: filters, security, JSON-safe responses."""
from __future__ import annotations

import datetime as dt
import json
import math
import functools
import inspect
import secrets
from dataclasses import dataclass

import numpy as np
import pandas as pd
from fastapi import Header, HTTPException, Query, status
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute

from ..config import get_settings
from ..data.store import DataStore, get_store


def clean(obj):
    """Recursively convert numpy/pandas values and NaN/inf into JSON-safe python values."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [clean(v) for v in obj]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(obj, (pd.Timestamp, dt.date, dt.datetime)):
        return obj.isoformat()
    if obj is pd.NA or obj is pd.NaT:
        return None
    if isinstance(obj, pd.DataFrame):
        return clean(obj.to_dict("records"))
    return obj


class SafeJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(clean(content), ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


class CleanRoute(APIRoute):
    """Route class that converts numpy/pandas/NaN results to JSON-safe values before FastAPI encodes them."""

    def __init__(self, path, endpoint, **kwargs):
        if inspect.iscoroutinefunction(endpoint):
            @functools.wraps(endpoint)
            async def wrapped(*a, **kw):
                out = await endpoint(*a, **kw)
                return out if isinstance(out, Response) else clean(out)
        else:
            @functools.wraps(endpoint)
            def wrapped(*a, **kw):
                out = endpoint(*a, **kw)
                return out if isinstance(out, Response) else clean(out)
        super().__init__(path, wrapped, **kwargs)


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = get_settings().api_key
    if expected and not (x_api_key and secrets.compare_digest(x_api_key, expected)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing X-API-Key")


@dataclass
class Filters:
    department: str | None = None
    device_model: str | None = None
    work_mode: str | None = None
    week_from: int | None = None
    week_to: int | None = None

    def key(self) -> tuple:
        return (self.department, self.device_model, self.work_mode, self.week_from, self.week_to)

    def describe(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, "")}


def filters(department: str | None = Query(None), device_model: str | None = Query(None),
            work_mode: str | None = Query(None), week_from: int | None = Query(None, ge=1),
            week_to: int | None = Query(None, ge=1)) -> Filters:
    if week_from and week_to and week_from > week_to:
        raise HTTPException(422, "week_from must be <= week_to")
    return Filters(department or None, device_model or None, work_mode or None, week_from, week_to)


def scoped(store: DataStore, f: Filters) -> tuple[pd.DataFrame, pd.DataFrame]:
    dw = store.apply_filters(store.device_weeks, f.department, f.device_model, f.work_mode, f.week_from, f.week_to)
    tk = store.apply_filters(store.tickets_enriched, f.department, f.device_model, f.work_mode, f.week_from, f.week_to)
    return dw, tk


def store_dep() -> DataStore:
    return get_store()
