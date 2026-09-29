"""Module 8 — Upload Dataset API: submit new data for analysis, track the job, inspect the active dataset."""
from __future__ import annotations

import io
import tempfile
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from .. import db
from ..config import get_settings
from ..copilot.tools import effective_config
from ..data import store as store_mod
from ..data.jobs import JobBusyError, STAGES, manager, max_upload_bytes, snapshot
from ..data.schemas import COLUMN_ALIASES, TABLES, TELEMETRY_SIGNAL_COLUMNS
from .deps import CleanRoute

router = APIRouter(route_class=CleanRoute)

ALLOWED_EXT = {".xlsx", ".csv"}
CHUNK = 1024 * 1024

DERIVABLE = {("telemetry", "week"): "or a reading date", ("tickets", "week"): "or a ticket date",
             ("remediations", "week_of_remediation"): "or a remediation date"}

TABLE_HELP = {
    "telemetry": "Endpoint telemetry — one row per device per week (daily or event-level rows are rolled up). "
                 "Needs device_id and a week number or reading date, plus at least two signals.",
    "tickets": "Service-desk calls, chats and portal tickets. Needs ticket_id, device_id, ticket text and a week "
               "or date; channel, category, repeat contacts and status are derived when missing.",
    "devices": "Optional. Employee, department, work mode, model, age. Derived from telemetry/tickets when missing.",
    "remediations": "Optional. Fixes applied: device_id, week (or date), root cause and action. Before/after "
                    "metrics are calculated from the data when not supplied.",
}


async def _save(upload: UploadFile, workdir: Path, limit: int) -> tuple[str, Path, int]:
    name = Path(upload.filename or "upload").name
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(415, f"{name}: only .xlsx and .csv files are accepted")
    dest = workdir / f"{len(list(workdir.iterdir()))}_{name}"
    size, head = 0, b""
    with open(dest, "wb") as out:
        while chunk := await upload.read(CHUNK):
            if not head:
                head = chunk[:8]
            size += len(chunk)
            if size > limit:
                raise HTTPException(413, f"{name} exceeds the {limit // (1024 * 1024)} MB limit")
            out.write(chunk)
    if size == 0:
        raise HTTPException(422, f"{name} is empty")
    if ext == ".xlsx" and not head.startswith(b"PK"):
        raise HTTPException(415, f"{name} is not a valid .xlsx workbook")
    if ext == ".csv" and (head.startswith(b"PK") or b"\x00" in head):
        raise HTTPException(415, f"{name} looks like a binary file, not CSV text")
    return name, dest, size


@router.post("/datasets/analyze", status_code=202, summary="Module 8 — upload a dataset and submit it for analysis")
async def analyze(files: list[UploadFile] = File(..., description=".xlsx workbook and/or .csv files, 200 MB each"),
                  mode: str = Form("replace", description="replace | append")):
    if mode not in ("replace", "append"):
        raise HTTPException(422, "mode must be 'replace' or 'append'")
    s = get_settings()
    if not files:
        raise HTTPException(422, "attach at least one file")
    if len(files) > s.max_upload_files:
        raise HTTPException(422, f"at most {s.max_upload_files} files per upload")
    if manager.running():
        raise HTTPException(409, "another dataset is being analysed — wait for it to finish")
    workdir = Path(tempfile.mkdtemp(prefix="dex_upload_"))
    try:
        saved = [await _save(f, workdir, max_upload_bytes()) for f in files]
        job = manager.submit(saved, mode, workdir)
    except HTTPException:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    except JobBusyError as e:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(409, str(e))
    return job.as_dict()


@router.get("/datasets/jobs/{job_id}", summary="Analysis job status")
def job_status(job_id: str):
    job = manager.get(job_id)
    if job is None:
        raise HTTPException(404, f"job {job_id} not found")
    return job.as_dict()


@router.get("/datasets/jobs", summary="Recent analysis jobs")
def jobs(limit: int = 10):
    return {"items": manager.recent(limit), "running": manager.running() is not None}


@router.post("/datasets/restore-sample", status_code=202, summary="Re-analyse the bundled simulated dataset")
def restore_sample():
    seed = Path(get_settings().seed_dataset)
    try:
        job = manager.submit([(seed.name, seed, seed.stat().st_size)], "replace", None)
    except JobBusyError as e:
        raise HTTPException(409, str(e))
    return job.as_dict()


@router.get("/datasets/active", summary="Active dataset: version, coverage, headline metrics, history")
def active():
    st = store_mod.get_store()
    with db.get_engine().connect() as conn:
        rows = conn.execute(db.dataset_versions.select().order_by(db.dataset_versions.c.id.desc()).limit(10)).all()
    import json
    history = [{"id": r.id, "loaded_at": r.loaded_at.isoformat() if r.loaded_at else None, "source": r.source,
                "rows": json.loads(r.rows_json)} for r in rows]
    signals = [c for c in TELEMETRY_SIGNAL_COLUMNS if c in st.telemetry and st.telemetry[c].notna().any()]
    return {"dataset": db.latest_dataset_version(), "history": history,
            "coverage": {"weeks": st.weeks[:1] + st.weeks[-1:], "week_dates": [st.week_dates.get(st.weeks[0]),
                                                                          st.week_dates.get(st.weeks[-1])] if st.weeks else [],
                         "departments": int(st.devices["department"].nunique()),
                         "signals_present": signals,
                         "signals_missing": [c for c in TELEMETRY_SIGNAL_COLUMNS if c not in signals]},
            "metrics": snapshot(st, effective_config()),
            "limits": {"max_file_mb": get_settings().max_upload_mb, "max_files": get_settings().max_upload_files,
                       "formats": sorted(ALLOWED_EXT), "storage_mode": get_settings().storage_mode},
            "stages": [{"key": k, "label": lab} for k, lab in STAGES]}


@router.get("/datasets/schema", summary="Column guide for uploads")
def schema():
    out = []
    for t, cols in TABLES.items():
        aliases = {**{k: v for k, v in COLUMN_ALIASES["_common"].items()}, **COLUMN_ALIASES.get(t, {})}
        out.append({"table": t, "help": TABLE_HELP[t],
                    "columns": [{"name": c, "type": k, "required": r, "aliases": aliases.get(c, [])[:6],
                                 "note": DERIVABLE.get((t, c))} for c, (k, r) in cols.items()]})
    return {"tables": out}


@router.get("/datasets/templates/{table}.csv", summary="CSV template with example rows")
def template(table: str):
    if table not in TABLES:
        raise HTTPException(404, f"unknown table {table}")
    st = store_mod.get_store()
    src = {"devices": st.devices, "telemetry": st.telemetry, "tickets": st.tickets, "remediations": st.remediations}[table]
    cols = list(TABLES[table])
    sample = src[[c for c in cols if c in src]].head(3) if len(src) else pd.DataFrame(columns=cols)
    buf = io.StringIO()
    sample.reindex(columns=cols).to_csv(buf, index=False)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=dex_{table}_template.csv"})


@router.get("/datasets/sample.xlsx", summary="Download the bundled simulated dataset")
def sample_workbook():
    seed = Path(get_settings().seed_dataset)
    return FileResponse(seed, filename=seed.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
