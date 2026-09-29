"""Telemetry thresholds and category taxonomy shared by every engine.

Values are carried over unchanged from the validated prototype so that the
correlation / diagnosis numbers stay reproducible.
"""
from __future__ import annotations

THRESHOLDS: dict[str, dict[str, float]] = {
    "boot": {"warn": 55, "critical": 85},
    "latency": {"warn": 90, "critical": 160},
    "packet_loss": {"warn": 1.5, "critical": 3.5},
    "hw_health": {"warn": 68, "critical": 52},  # lower is worse
    "hangs": {"warn": 3, "critical": 6},
    "battery": {"warn": 60, "critical": 45},  # lower is worse
    "disk": {"warn": 70, "critical": 55},  # lower is worse
}

CATEGORIES: list[str] = ["Performance", "Network", "Login/Auth", "Hardware", "Application Crash"]

ACTION_BY_CATEGORY: dict[str, str] = {
    "Performance": "Reimage device (fresh OS install + SSD optimization)",
    "Network": "Replace Wi-Fi adapter / push QoS network profile",
    "Login/Auth": "Push compliance policy update and re-enroll device",
    "Hardware": "Hardware swap — replace battery and disk",
    "Application Crash": "Reinstall and patch application suite",
}

# Human-readable telemetry signal catalogue: key -> (column, label, unit, higher_is_worse)
TELEMETRY_SIGNALS: dict[str, tuple[str, str, str, bool]] = {
    "boot": ("boot_duration_sec", "Boot duration", "s", True),
    "hangs": ("app_hang_count", "App hangs / week", "", True),
    "latency": ("network_latency_ms", "Network latency", "ms", True),
    "packet_loss": ("packet_loss_pct", "Packet loss", "%", True),
    "noncompliant": ("non_compliant", "Policy non-compliance", "", True),
    "hw_health": ("hardware_health_score", "Hardware health", "", False),
    "battery": ("battery_health_pct", "Battery health", "%", False),
    "disk": ("disk_health_pct", "Disk health", "%", False),
}

ISSUE_LABEL: dict[str, str] = {
    "Performance": "Boot / performance degradation",
    "Network": "Network quality",
    "Login/Auth": "Policy non-compliance",
    "Hardware": "Hardware health",
    "Application Crash": "Application hangs",
}

# Which telemetry signal primarily evidences each root-cause category
CATEGORY_PRIMARY_SIGNAL: dict[str, str] = {
    "Performance": "boot",
    "Network": "latency",
    "Login/Auth": "noncompliant",
    "Hardware": "hw_health",
    "Application Crash": "hangs",
}


def signal_state(key: str, value: float | bool) -> str:
    """Return ok / warn / critical for a telemetry reading."""
    if key == "noncompliant":
        return "critical" if value else "ok"
    if key == "compliant":
        return "ok" if value else "critical"
    th = THRESHOLDS[key]
    lower_is_worse = th["critical"] < th["warn"]
    v = float(value)
    if lower_is_worse:
        if v < th["critical"]:
            return "critical"
        return "warn" if v < th["warn"] else "ok"
    if v > th["critical"]:
        return "critical"
    return "warn" if v > th["warn"] else "ok"
