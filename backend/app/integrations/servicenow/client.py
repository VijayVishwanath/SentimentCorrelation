"""ServiceNow Table API clients.

`LiveClient` reads the `incident` table of a real instance with basic auth. `MockClient` is a built-in demo
instance that answers in exactly the same JSON shape (``sysparm_display_value=all``: every field is
``{"value": ..., "display_value": ...}``), so the mapper and the sync path are identical in both modes.
Both are read-only: the sync never writes to ServiceNow.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

SN_TIME = "%Y-%m-%d %H:%M:%S"  # ServiceNow internal (UTC) date-time format
FIELDS = ["sys_id", "number", "sys_updated_on", "opened_at", "resolved_at", "state", "short_description",
          "description", "cmdb_ci", "caller_id", "contact_type", "category", "subcategory", "reopen_count",
          "escalation", "priority"]


class ServiceNowError(RuntimeError):
    pass


def sn_time(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(SN_TIME)


def host_of(instance: str | None) -> str | None:
    if not instance:
        return None
    u = instance if "://" in instance else f"https://{instance}"
    return urlparse(u).netloc or None


class LiveClient:
    mode = "live"

    def __init__(self, instance: str, username: str, password: str, *, extra_query: str | None = None,
                 page_size: int = 500, max_records: int = 10_000, timeout: float = 30.0,
                 transport: httpx.BaseTransport | None = None, retry_wait: float = 1.0):
        base = instance.rstrip("/")
        if "://" not in base:
            base = f"https://{base}"
        self.instance = host_of(base)
        self.extra_query = (extra_query or "").strip("^ ")
        self.page_size, self.max_records, self.retry_wait = page_size, max_records, retry_wait
        self._http = httpx.Client(base_url=base, auth=(username, password), timeout=timeout, transport=transport,
                                  headers={"Accept": "application/json"})

    def _get(self, params: dict) -> list[dict]:
        for attempt in range(3):
            try:
                r = self._http.get("/api/now/table/incident", params=params)
            except httpx.HTTPError as e:
                if attempt == 2:
                    raise ServiceNowError(f"could not reach {self.instance}: {e}") from e
                time.sleep(self.retry_wait * (attempt + 1))
                continue
            if r.status_code in (401, 403):
                raise ServiceNowError(f"ServiceNow rejected the credentials ({r.status_code}) — check "
                                      "DEX_SERVICENOW_USERNAME / PASSWORD and that the user can read the incident table")
            if r.status_code == 429 or r.status_code >= 500:
                if attempt == 2:
                    raise ServiceNowError(f"ServiceNow returned {r.status_code} after 3 attempts")
                wait = r.headers.get("Retry-After")
                time.sleep(min(float(wait), 30.0) if wait and wait.replace(".", "", 1).isdigit()
                           else self.retry_wait * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise ServiceNowError(f"ServiceNow returned {r.status_code}: {r.text[:200]}")
            try:
                return r.json().get("result", [])
            except ValueError as e:  # e.g. a hibernating developer instance answers with an HTML page
                raise ServiceNowError(f"{self.instance} did not answer with JSON — is the instance awake?") from e
        return []

    def fetch_incidents(self, since: datetime) -> list[dict]:
        """Every incident updated after `since`, oldest change first, paged."""
        q = f"sys_updated_on>{sn_time(since)}"
        if self.extra_query:
            q += f"^{self.extra_query}"
        q += "^ORDERBYsys_updated_on"
        out: list[dict] = []
        while len(out) < self.max_records:
            page = self._get({"sysparm_query": q, "sysparm_display_value": "all",
                              "sysparm_exclude_reference_link": "true", "sysparm_fields": ",".join(FIELDS),
                              "sysparm_limit": min(self.page_size, self.max_records - len(out)),
                              "sysparm_offset": len(out)})
            out.extend(page)
            if len(page) < self.page_size:
                break
        return out

    def test_connection(self) -> dict:
        rows = self._get({"sysparm_limit": 1, "sysparm_fields": "number,sys_updated_on"})
        return {"ok": True, "instance": self.instance, "sample": rows[0].get("number") if rows else None}


# ---------------------------------------------------------------- demo instance
TEMPLATES = {
    "Network": [
        ("VPN keeps disconnecting", "The VPN drops every 20 minutes and I lose my session in the CRM. This is the third time this week, really frustrating."),
        ("Very slow network from home", "Pages take forever to load and Teams calls keep freezing. I can't work like this."),
        ("Wi-Fi drops in meeting room", "Wi-Fi disconnected twice during a client call. Minor, but embarrassing."),
    ],
    "Performance": [
        ("Laptop extremely slow to start", "Boot takes more than five minutes every morning. I have restarted it many times, nothing helps."),
        ("Everything freezes after update", "Since the last update the laptop is sluggish and Excel freezes for seconds at a time."),
        ("Slow startup", "Startup feels a bit slow since Monday, not urgent."),
    ],
    "Application Crash": [
        ("Outlook crashes repeatedly", "Outlook crashes several times a day and I lose drafts. Again! Please fix this urgently."),
        ("Teams not responding", "Teams hangs when I share my screen and I have to kill it. Happened in two meetings today."),
        ("Excel closed unexpectedly", "Excel closed once while saving, it recovered the file."),
    ],
    "Login/Auth": [
        ("Locked out of my account", "Locked out again after the password change, MFA prompt loops forever. Cannot work at all."),
        ("SSO asks for password every hour", "Single sign-on keeps prompting me for credentials, very annoying."),
        ("Password reset request", "Need a password reset, my password expired over the weekend."),
    ],
    "Hardware": [
        ("Battery drains in an hour", "Battery is dead after an hour away from the dock. Laptop gets very hot. Need a replacement."),
        ("Keyboard keys not working", "Several keys stopped working, I have to use an external keyboard."),
        ("Docking station flicker", "External monitor flickers sometimes when docked."),
    ],
}
SIGNAL_FOR = {"Network": ("network_latency_ms", 1), "Performance": ("boot_duration_sec", 1),
              "Application Crash": ("app_hang_count", 1), "Hardware": ("hardware_health_score", -1),
              "Login/Auth": (None, 0)}
STATES = {1: "New", 2: "In Progress", 3: "On Hold", 6: "Resolved", 7: "Closed"}
CHANNELS = {"phone": "Phone", "email": "Email", "self-service": "Self-service", "chat": "Chat", "walk-in": "Walk-in"}


def _f(value, display=None) -> dict:
    v = "" if value is None else str(value)
    return {"value": v, "display_value": v if display is None else str(display)}


class MockClient:
    """Deterministic demo instance built from the live fleet.

    Batch 0 is the backlog inside the lookback window; every later batch brings a handful of new incidents
    plus state changes (resolutions, reopens, escalations) on the previous batch, all with
    ``sys_updated_on`` just now so they pass the watermark. Incidents land on real devices in the latest
    telemetry weeks, biased toward devices whose telemetry matches the complaint, so a sync moves the analytics.
    """
    mode = "mock"
    instance = "demo instance"

    def __init__(self, store, batch: int, *, seed: int = 7, now: datetime | None = None):
        self.store, self.batch, self.seed = store, batch, seed
        self.now = now or datetime.now(timezone.utc)

    def _window(self) -> tuple[pd.Timestamp, pd.Timestamp]:
        wd = self.store.week_dates or {}
        if wd:
            last = pd.Timestamp(wd[max(wd)])
            return last - pd.Timedelta(days=7), last + pd.Timedelta(days=6, hours=23)
        end = pd.Timestamp(self.now).tz_localize(None)
        return end - pd.Timedelta(days=14), end

    def _batch(self, n: int) -> list[dict]:
        rng = np.random.default_rng(self.seed * 1000 + n)
        size = 36 if n == 0 else int(rng.integers(6, 12))
        dev = self.store.devices.reset_index(drop=True)
        tel = self.store.telemetry
        latest = tel[tel["week"] == tel["week"].max()].set_index("device_id") if len(tel) else pd.DataFrame()
        start, end = self._window()
        span = max((end - start).total_seconds(), 3600)
        cats = list(TEMPLATES)
        out = []
        for i in range(size):
            cat = cats[int(rng.integers(len(cats)))]
            sig, sign = SIGNAL_FOR[cat]
            if sig and sig in latest and latest[sig].notna().any():
                w = latest[sig].reindex(dev["device_id"]).astype(float)
                w = (w - w.min()) if sign > 0 else (w.max() - w)
                w = (w.fillna(0) + 1e-3) ** 2
                idx = int(rng.choice(len(dev), p=(w / w.sum()).to_numpy()))
            else:
                idx = int(rng.integers(len(dev)))
            d = dev.iloc[idx]
            tpl = int(rng.choice(3, p=[0.45, 0.35, 0.20]))
            short, desc = TEMPLATES[cat][tpl]
            opened = (start + pd.Timedelta(seconds=int(rng.uniform(0, span)))).to_pydatetime().replace(tzinfo=timezone.utc)
            state = int(rng.choice([2, 6, 7], p=[0.3, 0.4, 0.3]))
            resolved = opened + timedelta(hours=float(rng.gamma(2.0, 3.0))) if state in (6, 7) else None
            contact = list(CHANNELS)[int(rng.choice(5, p=[0.35, 0.2, 0.15, 0.25, 0.05]))]
            out.append({
                "sys_id": f"mock{n:04d}{i:04d}", "number": f"INC{10_000 + n * 100 + i:07d}",
                "opened_at": opened, "resolved_at": resolved, "state": state, "short_description": short,
                "description": desc, "device": d["device_id"], "caller": d.get("employee_name"),
                "contact_type": contact, "category": "inquiry", "subcategory": cat,
                "reopen_count": 0, "escalation": 0, "priority": 2 + tpl,
            })
        return out

    def _updates(self, prev: list[dict], n: int) -> list[dict]:
        rng = np.random.default_rng(self.seed * 7919 + n)
        changed = []
        for inc in prev:
            r = rng.random()
            inc = dict(inc)
            if inc["state"] == 2 and r < 0.6:  # in-progress work gets resolved
                inc["state"], inc["resolved_at"] = 6, inc["opened_at"] + timedelta(hours=float(rng.gamma(3.0, 4.0)))
            elif inc["state"] in (6, 7) and r < 0.12:  # the fix did not hold
                inc["state"], inc["reopen_count"], inc["resolved_at"] = 2, 1, None
                inc["description"] += " It is happening again after the fix — still not resolved."
            elif r < 0.05:
                inc["escalation"] = 1
            else:
                continue
            changed.append(inc)
        return changed

    def _record(self, inc: dict, updated: datetime) -> dict:
        return {
            "sys_id": _f(inc["sys_id"]), "number": _f(inc["number"]), "sys_updated_on": _f(sn_time(updated)),
            "opened_at": _f(sn_time(inc["opened_at"])),
            "resolved_at": _f(sn_time(inc["resolved_at"]) if inc["resolved_at"] else ""),
            "state": _f(inc["state"], STATES[inc["state"]]), "short_description": _f(inc["short_description"]),
            "description": _f(inc["description"]), "cmdb_ci": _f(f"ci-{inc['device']}", inc["device"]),
            "caller_id": _f(f"usr-{inc['device']}", inc["caller"]),
            "contact_type": _f(inc["contact_type"], CHANNELS[inc["contact_type"]]),
            "category": _f(inc["category"], "Inquiry / Help"), "subcategory": _f(inc["subcategory"]),
            "reopen_count": _f(inc["reopen_count"]), "escalation": _f(inc["escalation"]),
            "priority": _f(inc["priority"]),
        }

    def fetch_incidents(self, since: datetime) -> list[dict]:
        new = self._batch(self.batch)
        upd = self._updates(self._batch(self.batch - 1), self.batch) if self.batch > 0 else []
        recs = [self._record(i, self.now) for i in upd + new]
        return [r for r in recs if r["sys_updated_on"]["value"] > sn_time(since)]

    def test_connection(self) -> dict:
        return {"ok": True, "instance": self.instance, "sample": f"INC{10_000:07d}"}
