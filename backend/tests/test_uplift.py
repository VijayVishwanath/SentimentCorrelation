"""Causal uplift (difference-in-differences vs matched never-fixed devices)."""
import pytest

from app.engines import uplift


@pytest.fixture(scope="module")
def u(client):
    r = client.get("/api/v1/outcomes/uplift")
    assert r.status_code == 200
    return r.json()


def test_controls_are_never_fixed_devices(u, store):
    assert u["available"]
    assert u["control_pool"] == len(store.devices) - len(store.remediated_devices)
    assert 0 < u["overall"]["cases"] <= len(store.remediations)
    assert sum(c["cases"] for c in u["by_category"]) == u["overall"]["cases"]


def test_uplift_is_treated_change_minus_control_change(u):
    for block in [u["overall"], *u["by_category"]]:
        for m in ("tickets", "frustration"):
            x = block[m]
            assert abs(x["uplift"] - (x["naive_change"] - x["control_change"])) < 0.01
            lo, hi = x["ci95"]
            assert lo - 1e-6 <= x["uplift"] <= hi + 1e-6
            assert x["significant"] == (hi < 0 or lo > 0)


def test_estimate_is_reproducible_and_scoped(u, store, client):
    uplift._memo.clear()
    again = uplift.causal_uplift(store)
    assert again["overall"] == u["overall"]
    cat = u["by_category"][0]["category"]
    one = client.get(f"/api/v1/outcomes/uplift?category={cat}").json()
    assert one["overall"]["cases"] == u["by_category"][0]["cases"]
    assert client.get("/api/v1/outcomes/uplift?department=__none__").json()["available"] is False


def test_roi_uses_the_causal_ticket_count(u, client):
    roi = client.get("/api/v1/roi").json()
    assert roi["inputs"]["tickets_avoided"]["value"] == round(uplift.annual_tickets_avoided(u))
    assert roi["causal"]["causal_tickets_avoided"] <= roi["causal"]["naive_tickets_avoided"]
