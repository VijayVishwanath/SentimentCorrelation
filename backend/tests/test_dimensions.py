"""Experience dimensions beyond frustration: business impact, urgency and trust in IT."""
from app.engines.dimensions import score_dimensions, validity


def levels(d):
    return {k: d[k]["level"] for k in ("impact", "urgency", "trust")}


def test_each_dimension_reads_its_own_cues():
    d = score_dimensions("I can't get my work done, it is affecting my whole team too")
    assert d["impact"]["score"] == 85 and d["impact"]["level"] == "High" and d["primary_concern"] == "Business impact"
    assert {c["family"] for c in d["impact"]["cues"]} == {"Can't work", "Team-wide"}
    d = score_dimensions("This is urgent, please fix before my presentation")
    assert d["urgency"]["score"] == 60 + 20 + 15 and d["urgency"]["level"] == "High"
    d = score_dimensions("Nothing has changed after the reinstall, this is the third time")
    assert d["trust"]["score"] == 65 and d["primary_concern"] == "Trust in IT"


def test_calm_and_negated_language_stays_low():
    for text in ("Network seemed a touch slow on a file download, not urgent.", "Quick question about my printer",
                 "It's no big deal, not that urgent"):
        d = score_dimensions(text)
        assert levels(d) == {"impact": "Low", "urgency": "Low", "trust": "Low"} and d["primary_concern"] is None


def test_word_boundaries():
    assert score_dimensions("I changed my settings, nothing urgent")["trust"]["score"] == 0  # "again" not in "against"
    assert score_dimensions("This happened against all odds")["trust"]["score"] == 0


def test_behaviour_adds_weight():
    d = score_dimensions("Outlook keeps crashing", prior_contacts=4, escalated=True, reopened=True)
    assert d["urgency"]["score"] == 25  # escalated only
    assert d["trust"]["score"] == 36 + 20  # prior contacts capped at 36, plus reopened
    kinds = {c["kind"] for c in d["trust"]["cues"]}
    assert kinds == {"behaviour"}


def test_cue_spans_point_at_the_text():
    text = "Losing hours of work, this needs to be fixed urgently"
    d = score_dimensions(text)
    for key in ("impact", "urgency"):
        for cue in d[key]["cues"]:
            for m in cue["matches"]:
                assert text.lower()[m["start"]:m["end"]] == m["phrase"]


def test_store_and_api_carry_dimensions(client, store):
    tk = store.tickets_enriched
    for col in ("impact_score", "impact_level", "urgency_score", "trust_score", "primary_concern"):
        assert col in tk
    s = client.get("/api/v1/experience/summary").json()["dimensions"]
    assert {"impact", "urgency", "trust", "primary_concern"} <= set(s)
    assert 0 <= s["impact"]["high_pct"] <= 100 and s["trust"]["weekly_high_pct"]
    t = client.get("/api/v1/experience/tickets?sort_by=trust_score&order=desc&limit=5").json()["items"]
    assert t and t[0]["trust_score"] >= t[-1]["trust_score"]
    a = client.post("/api/v1/experience/analyze", json={"text": "urgent: I can't work at all"}).json()
    assert a["dimensions"]["urgency"]["level"] in ("Medium", "High") and a["frustration_score"] >= 8
    m = client.get("/api/v1/models/metrics").json()["dimensions"]
    assert "not accuracy" in m["note"] and m["trust"]["by_level"][0]["level"] == "Low"


def test_triage_weights_high_urgency_and_impact(client):
    body = {"ticket_text": "Outlook crashes, I can't get my work done and it is affecting my whole team. This is urgent, "
                           "please fix it before my presentation", "device_id": "DEV-0001"}
    d = client.post("/api/v1/diagnosis", json=body).json()
    assert d["dimensions"]["impact"]["level"] == "High" and d["dimensions"]["urgency"]["level"] == "High"
    reasons = " ".join(d["priority"]["reasons"])
    assert "urgency is high" in reasons and "business impact is high" in reasons
    assert d["priority"]["boost"] >= 20


def test_validity_is_reported_honestly(store):
    v = validity(store.tickets_enriched)
    for key in ("impact", "urgency", "trust"):
        assert [r["level"] for r in v[key]["by_level"]] == ["Low", "Medium", "High"]
        assert v[key]["moves_with_outcome"] in (True, False, None)
