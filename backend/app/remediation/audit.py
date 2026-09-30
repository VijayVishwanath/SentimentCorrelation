"""Tamper-evident audit trail for software remediation.

Rows are append-only and hash-chained: each row stores sha256(prev_hash + canonical
JSON of the row), so editing or deleting any earlier row breaks verify_chain().
"""
from __future__ import annotations

import hashlib
import json
import threading

from sqlalchemy import insert, select

from .. import db

T = db.remediation_audit
GENESIS = "0" * 64
_lock = threading.Lock()


def _digest(prev: str, created_at: str, event: str, run_id: str | None, actor: str | None, payload_json: str) -> str:
    body = json.dumps({"created_at": created_at, "event": event, "run_id": run_id, "actor": actor,
                       "payload": payload_json}, sort_keys=True)
    return hashlib.sha256((prev + body).encode()).hexdigest()


def record(event: str, payload: dict, run_id: str | None = None, actor: str | None = None) -> str:
    payload_json = json.dumps(payload, sort_keys=True, default=str)
    with _lock, db.get_engine().begin() as conn:
        last = conn.execute(select(T.c.hash).order_by(T.c.id.desc()).limit(1)).scalar()
        prev = last or GENESIS
        created = db.now()
        h = _digest(prev, created.isoformat(), event, run_id, actor, payload_json)
        conn.execute(insert(T).values(created_at=created, event=event, run_id=run_id, actor=actor,
                                      payload_json=payload_json, prev_hash=prev, hash=h))
    return h


def trail(run_id: str | None = None, event: str | None = None, device_id: str | None = None,
          limit: int = 100) -> list[dict]:
    q = select(T).order_by(T.c.id.desc()).limit(limit)
    if run_id:
        q = q.where(T.c.run_id == run_id)
    if event:
        q = q.where(T.c.event == event)
    if device_id:
        q = q.where(T.c.payload_json.contains(f'"device_id": "{device_id}"'))
    with db.get_engine().connect() as conn:
        rows = conn.execute(q).all()
    return [{"id": r.id, "created_at": r.created_at.isoformat(), "event": r.event, "run_id": r.run_id,
             "actor": r.actor, "payload": json.loads(r.payload_json), "hash": r.hash} for r in rows]


def verify_chain() -> dict:
    prev, n = GENESIS, 0
    # fetch everything first: returning mid-iteration would leave the SQLite cursor open, pinning the
    # pooled connection to a stale WAL snapshot for its next reader
    with db.get_engine().connect() as conn:
        rows = conn.execute(select(T).order_by(T.c.id)).all()
    for r in rows:
        created = r.created_at.isoformat() if r.created_at.tzinfo else r.created_at.replace(
            tzinfo=db.now().tzinfo).isoformat()
        if r.prev_hash != prev or _digest(prev, created, r.event, r.run_id, r.actor, r.payload_json) != r.hash:
            return {"intact": False, "entries_checked": n, "first_broken_id": r.id}
        prev, n = r.hash, n + 1
    return {"intact": True, "entries_checked": n, "head_hash": prev}
