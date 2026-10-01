"""Module 8 — dataset analysis jobs.

An upload is analysed in a background thread so large files never hit an HTTP
timeout. Each job walks through visible stages, builds the complete analytical
store off to the side, and only then swaps it in atomically — a failed upload
never disturbs the live dataset. The result compares headline metrics before
and after so the user sees exactly what the new data changed.
"""
from __future__ import annotations

import logging
import shutil
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .. import db
from ..config import get_settings
from .loader import DatasetValidationError, read_upload_files, validate_frames
from . import store as store_mod

log = logging.getLogger(__name__)

STAGES = [
    ("received", "Upload received"),
    ("read", "Reading files"),
    ("validate", "Validating & normalising"),
    ("sentiment", "Scoring sentiment & frustration"),
    ("correlate", "Correlating experience with telemetry"),
    ("outcomes", "Diagnosis, outcomes & DEX Score"),
    ("publish", "Publishing to all dashboards"),
    ("done", "Analysis complete"),
]
STAGE_PROGRESS = {"received": 5, "read": 15, "validate": 30, "sentiment": 50, "correlate": 65,
                  "outcomes": 80, "publish": 92, "done": 100}


class JobBusyError(RuntimeError):
    pass


@dataclass
class Job:
    id: str
    mode: str
    files: list[dict]
    state: str = "queued"  # queued | running | succeeded | failed
    stage: str = "received"
    progress: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: str | None = None
    finished_at: str | None = None
    duration_sec: float | None = None
    log: list[dict] = field(default_factory=list)
    error: str | None = None
    issues: list[str] = field(default_factory=list)
    result: dict | None = None
    source: str | None = None  # dataset-history label; defaults to the file names

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d["stages"] = [{"key": k, "label": lab, "progress": STAGE_PROGRESS[k]} for k, lab in STAGES]
        return d


def snapshot(store, cfg: dict) -> dict:
    """Headline metrics of a store — used for the before/after comparison."""
    from ..engines import correlation as corr
    from ..engines import dex_score, outcomes
    dw, tk = store.device_weeks, store.tickets_enriched
    comp = dex_score.compute_components(dw, tk, cfg["resolution_sla_hours"])
    head = corr.headline_correlation(tk, dw) if len(tk) >= 3 else {"score": None, "strength": "n/a"}
    lift = corr.lift_analysis(tk, dw, "frustration_score") if len(tk) else {}
    ranking = corr.impact_ranking(tk, dw) if len(tk) else []
    oc = outcomes.outcome_report(store, cfg)
    return {
        "devices": int(len(store.devices)), "tickets": int(len(tk)), "device_weeks": int(len(dw)),
        "weeks": [int(min(store.weeks)), int(max(store.weeks))] if store.weeks else None,
        "remediations": int(len(store.remediations)),
        "dex_score": comp.get("dex_score"), "band": comp.get("band"),
        "eei": comp.get("components", {}).get("eei"), "dhs": comp.get("components", {}).get("dhs"),
        "correlation_score": head["score"], "correlation_strength": head["strength"],
        "avg_frustration": comp.get("supporting", {}).get("avg_frustration"),
        "repeat_contact_rate_pct": comp.get("supporting", {}).get("repeat_contact_rate_pct"),
        "top_driver": ranking[0]["label"] if ranking and ranking[0]["impact_score"] > 0 else None,
        "lifts": {k: (None if v.get("infinite") else v.get("lift")) for k, v in lift.items()},
        "policy_lift_infinite": bool(lift.get("policy", {}).get("infinite")),
        "experience_recovery_pct": (oc.get("dex") or {}).get("experience_recovery_pct"),
        "annual_savings_usd": (oc.get("business_impact") or {}).get("total_annual_savings_usd"),
    }


