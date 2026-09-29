"""Golden tests: the Python engines must reproduce every figure published in the
judge briefing / pitch deck (computed originally by the HTML prototype)."""
import pytest

from app.copilot.tools import effective_config
from app.engines import correlation as corr
from app.engines import outcomes


def fmt1(x):
    return round(x + 1e-9, 1)


@pytest.mark.parametrize("key,expected", [("boot", 1.9), ("latency", 1.9), ("hangs", 1.8), ("hw_health", 1.6)])
def test_severity_lift_matches_briefing(store, key, expected):
    lift = corr.lift_analysis(store.tickets_enriched, store.device_weeks, "text_score")[key]["lift"]
    assert fmt1(lift) == expected


def test_policy_incidence_lift(store):
    pol = corr.lift_analysis(store.tickets_enriched, store.device_weeks, "text_score")["policy"]
    assert pol["detail"]["compliant_rate_pct"] == 0.0
    assert fmt1(pol["detail"]["noncompliant_rate_pct"]) == 28.5
    assert pol["infinite"] is True


def test_outcome_aggregates_match_briefing(store):
    rep = outcomes.outcome_report(store, effective_config())
    agg = rep["aggregate"]
    assert rep["cases"] == 46
    assert fmt1(agg["frustration"]["pre"]) == 69.0 and fmt1(agg["frustration"]["post"]) == 58.2
    assert fmt1(agg["repeat_rate"]["pre"]) == 46.8 and fmt1(agg["repeat_rate"]["post"]) == 0.7
    assert round(agg["ticket_rate"]["pre"], 2) == 0.41 and round(agg["ticket_rate"]["post"], 2) == 0.15
    assert rep["improved_cases"] == 45


def test_dataset_counts(store):
    assert (len(store.devices), len(store.telemetry), len(store.tickets), len(store.remediations)) == (260, 3120, 326, 46)


def test_briefing_diagnosis_example(store):
    """'This is unacceptable at this point. Outlook keeps crashing.' -> High 62/100, Application Crash 100%."""
    from app.engines.diagnosis import diagnose
    t = store.tickets_enriched.set_index("ticket_id").loc["TCK-00002"]
    d = diagnose(t["ticket_text"], t["device_id"], store, week=int(t["week"]))
    assert d["experience"]["text_score"] == 62
    assert d["experience"]["sentiment_tier"] == "High"
    assert d["primary"]["category"] == "Application Crash"
    assert d["primary"]["likelihood"] == 100
    assert "patch" in d["standard_action"].lower()
