"""Canonical dataset schemas.

Each column is (kind, required). Optional columns may be absent from an upload;
they are then derived (see ingest.py) or left empty, and every engine treats an
empty signal as "not measured" rather than as zero.
"""
from __future__ import annotations

S, I, F, B, D = "str", "int", "float", "bool", "date"

TABLES: dict[str, dict[str, tuple[str, bool]]] = {
    "devices": {
        "device_id": (S, True), "employee_name": (S, False), "department": (S, False),
        "work_mode": (S, False), "device_model": (S, False), "age_months": (I, False),
    },
    "telemetry": {
        "device_id": (S, True), "week": (I, True), "week_start": (D, False),
        "boot_duration_sec": (F, False), "app_hang_count": (F, False), "network_latency_ms": (F, False),
        "packet_loss_pct": (F, False), "policy_compliant": (B, False), "hardware_health_score": (F, False),
        "battery_health_pct": (F, False), "disk_health_pct": (F, False),
    },
    "tickets": {
        "ticket_id": (S, True), "device_id": (S, True), "employee_name": (S, False), "department": (S, False),
        "week": (I, True), "date": (D, False), "channel": (S, False), "category": (S, False),
        "repeat_contact": (B, False), "repeat_number": (I, False), "ticket_text": (S, True),
        "resolution_time_hours": (F, False), "outcome_status": (S, False),
    },
    "remediations": {
        "remediation_id": (S, True), "device_id": (S, True), "employee_name": (S, False), "department": (S, False),
        "problem_type": (S, False), "root_cause_category": (S, True), "week_of_remediation": (I, True),
        "date": (D, False), "action_taken": (S, True),
        "pre_boot_duration_sec": (F, False), "post_boot_duration_sec": (F, False),
        "pre_network_latency_ms": (F, False), "post_network_latency_ms": (F, False),
        "pre_hardware_health_score": (F, False), "post_hardware_health_score": (F, False),
        "pre_app_hang_count": (F, False), "post_app_hang_count": (F, False),
        "pre_ticket_count": (I, False), "post_ticket_count": (I, False),
        "pre_ticket_rate_per_week": (F, False), "post_ticket_rate_per_week": (F, False),
        "pre_frustration_score": (F, False), "post_frustration_score": (F, False),
        "pre_repeat_contact_rate_pct": (F, False), "post_repeat_contact_rate_pct": (F, False),
    },
}

# Backwards-compatible view: table -> {column: kind}
SCHEMAS: dict[str, dict[str, str]] = {t: {c: k for c, (k, _) in cols.items()} for t, cols in TABLES.items()}
REQUIRED: dict[str, list[str]] = {t: [c for c, (_, r) in cols.items() if r] for t, cols in TABLES.items()}

PRIMARY_KEYS = {"devices": ["device_id"], "telemetry": ["device_id", "week"], "tickets": ["ticket_id"],
                "remediations": ["remediation_id"]}

TELEMETRY_SIGNAL_COLUMNS = ["boot_duration_sec", "app_hang_count", "network_latency_ms", "packet_loss_pct",
                            "policy_compliant", "hardware_health_score", "battery_health_pct", "disk_health_pct"]

REMEDIATION_METRIC_COLUMNS = [c for c in TABLES["remediations"] if c.startswith(("pre_", "post_"))]

# Sheet / file-name aliases used to identify a table
SHEET_ALIASES = {
    "devices": ["devices", "device", "assets", "endpoints", "cmdb"],
    "telemetry": ["telemetry", "weekly telemetry", "device telemetry", "endpoint telemetry", "dex telemetry"],
    "tickets": ["tickets", "service-desk tickets", "service desk tickets", "ticket", "incidents", "interactions", "cases"],
    "remediations": ["remediations", "remediation", "remediation before/after", "fixes", "changes"],
}

# Accepted alternative column names (after normalisation to snake_case)
COLUMN_ALIASES: dict[str, dict[str, list[str]]] = {
    "_common": {
        "device_id": ["device", "deviceid", "device_name", "hostname", "computer_name", "asset_id", "asset_tag",
                      "endpoint_id", "machine_name", "configuration_item", "ci"],
        "employee_name": ["employee", "user", "user_name", "username", "caller", "caller_id", "requested_for", "name"],
        "department": ["dept", "business_unit", "bu", "org", "organization", "cost_center"],
    },
    "devices": {
        "work_mode": ["workmode", "location_type", "work_location", "working_mode"],
        "device_model": ["model", "hardware_model", "make_model"],
        "age_months": ["age", "device_age_months", "age_in_months"],
    },
    "telemetry": {
        "week": ["week_number", "week_no", "wk"],
        "week_start": ["date", "timestamp", "collected_at", "event_date", "day", "reading_date", "week_start_date"],
        "boot_duration_sec": ["boot_time", "boot_time_sec", "boot_duration", "boot_seconds", "startup_time_sec"],
        "app_hang_count": ["app_hangs", "application_hangs", "hang_count", "hangs", "app_crashes", "crash_count"],
        "network_latency_ms": ["latency", "latency_ms", "network_latency", "rtt_ms", "ping_ms"],
        "packet_loss_pct": ["packet_loss", "packet_loss_percent", "loss_pct"],
        "policy_compliant": ["compliant", "compliance", "compliance_status", "is_compliant", "policy_state"],
        "hardware_health_score": ["hardware_health", "hw_health", "hardware_score", "device_health_score"],
        "battery_health_pct": ["battery_health", "battery_pct", "battery"],
        "disk_health_pct": ["disk_health", "disk_pct", "ssd_health", "storage_health"],
    },
    "tickets": {
        "ticket_id": ["number", "ticket", "ticket_number", "incident_id", "incident_number", "case_id", "id"],
        "date": ["opened_at", "created", "created_at", "opened", "sys_created_on", "open_date", "reported_at"],
        "channel": ["contact_type", "source", "origin"],
        "category": ["subcategory", "issue_category", "problem_category"],
        "repeat_contact": ["is_repeat", "repeat"],
        "repeat_number": ["contact_number", "repeat_count_number"],
        "ticket_text": ["text", "description", "short_description", "summary", "comments", "notes",
                        "transcript", "message", "call_notes", "chat_text", "subject"],
        "resolution_time_hours": ["resolution_hours", "time_to_resolve_hours", "resolve_time_hours", "ttr_hours"],
        "outcome_status": ["status", "state", "resolution_status", "outcome"],
        "week": ["week_number", "week_no", "wk"],
    },
    "remediations": {
        "remediation_id": ["change_id", "fix_id", "remediation", "id"],
        "root_cause_category": ["root_cause", "category", "cause"],
        "week_of_remediation": ["week", "remediation_week", "fix_week"],
        "date": ["remediation_date", "fixed_at", "implemented_at", "closed_at"],
        "action_taken": ["action", "fix", "remediation_action", "resolution"],
    },
}
