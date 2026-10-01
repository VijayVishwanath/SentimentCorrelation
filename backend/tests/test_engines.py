import pandas as pd
import pytest

from app.engines import dex_score, experience as exp, telemetry as tel
from app.engines.correlation import correlation_score
from app.engines.diagnosis import rank_categories, rank_root_causes


class TestExperience:
    def test_baseline_neutral_text(self):
        assert exp.text_frustration("Quick question about my setup") == 8

    def test_negation_not_urgent_does_not_fire(self):
        # validation bug from the briefing: 'urgent' must not match inside 'not urgent'
        assert exp.text_frustration("Not urgent, but wanted to check something") == 8

    def test_strong_phrase_reaches_high(self):
        assert exp.sentiment_tier(exp.text_frustration("This is unacceptable")) == "High"

    def test_behavioural_boost_and_cap(self):
        assert exp.calculate_frustration("unacceptable", repeat_contacts=1, escalation_count=1) == 62 + 10 + 15
        assert exp.calculate_frustration("unacceptable, nothing has changed", 5, 2) == 100

    @pytest.mark.parametrize("score,tier", [(85, "Critical"), (80, "Critical"), (60, "High"), (40, "Medium"), (39, "Low")])
    def test_severity_thresholds(self, score, tier):
        assert exp.experience_severity(score) == tier

    def test_emotion(self):
        assert exp.classify_emotion("This is unacceptable")["primary"] == "Anger"
        assert exp.classify_emotion("Quick question, wanted to confirm")["primary"] == "Inquiry"
        assert exp.classify_emotion("hello")["primary"] == "Neutral"

    def test_polarity_range(self):
        assert exp.sentiment_polarity("This is unacceptable, I can't get my work done") < -0.9
        assert exp.sentiment_polarity("Quick question, thanks") > 0


class TestTelemetry:
    def test_device_health_formula(self):
        # (100 - 3 - 3 - 0 - 1.5) * 0.8 + 83 * 0.2 = 92.5*0.8 + 16.6
        assert tel.device_health(30, 1, 0, 30, 83) == pytest.approx(90.6, abs=0.05)

    def test_device_health_clamped(self):
        assert tel.device_health(1000, 50, 50, 5000, 0) == 0.0

    def test_category_severity(self):
        row = {"boot_duration_sec": 85, "network_latency_ms": 30, "packet_loss_pct": 0.2, "policy_compliant": False,
               "hardware_health_score": 80, "app_hang_count": 0}
        sev = tel.category_severity(row)
        assert sev["Performance"] == pytest.approx(1.0)
        assert sev["Login/Auth"] == 1.0 and sev["Network"] == 0 and sev["Application Crash"] == 0


class TestDiagnosis:
    def test_text_drives_category_when_telemetry_clean(self):
        row = {"boot_duration_sec": 30, "network_latency_ms": 30, "packet_loss_pct": 0.2, "policy_compliant": True,
               "hardware_health_score": 85, "app_hang_count": 0}
        assert rank_categories("VPN keeps dropping my connection", row)[0]["category"] == "Network"

    def test_telemetry_outweighs_text(self):
        row = {"boot_duration_sec": 30, "network_latency_ms": 30, "packet_loss_pct": 0.2, "policy_compliant": True,
               "hardware_health_score": 85, "app_hang_count": 9}
        assert rank_categories("my laptop is slow", row)[0]["category"] == "Application Crash"

    def test_spec_rank_root_causes(self):
        out = rank_root_causes({"crashes": 7, "memory_usage": 95, "profile_corruption": True})
        assert [c for c, _ in out] == ["Application Crash", "Memory Leak", "Profile Corruption"]


class TestDexScore:
    def test_formula(self):
        assert dex_score.dex_score(100, 100, 100, 100, 100) == 100
        assert dex_score.dex_score(80, 90, 70, 60, 50) == pytest.approx(0.35 * 80 + 0.25 * 90 + 0.2 * 70 + 0.1 * 60 + 0.1 * 50, abs=0.05)

    def test_recovery_spec_example(self):
        assert dex_score.experience_recovery(52, 78) == 50.0

    def test_within_window_repeats(self):
        t = pd.DataFrame({"device_id": ["A", "A", "A", "B"], "category": ["Net", "Net", "HW", "Net"],
                          "week": [1, 2, 3, 1], "ticket_id": ["1", "2", "3", "4"]})
        assert dex_score.within_window_repeats(t).tolist() == [False, True, False, False]

    def test_sts_neutral_when_flat(self):
        dw = pd.DataFrame({"week": [1, 2, 3, 4], "experience_burden": [10, 10, 10, 10]})
        assert dex_score.sentiment_trend(dw)[0] == 50.0


def test_correlation_score_spec():
    assert correlation_score([1, 2, 3, 4], [2, 4, 6, 8]) == 1.0
    assert correlation_score([1, 1, 1], [1, 2, 3]) is None


def test_store_integrity(store):
    t = store.tickets_enriched
    assert t["boot_duration_sec"].notna().all()
    assert set(t["severity"]) <= {"Low", "Medium", "High", "Critical"}
    assert len(store.device_weeks) == 3120
    assert store.device_weeks["device_health"].between(0, 100).all()


class TestThermalTriage:
    def test_no_hang_or_heat_language_keeps_base_priority(self):
        from app.engines.diagnosis import triage
        out = triage("Nothing has changed since my last ticket about the VPN.", {"device_temperature_c": 95,
                                                                               "battery_health_pct": 30}, 50)
        assert out["priority"]["boost"] == 0 and out["priority"]["level"] == "P3"
        assert out["priority"]["thermal_check"] is None and out["user_suggestions"] == []

    def test_heat_language_with_hot_device_and_worn_battery_raises_priority(self):
        from app.engines.diagnosis import HEAVY_APPS_TIP, triage
        out = triage("Laptop is overheating and Outlook hangs", {"device_temperature_c": 92, "battery_health_pct": 50}, 40)
        p = out["priority"]
        assert p["boost"] == 10 + 25 + 10 and p["score"] == 85 and p["level"] == "P1"
        assert p["thermal_check"]["matched_terms"] == ["hangs", "overheating"]
        assert out["user_suggestions"][0] == HEAVY_APPS_TIP and len(out["user_suggestions"]) == 3

    def test_unmeasured_temperature_is_reported_not_guessed(self):
        from app.engines.diagnosis import triage
        out = triage("Teams is not responding", {"battery_health_pct": 90}, 30)
        assert out["priority"]["boost"] == 10
        temp = next(r for r in out["priority"]["thermal_check"]["readings"] if r["signal"] == "temp")
        assert temp["state"] == "na" and any("not measured" in r for r in out["priority"]["reasons"])
