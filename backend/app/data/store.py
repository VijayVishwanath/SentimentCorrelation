"""In-memory analytical store: raw tables + derived, analysis-ready views.

Built once per dataset version and swapped atomically on reload, so request
handlers always see a consistent snapshot.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .. import db
from ..config import get_settings
from ..engines import experience as exp
from ..engines import telemetry as tel
from ..engines.thresholds import CATEGORIES, THRESHOLDS
from .loader import load_dataset
from .schemas import REMEDIATION_METRIC_COLUMNS

log = logging.getLogger(__name__)


@dataclass
class DataStore:
    devices: pd.DataFrame
    telemetry: pd.DataFrame
    tickets: pd.DataFrame
    remediations: pd.DataFrame
    device_weeks: pd.DataFrame = field(init=False)
    weeks: list[int] = field(init=False)
    week_dates: dict[int, str] = field(init=False)

    def __post_init__(self) -> None:
        if get_settings().mask_pii:
            self._mask_names()
        self._build()

    def _mask_names(self) -> None:
        """Replace employee names with stable pseudonyms (DEX_MASK_PII=true)."""
        alias = {dev: f"Employee {dev.split('-')[-1]}" for dev in self.devices["device_id"]}
        for name in ("devices", "tickets", "remediations"):
            df = getattr(self, name).copy()
            df["employee_name"] = df["device_id"].map(alias).fillna("Employee")
            setattr(self, name, df)

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        # one string dtype for join keys, whatever the source (Excel, CSV, SQLite)
        for name in ("devices", "telemetry", "tickets", "remediations"):
            df = getattr(self, name).copy()
            for col in ("device_id", "ticket_id", "remediation_id"):
                if col in df:
                    df[col] = df[col].astype(str)
            setattr(self, name, df)
        t = self.tickets.copy()
        t["escalated"] = t["outcome_status"].eq("Escalated")
        t["reopened"] = t["outcome_status"].eq("Reopened")
        # prior contacts on the same issue (+1 when the ticket bounced back as reopened)
        t["prior_contacts"] = (t["repeat_number"].astype(int) - 1).clip(lower=0) + t["reopened"].astype(int)
        cache: dict[tuple, exp.ExperienceResult] = {}  # real ticket language repeats a lot
        results = []
        for key in zip(t["ticket_text"], t["prior_contacts"].astype(int), t["escalated"].astype(int)):
            if key not in cache:
                cache[key] = exp.analyze_text(key[0], int(key[1]), int(key[2]))
            results.append(cache[key])
        t["text_score"] = [r.text_score for r in results]
        t["frustration_score"] = [r.frustration_score for r in results]
        t["sentiment"] = [r.sentiment for r in results]
        t["sentiment_tier"] = [r.sentiment_tier for r in results]
        t["severity"] = [r.severity for r in results]
        t["emotion"] = [r.emotion for r in results]

        telem = self.telemetry.sort_values(["device_id", "week"]).reset_index(drop=True)
        telem["non_compliant"] = telem["policy_compliant"].astype(object).map({False: 1}).fillna(0).astype(int)
        telem["vpn_failure"] = (telem["packet_loss_pct"] >= THRESHOLDS["packet_loss"]["warn"]).astype(int)

        # Ticket -> telemetry at (or most recently before) the ticket's week
        telem["_tel_week"] = telem["week"]
        t = pd.merge_asof(
            t.sort_values("week"), telem.sort_values("week"), on="week", by="device_id",
            direction="backward", suffixes=("", "_tel"))
        missing = t["_tel_week"].isna()
        if missing.any():  # ticket before first telemetry week -> use first week
            first = telem.groupby("device_id").first()
            for col in ["boot_duration_sec", "app_hang_count", "network_latency_ms", "packet_loss_pct",
                        "policy_compliant", "hardware_health_score", "battery_health_pct", "disk_health_pct",
                        "non_compliant", "vpn_failure"]:
                t.loc[missing, col] = t.loc[missing, "device_id"].map(first[col])
        t = t.drop(columns=["_tel_week"])
        telem = telem.drop(columns=["_tel_week"])
        sev = tel.category_severity_frame(t)
        for c in CATEGORIES:
            t[f"sev_{c}"] = sev[c]
        t["telemetry_severity"] = tel.telemetry_severity_frame(sev)
        dev = self.devices.set_index("device_id")
        t["device_model"] = t["device_id"].map(dev["device_model"])
        t["work_mode"] = t["device_id"].map(dev["work_mode"])
        self.tickets_enriched = t.sort_values("ticket_id").reset_index(drop=True)

        # Device-week fact table (every device, every week)
        g = t.groupby(["device_id", "week"])
        agg = pd.DataFrame({
            "ticket_count": g.size(),
            "repeat_contacts": g["repeat_contact"].sum(),
            "escalations": g["escalated"].sum(),
            "crash_events": t.assign(_c=t["category"].eq("Application Crash")).groupby(["device_id", "week"])["_c"].sum(),
            "avg_frustration": g["frustration_score"].mean(),
            "max_frustration": g["frustration_score"].max(),
            "avg_text_score": g["text_score"].mean(),
            "resolution_hours": g["resolution_time_hours"].sum(),
        }).reset_index()
        dw = telem.merge(agg, on=["device_id", "week"], how="left")
        for c in ["ticket_count", "repeat_contacts", "escalations", "crash_events", "resolution_hours"]:
            dw[c] = dw[c].fillna(0)
        dw["ticket_count"] = dw["ticket_count"].astype(int)
        dw = dw.merge(self.devices, on="device_id", how="left")
        dw["device_health"] = tel.device_health_frame(dw, dw["crash_events"])
        dw["telemetry_severity"] = tel.telemetry_severity_frame(tel.category_severity_frame(dw))
        # Weekly experience burden: frustration experienced that week (0 when no contact)
        dw["experience_burden"] = dw["max_frustration"].fillna(0)
        self.device_weeks = dw.sort_values(["device_id", "week"]).reset_index(drop=True)

        # Per-device positional slices: one sort, then O(1) lookups (scales to millions of device-weeks)
        self._tk_by_dev = self.tickets_enriched.sort_values(["device_id", "week", "ticket_id"]).reset_index(drop=True)
        self._dw_pos = _slices(self.device_weeks["device_id"])
        self._tk_pos = _slices(self._tk_by_dev["device_id"])
        # narrow projections for DEX-score windows (much cheaper to slice than the wide frames)
        self._dex_dw = self.device_weeks[["device_id", "week", "experience_burden", "device_health"]]
        self._dex_tk = self._tk_by_dev[["device_id", "ticket_id", "week", "category", "outcome_status",
                                        "resolution_time_hours", "frustration_score", "repeat_contact"]]
        self._dev_pos = {d: i for i, d in enumerate(self.devices["device_id"])}

        self.weeks = sorted(int(w) for w in telem["week"].unique())
        self.week_dates = (telem.drop_duplicates("week").set_index("week")["week_start"]
                           .astype(str).to_dict())
        self._derive_remediation_metrics()
        self.remediated_devices = set(self.remediations["device_id"])
        log.info("store built: %d tickets, %d device-weeks", len(t), len(dw))

    def _derive_remediation_metrics(self) -> None:
        """Fill missing pre/post remediation metrics from telemetry and tickets (pre = weeks before the fix,
        post = fix week onward) so an upload only needs device, week, root cause and action."""
        from ..engines.dex_score import within_window_repeats
        self.remediation_metrics_derived = 0
        rem = self.remediations
        if rem.empty:
            return
        cols = REMEDIATION_METRIC_COLUMNS
        for c in cols:
            if c not in rem:
                rem[c] = np.nan
        need = rem[cols].isna().any(axis=1)
        if not need.any():
            return
        rem = rem.copy()
        for idx in rem.index[need]:
            dev, w = rem.at[idx, "device_id"], int(rem.at[idx, "week_of_remediation"])
            h, tk = self.device_history(dev), self.device_tickets(dev)
            for side, hh, tt in (("pre", h[h["week"] < w], tk[tk["week"] < w]), ("post", h[h["week"] >= w], tk[tk["week"] >= w])):
                weeks = max(1, int(hh["week"].nunique()))
                reps = within_window_repeats(tt) if len(tt) else pd.Series(dtype=bool)
                vals = {
                    f"{side}_boot_duration_sec": hh["boot_duration_sec"].mean(),
                    f"{side}_network_latency_ms": hh["network_latency_ms"].mean(),
                    f"{side}_hardware_health_score": hh["hardware_health_score"].mean(),
                    f"{side}_app_hang_count": hh["app_hang_count"].mean(),
                    f"{side}_ticket_count": float(len(tt)),
                    f"{side}_ticket_rate_per_week": round(len(tt) / weeks, 2),
                    f"{side}_frustration_score": tt["frustration_score"].mean() if len(tt) else np.nan,
                    f"{side}_repeat_contact_rate_pct": round(100 * float(reps.mean()), 1) if len(tt) else 0.0,
                }
                for c, v in vals.items():
                    if pd.isna(rem.at[idx, c]):
                        rem.at[idx, c] = round(float(v), 2) if pd.notna(v) else np.nan
        self.remediations = rem
        self.remediation_metrics_derived = int(need.sum())
        log.info("derived pre/post metrics for %d remediation case(s)", self.remediation_metrics_derived)

    # --------------------------------------------------------------- helpers
    def device_ids(self) -> list[str]:
        return self.devices["device_id"].tolist()

    def device(self, device_id: str) -> dict | None:
        i = self._dev_pos.get(device_id)
        return None if i is None else self.devices.iloc[i].to_dict()

    def device_history(self, device_id: str) -> pd.DataFrame:
        a, b = self._dw_pos.get(device_id, (0, 0))
        return self.device_weeks.iloc[a:b]

    def dex_frames(self, device_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        a, b = self._dw_pos.get(device_id, (0, 0))
        c, d = self._tk_pos.get(device_id, (0, 0))
        return self._dex_dw.iloc[a:b], self._dex_tk.iloc[c:d]

    def device_tickets(self, device_id: str) -> pd.DataFrame:
        a, b = self._tk_pos.get(device_id, (0, 0))
        return self._tk_by_dev.iloc[a:b]

    def telemetry_at(self, device_id: str, week: int | None = None) -> dict | None:
        h = self.device_history(device_id)
        if h.empty:
            return None
        if week is not None:
            h = h[h["week"] <= week] if (h["week"] <= week).any() else h.head(1)
        return h.iloc[-1].to_dict()

    def filter_weeks(self, df: pd.DataFrame, week_from: int | None, week_to: int | None, col: str = "week"):
        if week_from is not None:
            df = df[df[col] >= week_from]
        if week_to is not None:
            df = df[df[col] <= week_to]
        return df

    def apply_filters(self, df: pd.DataFrame, department: str | None = None, device_model: str | None = None,
                      work_mode: str | None = None, week_from: int | None = None, week_to: int | None = None):
        if department:
            df = df[df["department"] == department]
        if device_model and "device_model" in df:
            df = df[df["device_model"] == device_model]
        if work_mode and "work_mode" in df:
            df = df[df["work_mode"] == work_mode]
        return self.filter_weeks(df, week_from, week_to)

    def dimensions(self) -> dict:
        return {
            "departments": sorted(self.devices["department"].unique().tolist()),
            "device_models": sorted(self.devices["device_model"].unique().tolist()),
            "work_modes": sorted(self.devices["work_mode"].unique().tolist()),
            "weeks": [{"week": w, "week_start": self.week_dates.get(w)} for w in self.weeks],
            "categories": CATEGORIES,
            "channels": sorted(self.tickets["channel"].unique().tolist()),
        }


def _slices(sorted_ids: pd.Series) -> dict[str, tuple[int, int]]:
    """{id: (start, end)} row ranges for a frame already sorted by id."""
    if sorted_ids.empty:
        return {}
    vals = sorted_ids.to_numpy()
    uniq, starts = np.unique(vals, return_index=True)
    order = np.argsort(starts)
    uniq, starts = uniq[order], starts[order]
    ends = np.append(starts[1:], len(vals))
    return {str(u): (int(s), int(e)) for u, s, e in zip(uniq, starts, ends)}


# ---------------------------------------------------------------- singleton
_lock = threading.Lock()
_store: DataStore | None = None


def _from_frames(frames: dict[str, pd.DataFrame]) -> DataStore:
    return DataStore(frames["devices"], frames["telemetry"], frames["tickets"], frames["remediations"])


def init_store(force_seed: bool = False) -> DataStore:
    global _store
    with _lock:
        if force_seed or not db.has_dataset():
            path = Path(get_settings().seed_dataset)
            frames, _ = load_dataset(path)
            db.save_dataset(frames, source=path.name)
        _store = _from_frames(db.read_dataset())
        return _store


def build_store(frames: dict[str, pd.DataFrame]) -> DataStore:
    """Build a complete analytical store without publishing it."""
    return _from_frames(frames)


def replace_store(frames: dict[str, pd.DataFrame], source: str, built: DataStore | None = None) -> DataStore:
    global _store
    new = built or _from_frames(frames)  # build first so a bad dataset never replaces a good one
    with _lock:
        db.save_dataset(frames, source=source)
        _store = new
    return new


def get_store() -> DataStore:
    if _store is None:
        return init_store()
    return _store


def to_records(df: pd.DataFrame) -> list[dict]:
    """JSON-safe records (NaN -> None, numpy -> python)."""
    return df.replace({np.nan: None}).to_dict("records")
