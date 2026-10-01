"""Auto-sync: a daemon thread that starts a ServiceNow sync every N minutes (0 = off).

The interval is read on every tick, so changing it in the UI takes effect without a restart. The clock
runs from the last sync of any kind, so a manual sync also resets the countdown.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from ...data.jobs import JobBusyError
from .client import ServiceNowError

log = logging.getLogger(__name__)
POLL_SEC = 15.0


class Scheduler:
    def __init__(self):
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        from .sync import recover_interrupted
        recover_interrupted()  # no job survives a restart
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="servicenow-auto-sync", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(POLL_SEC):
            try:
                self.tick()
            except Exception:
                log.exception("servicenow auto-sync tick failed")

    @staticmethod
    def _due_at() -> datetime | None:
        from .sync import effective_settings, list_runs
        minutes = effective_settings()["auto_sync_minutes"]
        if minutes <= 0:
            return None
        last = list_runs(1)
        if not last:
            return datetime.now(timezone.utc)
        return datetime.fromisoformat(last[0]["started_at"]) + timedelta(minutes=minutes)

    def next_run_at(self) -> str | None:
        due = self._due_at()
        return due.isoformat() if due else None

    def tick(self, now: datetime | None = None) -> str:
        """One scheduler step; returns what happened (off | waiting | started | busy | failed)."""
        from .sync import start_sync
        due = self._due_at()
        if due is None:
            return "off"
        if (now or datetime.now(timezone.utc)) < due:
            return "waiting"
        try:
            start_sync("scheduled")
            return "started"
        except JobBusyError:
            return "busy"
        except ServiceNowError as e:
            log.warning("scheduled ServiceNow sync failed: %s", e)
            return "failed"


scheduler = Scheduler()
