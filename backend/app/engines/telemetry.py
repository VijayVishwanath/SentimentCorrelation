"""Module 2 — Telemetry Intelligence.

Device Health Score (requirements formula) and Telemetry Severity Score
(per-category severity vs fixed warn/critical thresholds, from the prototype).

Signals the simulated dataset does not carry directly are derived, and are
labelled as such wherever they are surfaced:
  * crash_events  = Application-Crash tickets logged for that device-week
  * vpn_failures  = device-weeks with packet loss at/over the warn threshold
"""
from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd

from .thresholds import CATEGORIES, THRESHOLDS, signal_state

SEVERITY_CAP = 1.3


def rule_risk(severity, burden):
    """The rule-based at-risk score: 60% telemetry severity + 40% experience burden (scalars or Series).

    Used by the Copilot's at-risk tool, the device fleet API, and as the baseline the forecaster must beat.
    """
    return severity * 0.6 + burden * 0.4


def _ramp(v, key: str):
    """Distance past the warn threshold, 0 at warn .. 1 at critical .. capped; unmeasured (NaN) -> 0."""
    th = THRESHOLDS[key]
    lower_is_worse = th["critical"] < th["warn"]
    v = np.asarray(v, dtype=float)
    num = (th["warn"] - v) if lower_is_worse else (v - th["warn"])
    return np.nan_to_num(np.clip(num / abs(th["critical"] - th["warn"]), 0, SEVERITY_CAP), nan=0.0)


def _noncompliant(v):
    """1.0 when explicitly non-compliant; unknown counts as compliant."""
    s = v if isinstance(v, pd.Series) else pd.Series(v if isinstance(v, (np.ndarray, list)) else [v])
    return s.astype(object).map({False: 1.0}).fillna(0.0).astype(float).to_numpy()


def category_severity_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Vectorised severity per root-cause category for every row of a telemetry frame."""
    out = pd.DataFrame(index=df.index)
    out["Performance"] = _ramp(df["boot_duration_sec"], "boot")
    out["Network"] = np.maximum(_ramp(df["network_latency_ms"], "latency"), _ramp(df["packet_loss_pct"], "packet_loss"))
    out["Login/Auth"] = _noncompliant(df["policy_compliant"])
    out["Hardware"] = _ramp(df["hardware_health_score"], "hw_health")
    out["Application Crash"] = _ramp(df["app_hang_count"], "hangs")
    return out[CATEGORIES]


def telemetry_severity_frame(sev: pd.DataFrame) -> pd.Series:
    """0-100 composite: 60% worst category, 40% mean of all categories."""
    n = sev / SEVERITY_CAP
    return (100 * (0.6 * n.max(axis=1) + 0.4 * n.mean(axis=1))).round(1)


def device_health_frame(df: pd.DataFrame, crashes=0) -> pd.Series:
    """Vectorised Device Health Score. Unmeasured signals do not penalise; missing hardware health
    means the score is not blended with it."""
    score = (100.0 - 0.1 * df["boot_duration_sec"].astype(float).fillna(0) - 3 * df["app_hang_count"].astype(float).fillna(0)
             - 4 * (crashes if np.isscalar(crashes) else pd.Series(crashes, index=df.index).fillna(0))
             - 0.05 * df["network_latency_ms"].astype(float).fillna(0))
    hw = df["hardware_health_score"].astype(float).where(df["hardware_health_score"].notna(), score)
    return (score * 0.8 + hw * 0.2).clip(0, 100).round(1)


def category_severity(row: Mapping) -> dict[str, float]:
    """Severity per root-cause category, 0 (fine) .. 1 (at critical) .. 1.3 (cap)."""
    return {
        "Performance": float(_ramp(row["boot_duration_sec"], "boot")),
        "Network": float(max(_ramp(row["network_latency_ms"], "latency"), _ramp(row["packet_loss_pct"], "packet_loss"))),
        "Login/Auth": float(_noncompliant(row["policy_compliant"])[0]),
        "Hardware": float(_ramp(row["hardware_health_score"], "hw_health")),
        "Application Crash": float(_ramp(row["app_hang_count"], "hangs")),
    }


def telemetry_severity_score(row: Mapping) -> float:
    """0-100 composite: 60% worst category, 40% mean of all categories."""
    vals = [v / SEVERITY_CAP for v in category_severity(row).values()]
    return round(100 * (0.6 * max(vals) + 0.4 * sum(vals) / len(vals)), 1)


def _nz(v) -> float:
    return 0.0 if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)


def device_health(boot_duration: float, app_hangs: float, crashes: float,
                  network_latency: float, hardware_score: float | None) -> float:
    """Device Health Score (0-100) — formula from the requirements spec."""
    score = 100.0
    score -= _nz(boot_duration) * 0.1
    score -= _nz(app_hangs) * 3
    score -= _nz(crashes) * 4
    score -= _nz(network_latency) * 0.05
    hw = score if hardware_score is None or (isinstance(hardware_score, float) and np.isnan(hardware_score)) else hardware_score
    score = (score * 0.8) + (hw * 0.2)
    return round(max(0.0, min(100.0, score)), 1)


def device_health_row(row: Mapping, crashes: float = 0) -> float:
    return device_health(row["boot_duration_sec"], row["app_hang_count"], crashes,
                         row["network_latency_ms"], row["hardware_health_score"])


def _missing(v) -> bool:
    return v is None or (isinstance(v, float) and np.isnan(v))


def health_band(score: float) -> str:
    return "Healthy" if score >= 80 else "Degraded" if score >= 65 else "Poor"


def vitals(row: Mapping) -> list[dict]:
    """Per-signal reading + ok/warn/critical state for UI and evidence."""
    items = [
        ("boot", "Boot time", row["boot_duration_sec"], "s"),
        ("latency", "Network latency", row["network_latency_ms"], "ms"),
        ("packet_loss", "Packet loss", row["packet_loss_pct"], "%"),
        ("hangs", "App hangs / wk", row["app_hang_count"], ""),
        ("hw_health", "Hardware health", row["hardware_health_score"], ""),
        ("battery", "Battery health", row["battery_health_pct"], "%"),
        ("disk", "Disk health", row["disk_health_pct"], "%"),
        ("temp", "Temperature", row.get("device_temperature_c"), "°C"),
    ]
    out = [{"key": k, "label": label, "value": None if _missing(v) else round(float(v), 2), "unit": u,
            "state": "na" if _missing(v) else signal_state(k, v)} for k, label, v, u in items]
    compliant = bool(row["policy_compliant"])
    out.append({"key": "policy", "label": "Policy state", "value": "Compliant" if compliant else "Non-compliant",
                "unit": "", "state": "ok" if compliant else "critical"})
    return out


__all__ = ["CATEGORIES", "category_severity", "category_severity_frame", "telemetry_severity_frame",
           "device_health_frame", "telemetry_severity_score", "device_health",
           "device_health_row", "health_band", "vitals", "SEVERITY_CAP"]
