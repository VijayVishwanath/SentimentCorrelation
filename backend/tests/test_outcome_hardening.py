"""Regression tests: savings sign, edge-case remediation weeks, and cache correctness."""
from app.copilot.tools import effective_config
from app.engines import outcomes


class _Store:
    """The real store with a different remediation register."""

    def __init__(self, store, remediations):
        self._s, self.remediations = store, remediations

    def __getattr__(self, name):
        return getattr(self._s, name)


def test_reduction_is_zero_when_tickets_did_not_fall():
    assert outcomes.ticket_reduction_pct({"ticket_rate": {"change_pct": 40.0, "improved": False}}) == 0.0
    assert outcomes.ticket_reduction_pct({"ticket_rate": {"change_pct": 40.0, "improved": True}}) == 40.0
    assert outcomes.ticket_reduction_pct(None) == 0.0


def test_command_center_savings_use_signed_reduction(client):
    d = client.get("/api/v1/dashboard/command-center").json()
    by_cat = {c["category"]: c for c in client.get("/api/v1/outcomes").json()["by_category"]}
    for a in d["actions"]:
        assert a["ticket_reduction_pct"] == round(outcomes.ticket_reduction_pct(by_cat.get(a["category"])), 1)
        assert a["savings_per_year_usd"] >= 0


def test_fixes_in_the_first_week_do_not_crash(store):
    rems = store.remediations.copy()
    rems["week_of_remediation"] = min(store.weeks)  # nothing before the fix: no "before" DEX window
    rep = outcomes.outcome_report(_Store(store, rems), effective_config())
    assert rep["cases"] == len(rems) and rep["dex"]["available"] is False
    assert all(c["recovery_pct"] is None for c in rep["by_category"])


def test_outcome_report_is_memoised_per_settings(store):
    cfg = effective_config()
    a = outcomes.outcome_report(store, cfg)
    assert outcomes.outcome_report(store, dict(cfg)) is a
    assert outcomes.outcome_report(store, {**cfg, "cost_per_ticket_usd": cfg["cost_per_ticket_usd"] + 1}) is not a


def test_memo_drops_results_computed_across_a_cache_clear(store):
    from app.api import routes_analytics as ra

    def stale():
        ra.clear_cache()  # a settings change lands while this value is being computed
        return "stale"

    assert ra.memo(store, "t_gen", (), stale) == "stale"
    assert ra.memo(store, "t_gen", (), lambda: "fresh") == "fresh"
