"""Map ServiceNow incident records onto the canonical ticket schema (app/data/schemas.py TABLES["tickets"]).

Only fields ServiceNow actually holds are mapped. Everything else (week, repeat history, department,
sentiment) is derived downstream by the normal ingestion path, exactly as for an uploaded file.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from ...engines.thresholds import CATEGORIES

# ServiceNow category / subcategory values -> platform categories; anything else is inferred from the text
SN_CATEGORY = {"network": "Network", "vpn": "Network", "wireless": "Network", "dns": "Network",
               "dhcp": "Network", "ip address": "Network", "hardware": "Hardware", "cpu": "Hardware",
               "disk": "Hardware", "memory": "Hardware", "keyboard": "Hardware", "monitor": "Hardware",
               "mouse": "Hardware", "password reset": "Login/Auth", "authentication": "Login/Auth",
               "access": "Login/Auth", "performance": "Performance", "crash": "Application Crash"}
_PLATFORM = {c.lower(): c for c in CATEGORIES}
OPEN_STATES = {"1", "2", "3"}  # New, In Progress, On Hold
RESOLVED_STATES = {"6", "7"}  # Resolved, Closed
CANCELED = "8"
COLUMNS = ["ticket_id", "device_id", "employee_name", "date", "channel", "category", "ticket_text",
           "repeat_contact", "resolution_time_hours", "outcome_status"]


@dataclass
class MapStats:
    fetched: int = 0
    mapped: int = 0
    skipped_no_text: int = 0
    skipped_no_device: int = 0
    skipped_canceled: int = 0
    watermark: str | None = None  # max sys_updated_on seen

    @property
    def skipped(self) -> int:
        return self.skipped_no_text + self.skipped_no_device + self.skipped_canceled

    def as_dict(self) -> dict:
        return {**asdict(self), "skipped": self.skipped}


def _v(rec: dict, key: str, display: bool = False) -> str:
    """Field value from a Table API record, with or without sysparm_display_value=all."""
    f = rec.get(key)
    if isinstance(f, dict):
        f = f.get("display_value" if display else "value")
        if display and not f:
            f = rec[key].get("value")
    return "" if f is None else str(f).strip()


def _int(s: str) -> int:
    try:
        return int(float(s))
    except ValueError:
        return 0


def _category(rec: dict) -> str | None:
    for key in ("subcategory", "category"):
        for val in (_v(rec, key).lower(), _v(rec, key, True).lower()):
            if val in _PLATFORM:
                return _PLATFORM[val]
            if val in SN_CATEGORY:
                return SN_CATEGORY[val]
    return None


def _status(rec: dict) -> str:
    if _int(_v(rec, "reopen_count")) > 0:
        return "Reopened"
    if _int(_v(rec, "escalation")) > 0:
        return "Escalated"
    state = _v(rec, "state")
    if state in RESOLVED_STATES:
        return "Resolved"
    if state in OPEN_STATES:
        return "Pending"
    label = _v(rec, "state", True)
    return label or "Pending"


def incidents_to_tickets(records: list[dict]) -> tuple[pd.DataFrame, MapStats]:
    st = MapStats(fetched=len(records))
    rows = []
    for rec in records:
        upd = _v(rec, "sys_updated_on")
        if upd and (st.watermark is None or upd > st.watermark):
            st.watermark = upd
        if _v(rec, "state") == CANCELED:
            st.skipped_canceled += 1
            continue
        short, desc = _v(rec, "short_description"), _v(rec, "description")
        text = short if not desc else desc if not short or desc.startswith(short) else f"{short}. {desc}"
        if not text:
            st.skipped_no_text += 1
            continue
        device = _v(rec, "cmdb_ci", True)
        if not device:
            st.skipped_no_device += 1
            continue
        opened = pd.to_datetime(_v(rec, "opened_at") or None, errors="coerce")
        resolved = pd.to_datetime(_v(rec, "resolved_at") or None, errors="coerce")
        hours = round((resolved - opened).total_seconds() / 3600, 2) if pd.notna(opened) and pd.notna(resolved) else None
        reopened = _int(_v(rec, "reopen_count")) > 0
        rows.append({
            "ticket_id": _v(rec, "number"), "device_id": device, "employee_name": _v(rec, "caller_id", True) or None,
            "date": opened.date().isoformat() if pd.notna(opened) else None,
            "channel": _v(rec, "contact_type", True).title() or None, "category": _category(rec),
            "ticket_text": text, "repeat_contact": True if reopened else None,
            "resolution_time_hours": hours if hours is None or hours >= 0 else None, "outcome_status": _status(rec),
        })
    st.mapped = len(rows)
    df = pd.DataFrame(rows, columns=COLUMNS)
    return df.drop_duplicates("ticket_id", keep="last").reset_index(drop=True), st
