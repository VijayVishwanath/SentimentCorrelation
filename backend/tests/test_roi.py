import pytest


@pytest.fixture(scope="module")
def roi(client):
    return client.get("/api/v1/roi").json()


def test_total_is_the_sum_of_the_four_formulas(roi):
    x = {k: v["value"] for k, v in roi["inputs"].items()}
    c = {k["key"]: k["value_usd"] for k in roi["components"]}
    assert c["tickets"] == round(x["tickets_avoided"] * x["cost_per_ticket_usd"])
    hours = x["affected_employees"] * x["minutes_saved_per_day"] * x["working_days_per_year"] / 60
    assert c["productivity"] == round(hours * x["hourly_employee_cost_usd"])
    assert c["licenses"] == round(x["unused_licenses"] * x["annual_license_cost_usd"])
    assert c["hardware"] == round(x["avoided_replacements"] * x["device_cost_usd"])
    assert roi["total_usd"] == sum(c.values())


def test_sources_are_labelled(roi):
    src = {k: v["source"] for k, v in roi["inputs"].items()}
    assert src["tickets_avoided"] == "measured" and src["minutes_saved_per_day"] == "derived"
    assert src["unused_licenses"] == "assumption"  # no license data in the dataset
    lic = next(c for c in roi["components"] if c["key"] == "licenses")
    assert not lic["data_backed"] and roi["data_backed_usd"] == roi["total_usd"] - lic["value_usd"]


def test_what_if_and_plan(client, roi):
    w = client.get("/api/v1/roi?minutes_saved_per_day=0&unused_licenses=0").json()
    assert w["inputs"]["minutes_saved_per_day"]["source"] == "what-if"
    assert w["total_usd"] == next(c["value_usd"] for c in roi["components"] if c["key"] == "tickets") \
        + next(c["value_usd"] for c in roi["components"] if c["key"] == "hardware")
    plan = client.get("/api/v1/roi?scenario=with_plan").json()
    assert plan["total_usd"] > roi["total_usd"] and plan["inputs"]["affected_employees"]["value"] > roi["inputs"]["affected_employees"]["value"]


def test_saved_assumptions_and_reset(client, roi):
    r = client.put("/api/v1/settings", json={"device_cost_usd": 1000, "roi_unused_licenses": 50})
    assert r.status_code == 200
    d = client.get("/api/v1/roi").json()
    assert d["inputs"]["device_cost_usd"]["value"] == 1000 and d["inputs"]["unused_licenses"]["value"] == 50
    client.put("/api/v1/settings", json={"reset": ["device_cost_usd", "roi_unused_licenses"]})
    assert client.get("/api/v1/roi").json()["total_usd"] == roi["total_usd"]
    assert client.put("/api/v1/settings", json={"reset": ["nope"]}).status_code == 422


@pytest.fixture(scope="module")
def pareto(client):
    r = client.get("/api/v1/roi/critical-few")
    assert r.status_code == 200
    return r.json()


def test_priority_score_is_the_sum_of_four_parts(pareto):
    for i in pareto["issues"]:
        p = i["priority"]
        assert abs(p["score"] - (p["productivity"] + p["cost"] + p["employee"] + p["risk"])) < 0.25
        assert all(0 <= p[k] <= 25 for k in ("productivity", "cost", "employee", "risk"))
    scores = [i["priority"]["score"] for i in pareto["issues"]]
    assert scores == sorted(scores, reverse=True)


def test_critical_few_is_the_smallest_set_reaching_80pct(pareto):
    for m in pareto["measures"].values():
        curve, k = m["curve"], m["critical_count"]
        assert curve[k - 1]["cumulative_pct"] >= 80 - 0.1 and (k == 1 or curve[k - 2]["cumulative_pct"] < 80)
        assert [c["critical"] for c in curve] == [n < k for n in range(len(curve))]
        assert abs(curve[-1]["cumulative_pct"] - 100) < 0.5
    st = {s["measure"]: s for s in pareto["statements"]}
    assert set(st) == {"productivity", "cost", "employee", "incidents"}
    inc = pareto["measures"]["incidents"]
    assert sum(c["value"] for c in inc["curve"]) == pareto["tickets"] and st["incidents"]["issue_count"] == inc["critical_count"]
    cf = pareto["critical_few"]
    assert cf["count"] == sum(i["critical_few"] for i in pareto["issues"]) and cf["impact_pct"] >= 80 - 0.1


def test_every_issue_has_a_solution_and_roi(pareto, client):
    for i in pareto["issues"]:
        assert i["solution"]["fix"] and i["solution"]["kb_id"].startswith("KB-")
        assert i["roi"]["annual_preventable_usd"] <= i["annual_impact_usd"]
    dept = client.get("/api/v1/roi/critical-few?department=Finance").json()
    assert not dept.get("available") or dept["tickets"] < pareto["tickets"]
