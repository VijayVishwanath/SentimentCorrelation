import numpy as np
import pandas as pd
import pytest

from app.data.loader import validate_frames
from app.data.simulator import SimConfig, simulate
from app.data.store import build_store
from app.engines import forecast as fc


@pytest.fixture(scope="module")
def sim_forecaster():
    frames, _ = validate_frames(simulate(SimConfig(devices=600, weeks=16, seed=11)))
    return fc.Forecaster(build_store(frames))


def test_features_do_not_leak_future_weeks(store):
    dw = store.device_weeks
    base = fc.build_features(dw, store.devices, store.remediations)
    t = 6
    future = dw.copy()
    later = future["week"] > t
    for col in ["boot_duration_sec", "network_latency_ms", "hardware_health_score", "ticket_count", "max_frustration"]:
        future.loc[later, col] = future.loc[later, col].astype(float) * 3 + 50
    mutated = fc.build_features(future, store.devices, store.remediations)
    cols = fc.feature_columns(base)
    a = base[base["week"] <= t][cols].reset_index(drop=True)
    b = mutated[mutated["week"] <= t][cols].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)
    assert not base.loc[base["week"] == t, "label"].equals(mutated.loc[mutated["week"] == t, "label"])


def test_label_is_next_week_frustration(store):
    f = fc.build_features(store.device_weeks, store.devices, store.remediations)
    assert f.loc[f["week"] == max(store.weeks), "label"].isna().all()
    dw = store.device_weeks.set_index(["device_id", "week"])
    row = f[(f["week"] < max(store.weeks)) & (f["label"] == 1)].iloc[0]
    assert dw.at[(row["device_id"], row["week"] + 1), "max_frustration"] >= fc.FRUSTRATED


def test_bundled_sample_is_flagged_low_sample(store):
    m = fc.get_forecaster(store).metrics
    if m["available"]:
        assert m["low_sample"] is True
    else:
        assert m["reason"]


def test_too_little_history_is_unavailable():
    frames, _ = validate_frames(simulate(SimConfig(devices=60, weeks=4, seed=5)))
    f = fc.Forecaster(build_store(frames))
    assert f.available is False and "weeks" in f.metrics["reason"]
    assert f.watchlist({"cost_per_ticket_usd": 1, "productivity_loss_factor": 1, "hourly_employee_cost_usd": 1})[
        "available"] is False


def test_model_beats_rule_baseline_out_of_time(sim_forecaster):
    bt = sim_forecaster.metrics["backtest"]
    assert bt["ml"]["roc_auc"] > bt["rules"]["roc_auc"]
    assert bt["ml"]["pr_auc"] > bt["rules"]["pr_auc"]
    assert bt["ml"]["recall_pct"] >= bt["rules"]["recall_pct"]


def test_contributions_sum_to_raw_score(sim_forecaster):
    f = sim_forecaster
    raw_logit = np.log(f.latest_raw / (1 - f.latest_raw))
    total = f.latest_contrib.sum(axis=1).to_numpy() + f.latest_bias
    np.testing.assert_allclose(total, raw_logit, rtol=1e-4, atol=1e-4)


def test_watchlist_is_ranked_and_explained(sim_forecaster):
    cfg = {"cost_per_ticket_usd": 22, "productivity_loss_factor": 0.5, "hourly_employee_cost_usd": 55}
    w = sim_forecaster.watchlist(cfg, top=20)
    risks = [i["risk_pct"] for i in w["items"]]
    assert risks == sorted(risks, reverse=True) and len(risks) == 20
    assert w["predicts_week"] == w["as_of_week"] + 1
    top = w["items"][0]
    assert top["drivers"] and top["action"] and top["kb_id"]
    d = sim_forecaster.device(top["device_id"])
    assert d["current"]["risk_pct"] == top["risk_pct"]
    assert d["history"][-1]["source"] == "live forecast"
