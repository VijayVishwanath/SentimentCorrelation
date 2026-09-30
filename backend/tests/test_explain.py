from app.engines import experience as exp


def test_steps_add_up_to_the_score():
    e = exp.explain("Third time I'm reporting this. Outlook keeps happening to crash, this is unacceptable.", 2, 1)
    assert e["steps"][0]["points"] == exp.TEXT_BASELINE
    assert sum(s["points"] for s in e["steps"]) - e["capped_points"] == e["frustration_score"]
    assert e["steps"][-1]["running_total"] == sum(s["points"] for s in e["steps"])
    assert {s["phrase"] for s in e["spans"] if s["kind"] == "score"} == {p["phrase"] for p in exp.matched_phrases(e["text"])}
    assert e["frustration_score"] == exp.calculate_frustration(e["text"], 2, 1)


def test_spans_point_at_the_text():
    text = "Quick question: same issue as last week, still not resolved. Thanks"
    e = exp.explain(text)
    for s in e["spans"]:
        assert text.lower()[s["start"]:s["end"]] == s["phrase"]
    starts = [(s["start"], s["end"]) for s in e["spans"]]
    assert all(a[1] <= b[0] for a, b in zip(starts, starts[1:]))  # no overlapping highlights
    assert "same issue" not in {s["phrase"] for s in e["spans"]}  # the longer repeat marker wins
    assert e["sentiment"]["softeners"]


def test_every_ticket_explanation_matches_its_stored_score(store):
    tk = store.tickets_enriched
    combos = tk[["ticket_text", "prior_contacts", "escalated", "frustration_score"]].drop_duplicates(
        ["ticket_text", "prior_contacts", "escalated"])
    for text, prior, esc, score in combos.itertuples(index=False):
        assert exp.explain(text, int(prior), int(bool(esc)))["frustration_score"] == score


def test_explain_api(client, store):
    tid = store.tickets_enriched.sort_values("frustration_score").iloc[-1]["ticket_id"]
    d = client.get(f"/api/v1/experience/tickets/{tid}/explain").json()
    assert d["ticket"]["ticket_id"] == tid and d["frustration_score"] == d["ticket"]["frustration_score"]
    assert d["method"]["lexicon"] and d["severity_bands"][-1]["band"] == "Critical"
    free = client.post("/api/v1/experience/explain", json={"text": "this is unacceptable", "repeat_contacts": 1}).json()
    assert free["frustration_score"] == 8 + 54 + 10
    assert client.get("/api/v1/experience/tickets/NOPE/explain").status_code == 404
