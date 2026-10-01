"""Pre-compute the heaviest unfiltered views so the next page load is instant.

One routine for every trigger: startup, a new dataset (upload or ServiceNow sync) and a settings change.
"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)


def warm_cache() -> None:
    from ..data.store import get_store
    from ..engines import forecast, ml
    from . import routes_analytics as ra
    from .deps import Filters
    try:
        store, f = get_store(), Filters()
        ra.executive_dashboard(f, store)
        ra.outcome_report(None, None, store)
        ra.correlation_analysis(f, store, "frustration")
        ml.get_model(store)  # ML second opinion
        forecast.get_forecaster(store)  # predictive model: backtest + fit
        ra.roi_critical_few(f, store)  # Pareto view reuses the outcome report and forecaster above
        ra.command_center(f, store)  # landing page (also primes the outcome report behind Annual Benefits)
        log.info("cache warm-up complete")
    except Exception:
        log.exception("cache warm-up failed")


def warm_in_background(name: str = "cache-warmup") -> None:
    threading.Thread(target=warm_cache, name=name, daemon=True).start()
