"""SQLite persistence (SQLAlchemy Core). Swap DEX_DATABASE_URL for Postgres in production."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from functools import lru_cache

import pandas as pd
from sqlalchemy import (Column, DateTime, Float, Integer, MetaData, String, Table, Text,
                        create_engine, insert, inspect, select)
from sqlalchemy.engine import Engine

from .config import get_settings

log = logging.getLogger(__name__)
metadata = MetaData()

dataset_versions = Table(
    "dataset_versions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("loaded_at", DateTime(timezone=True), nullable=False),
    Column("source", String(255), nullable=False),
    Column("rows_json", Text, nullable=False),
)

diagnosis_log = Table(
    "diagnosis_log", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("device_id", String(32)),
    Column("ticket_text", Text),
    Column("top_cause", String(64)),
    Column("confidence", Float),
    Column("frustration_score", Float),
    Column("result_json", Text),
)

copilot_log = Table(
    "copilot_log", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("provider", String(32)),
    Column("device_id", String(32)),
    Column("question", Text),
    Column("response_json", Text),
    Column("latency_ms", Integer),
)

app_settings = Table(
    "app_settings", metadata,
    Column("key", String(64), primary_key=True),
    Column("value", Text, nullable=False),
)

# ---- software remediation (app/remediation)
remediation_emails = Table(
    "remediation_emails", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("message_id", String(255), nullable=False, unique=True),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("sender", String(255), nullable=False),
    Column("subject", Text, nullable=False),
    Column("body", Text, nullable=False),
    Column("attachments_json", Text, nullable=False, default="[]"),
    Column("source", String(16), nullable=False),  # seed | submitted | imap
    Column("status", String(16), nullable=False),  # pending | processed | rejected
    Column("note", Text),
)

removed_installations = Table(
    "removed_installations", metadata,
    Column("installation_id", String(64), primary_key=True),
    Column("removed_at", DateTime(timezone=True), nullable=False),
    Column("run_id", String(32), nullable=False),
)

remediation_runs = Table(
    "remediation_runs", metadata,
    Column("run_id", String(32), primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("message_id", String(255)),
    Column("software_name", String(255), nullable=False),
    Column("software_version", String(64), nullable=False),
    Column("dry_run", Integer, nullable=False),
    Column("status", String(32), nullable=False),
    Column("approved_by", String(255)),
    Column("result_json", Text, nullable=False),
)

runbook_applications = Table(
    "runbook_applications", metadata,
    Column("device_id", String(32), primary_key=True),
    Column("runbook_id", String(32), primary_key=True),
    Column("run_id", String(32), nullable=False),
    Column("applied_at", DateTime(timezone=True), nullable=False),
)

remediation_audit = Table(
    "remediation_audit", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("event", String(64), nullable=False),
    Column("run_id", String(32)),
    Column("actor", String(255)),
    Column("payload_json", Text, nullable=False),
    Column("prev_hash", String(64), nullable=False),
    Column("hash", String(64), nullable=False),
)

# ---- ServiceNow incident sync (app/integrations/servicenow); the watermark must survive restarts
servicenow_sync_runs = Table(
    "servicenow_sync_runs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
    Column("trigger", String(16), nullable=False),  # manual | scheduled
    Column("mode", String(8), nullable=False),  # live | mock
    Column("instance", String(255)),
    Column("status", String(16), nullable=False),  # running | succeeded | no_changes | failed | skipped
    Column("fetched", Integer, nullable=False, default=0),
    Column("created", Integer, nullable=False, default=0),
    Column("updated", Integer, nullable=False, default=0),
    Column("skipped", Integer, nullable=False, default=0),
    Column("unmatched_devices", Integer, nullable=False, default=0),
    Column("since", String(32)),  # watermark the fetch started from
    Column("watermark", String(32)),  # max sys_updated_on fetched; advances the next sync on success
    Column("job_id", String(32)),
    Column("error", Text),
)

RAW_TABLES = ["devices", "telemetry", "tickets", "remediations"]


@lru_cache
def get_engine() -> Engine:
    url = get_settings().database_url
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    engine = create_engine(url, future=True, **kwargs)
    if url.startswith("sqlite"):
        from sqlalchemy import event

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):  # WAL: faster bulk loads, readers never blocked by the writer
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()
    metadata.create_all(engine)
    return engine


def now() -> datetime:
    return datetime.now(timezone.utc)


def has_dataset() -> bool:
    names = set(inspect(get_engine()).get_table_names())
    return all(f"raw_{t}" in names for t in RAW_TABLES)


def save_dataset(frames: dict[str, pd.DataFrame], source: str) -> None:
    eng = get_engine()
    with eng.begin() as conn:
        for t in RAW_TABLES:
            frames[t].to_sql(f"raw_{t}", conn, if_exists="replace", index=False, chunksize=50_000)
        conn.execute(insert(dataset_versions).values(
            loaded_at=now(), source=source, rows_json=json.dumps({k: len(v) for k, v in frames.items()})))


def read_dataset() -> dict[str, pd.DataFrame]:
    eng = get_engine()
    with eng.connect() as conn:
        frames = {t: pd.read_sql_table(f"raw_{t}", conn) for t in RAW_TABLES}
    frames["telemetry"]["policy_compliant"] = frames["telemetry"]["policy_compliant"].astype(bool)
    frames["tickets"]["repeat_contact"] = frames["tickets"]["repeat_contact"].astype(bool)
    from .data.schemas import TABLES
    for t, cols in TABLES.items():  # columns that were entirely empty may not round-trip
        for c in cols:
            if c not in frames[t]:
                frames[t][c] = None
    return frames


def latest_dataset_version() -> dict | None:
    with get_engine().connect() as conn:
        row = conn.execute(select(dataset_versions).order_by(dataset_versions.c.id.desc()).limit(1)).first()
    if not row:
        return None
    return {"id": row.id, "loaded_at": row.loaded_at.isoformat() if row.loaded_at else None,
            "source": row.source, "rows": json.loads(row.rows_json)}


def log_diagnosis(device_id: str, text: str, result: dict) -> None:
    top = result["root_causes"][0] if result.get("root_causes") else {}
    with get_engine().begin() as conn:
        conn.execute(insert(diagnosis_log).values(
            created_at=now(), device_id=device_id, ticket_text=text, top_cause=top.get("category"),
            confidence=top.get("confidence"), frustration_score=result.get("experience", {}).get("frustration_score"),
            result_json=json.dumps(result, default=str)))


def log_copilot(provider: str, device_id: str | None, question: str, response: dict, latency_ms: int) -> None:
    with get_engine().begin() as conn:
        conn.execute(insert(copilot_log).values(
            created_at=now(), provider=provider, device_id=device_id, question=question,
            response_json=json.dumps(response, default=str), latency_ms=latency_ms))


def recent_diagnoses(limit: int = 20) -> list[dict]:
    with get_engine().connect() as conn:
        rows = conn.execute(select(diagnosis_log).order_by(diagnosis_log.c.id.desc()).limit(limit)).all()
    return [{"id": r.id, "created_at": r.created_at.isoformat(), "device_id": r.device_id,
             "ticket_text": r.ticket_text, "top_cause": r.top_cause, "confidence": r.confidence,
             "frustration_score": r.frustration_score} for r in rows]


def get_setting_overrides() -> dict:
    with get_engine().connect() as conn:
        rows = conn.execute(select(app_settings)).all()
    return {r.key: json.loads(r.value) for r in rows}


def delete_setting_overrides(keys: list[str]) -> None:
    if keys:
        with get_engine().begin() as conn:
            conn.execute(app_settings.delete().where(app_settings.c.key.in_(keys)))


def put_setting_overrides(values: dict) -> None:
    with get_engine().begin() as conn:
        for k, v in values.items():
            conn.execute(app_settings.delete().where(app_settings.c.key == k))
            conn.execute(insert(app_settings).values(key=k, value=json.dumps(v)))
