import io
from types import SimpleNamespace

import pytest

from app.copilot.prompts import RESPONSE_SCHEMA

GETS = [
    "/api/health", "/api/v1/meta", "/api/v1/dashboard/executive", "/api/v1/dashboard/executive?department=Legal",
    "/api/v1/experience/summary", "/api/v1/experience/tickets?q=vpn", "/api/v1/telemetry/summary",
    "/api/v1/telemetry/devices?sort=health", "/api/v1/devices/DEV-0001", "/api/v1/correlation/analysis",
    "/api/v1/correlation/heatmap?by=work_mode", "/api/v1/correlation/scatter?signal=latency", "/api/v1/dex-score",
    "/api/v1/outcomes", "/api/v1/outcomes?category=Hardware", "/api/v1/models/metrics", "/api/v1/copilot/status",
    "/api/v1/kb", "/api/v1/kb/search?q=battery", "/api/v1/kb/KB-NET-002", "/api/v1/settings",
    "/api/v1/forecast/watchlist?top=10", "/api/v1/forecast/watchlist?department=Legal", "/api/v1/forecast/metrics",
    "/api/v1/forecast/devices/DEV-0001",
]


@pytest.mark.parametrize("path", GETS)
def test_get_endpoints(client, path):
    r = client.get(path)
    assert r.status_code == 200, r.text


def test_executive_kpis_present(client):
    k = client.get("/api/v1/dashboard/executive").json()["kpis"]
    for key in ("dex_score", "experience_recovery_pct", "employee_experience_index", "device_health_score",
                "correlation_score", "repeat_contact_rate_pct", "business_impact_savings_usd"):
        assert k[key] is not None, key
    assert 0 <= k["dex_score"] <= 100


def test_not_found_and_validation(client):
    assert client.get("/api/v1/devices/DEV-9999").status_code == 404
    assert client.get("/api/v1/dashboard/executive?week_from=10&week_to=2").status_code == 422
    assert client.post("/api/v1/diagnosis", json={"ticket_text": "", "device_id": "DEV-0001"}).status_code == 422


def test_diagnosis_endpoint(client):
    r = client.post("/api/v1/diagnosis", json={"ticket_text": "I can't log in, device isn't compliant",
                                               "device_id": "DEV-0001"})
    body = r.json()
    assert r.status_code == 200
    assert len(body["root_causes"]) == 5
    assert "ml_second_opinion" in body
    assert client.get("/api/v1/diagnosis/recent").json()["items"]


def test_copilot_template_schema(client):
    r = client.post("/api/v1/copilot/ask", json={"question": "Why?", "device_id": "DEV-0002",
                                                 "ticket_text": "Outlook keeps crashing", "week": 6})
    body = r.json()
    assert body["provider"] == "template"
    assert set(RESPONSE_SCHEMA["required"]) <= set(body["response"])
    assert body["tool_calls"] and body["response"]["citations"]


def test_settings_roundtrip(client):
    r = client.put("/api/v1/settings", json={"cost_per_ticket_usd": 40})
    assert r.json()["cost_per_ticket_usd"] == 40
    client.put("/api/v1/settings", json={"cost_per_ticket_usd": 22})
    assert client.put("/api/v1/settings", json={"productivity_loss_factor": 5}).status_code == 422


def test_upload_rejects_bad_file(client):
    r = client.post("/api/v1/data/upload", files={"file": ("x.txt", b"hi", "text/plain")})
    assert r.status_code == 415
    r = client.post("/api/v1/data/upload", files={"file": ("x.xlsx", b"not a workbook", "application/octet-stream")})
    assert r.status_code == 415  # content sniffing: not a real .xlsx


def test_upload_roundtrip_seed_workbook(client):
    from app.config import get_settings
    content = get_settings().seed_dataset.read_bytes()
    r = client.post("/api/v1/data/upload", files={"file": ("seed.xlsx", io.BytesIO(content), "application/octet-stream")})
    assert r.status_code == 200, r.text
    assert r.json()["rows"]["tickets"] == 326


def test_api_key_enforced(client, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "api_key", "secret")
    assert client.get("/api/v1/meta").status_code == 401
    assert client.get("/api/v1/meta", headers={"X-API-Key": "secret"}).status_code == 200
    assert client.get("/api/health").status_code == 200


# ---------------------------------------------------------------- Claude provider loop (mocked client)
class _FakeMessages:
    def __init__(self):
        self.calls = 0

    def create(self, **kw):
        self.calls += 1
        assert kw["model"] == "claude-opus-5-5"
        assert kw["fallbacks"] == "default" and kw["betas"] == ["server-side-fallback-2026-07-01"]
        assert kw["output_config"]["format"]["type"] == "json_schema"
        if self.calls == 1:
            return SimpleNamespace(stop_reason="tool_use", content=[
                SimpleNamespace(type="tool_use", id="tu_1", name="diagnose_ticket",
                                input={"text": "Outlook keeps crashing", "device_id": "DEV-0002", "week": 6})])
        # second call must carry the tool result back
        last = kw["messages"][-1]
        assert last["role"] == "user" and last["content"][0]["type"] == "tool_result"
        import json
        payload = {k: ([] if v["type"] == "array" else 90 if v["type"] == "integer" else "x")
                   for k, v in RESPONSE_SCHEMA["properties"].items()}
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(payload))])


def test_anthropic_provider_tool_loop(store):
    from app.copilot.provider_anthropic import AnthropicCopilot
    fake = SimpleNamespace(beta=SimpleNamespace(messages=_FakeMessages()))
    cop = AnthropicCopilot(api_key="k", model="claude-opus-5-5", timeout=5, client=fake)
    data, trace = cop.run("Why does Outlook crash?")
    assert data["confidence"] == 90
    assert trace[0]["tool"] == "diagnose_ticket" and not trace[0]["is_error"]


def test_anthropic_refusal_falls_back(store, monkeypatch):
    from app.copilot import agent
    from app.copilot.provider_anthropic import AnthropicCopilot, CopilotProviderError

    class Refuser:
        model = "claude-opus-5-5"

        def run(self, *a, **k):
            raise CopilotProviderError("The model declined this request")

    monkeypatch.setattr(agent, "_llm_provider", lambda name: Refuser())
    out = agent.ask("Fleet overview?", provider="anthropic")
    assert out["provider"] == "template" and "declined" in out["fallback_reason"]
    assert AnthropicCopilot  # imported for coverage of module import