class JobManager:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    def running(self) -> Job | None:
        with self._lock:
            return next((j for j in self._jobs.values() if j.state in ("queued", "running")), None)

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def recent(self, limit: int = 10) -> list[dict]:
        return [self._jobs[i].as_dict() for i in reversed(self._order[-limit:])]

    def submit(self, files: list[tuple[str, Path, int]], mode: str, workdir: Path | None,
               background: bool = True, source: str | None = None,
               on_done: Callable[[Job], None] | None = None) -> Job:
        with self._lock:
            if any(j.state in ("queued", "running") for j in self._jobs.values()):
                raise JobBusyError("another dataset is being analysed — wait for it to finish")
            job = Job(id=uuid.uuid4().hex[:12], mode=mode,
                      files=[{"name": n, "size_bytes": s} for n, _, s in files], source=source)
            self._jobs[job.id] = job
            self._order.append(job.id)
            if len(self._order) > 50:
                old = self._order.pop(0)
                self._jobs.pop(old, None)
        if background:
            threading.Thread(target=self._run, args=(job, files, workdir, on_done), name=f"dataset-{job.id}", daemon=True).start()
        else:
            self._run(job, files, workdir, on_done)
        return job

    # ------------------------------------------------------------------ worker
    def _stage(self, job: Job, key: str, msg: str | None = None) -> None:
        job.stage, job.progress = key, STAGE_PROGRESS[key]
        job.log.append({"at": datetime.now(timezone.utc).isoformat(), "stage": key,
                        "message": msg or dict(STAGES)[key]})
        log.info("dataset job %s: %s %s", job.id, key, msg or "")

    def _run(self, job: Job, files: list[tuple[str, Path, int]], workdir: Path | None,
             on_done: Callable[[Job], None] | None = None) -> None:
        from ..api.routes_analytics import clear_cache
        from ..copilot.tools import effective_config
        t0 = time.perf_counter()
        job.state, job.started_at = "running", datetime.now(timezone.utc).isoformat()
        try:
            cfg = effective_config()
            self._stage(job, "received", f"{len(files)} file(s), {sum(s for *_, s in files) / 1e6:.1f} MB, mode = {job.mode}")
            self._stage(job, "read")
            raw = read_upload_files([(n, p) for n, p, _ in files])
            found = [f"{f['file']}{' · ' + str(f['sheet']) if f.get('sheet') else ''} → {f['table'] or 'not recognised'}"
                     for f in raw.get("_files", [])]
            job.log[-1]["message"] = "Detected: " + "; ".join(found)

            self._stage(job, "validate")
            base = db.read_dataset() if job.mode == "append" and db.has_dataset() else None
            frames, report = validate_frames(raw, job.mode, base)
            job.log[-1]["message"] = ("Rows: " + ", ".join(f"{v:,} {k}" for k, v in report.rows.items())
                                      + (f" · {len(report.warnings)} warning(s)" if report.warnings else ""))

            before = None
            try:
                before = snapshot(store_mod.get_store(), cfg)
            except Exception:  # no current dataset
                log.exception("could not snapshot current dataset")

            self._stage(job, "sentiment", f"Scoring {report.rows['tickets']:,} tickets")
            new_store = store_mod.build_store(frames)  # sentiment, telemetry join, device-week facts

            self._stage(job, "correlate", f"Correlating {len(new_store.device_weeks):,} device-weeks")
            after = snapshot(new_store, cfg)

            self._stage(job, "outcomes", f"{len(new_store.remediations):,} remediation case(s)"
                        + (f", {new_store.remediation_metrics_derived} with before/after derived from the data"
                           if new_store.remediation_metrics_derived else ""))
            if new_store.remediation_metrics_derived:
                report.derived.append(f"remediations: before/after metrics derived from telemetry and tickets for "
                                      f"{new_store.remediation_metrics_derived} case(s)")

            self._stage(job, "publish", "Swapping in the new dataset and refreshing every module")
            source = (job.source or ", ".join(f["name"] for f in job.files))[:250]
            store_mod.replace_store(frames, source=source, built=new_store)
            clear_cache()
            from ..api.warmup import warm_in_background  # lazy: the api layer imports this module
            warm_in_background("post-upload-warmup")

            job.result = {"rows": report.rows, "report": report.as_dict(), "before": before, "after": after,
                          "dataset": db.latest_dataset_version()}
            self._stage(job, "done")
            job.state = "succeeded"
        except DatasetValidationError as e:
            job.state, job.error, job.issues = "failed", "The dataset did not pass validation", e.issues
            job.log.append({"at": datetime.now(timezone.utc).isoformat(), "stage": job.stage, "message": str(e)})
        except Exception as e:  # unexpected failure: the live dataset is untouched
            log.error("dataset job %s failed: %s\n%s", job.id, e, traceback.format_exc())
            job.state, job.error = "failed", f"{type(e).__name__}: {e}"
        finally:
            job.finished_at = datetime.now(timezone.utc).isoformat()
            job.duration_sec = round(time.perf_counter() - t0, 2)
            if workdir:
                shutil.rmtree(workdir, ignore_errors=True)
            if on_done:
                try:
                    on_done(job)
                except Exception:
                    log.exception("dataset job %s: completion callback failed", job.id)


manager = JobManager()


def max_upload_bytes() -> int:
    return int(get_settings().max_upload_mb) * 1024 * 1024
