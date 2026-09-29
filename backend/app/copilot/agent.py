"""DEX Copilot orchestrator: provider selection, graceful fallback, audit logging."""
from __future__ import annotations

import logging
import time

from .. import db
from ..config import get_settings
from .prompts import RESPONSE_SCHEMA, build_user_message
from .provider_anthropic import AnthropicCopilot, CopilotProviderError
from .provider_template import TemplateCopilot

log = logging.getLogger(__name__)


def resolve_provider_name() -> str:
    s = get_settings()
    p = (s.llm_provider or "auto").lower()
    if p == "auto":
        if s.anthropic_api_key:
            return "anthropic"
        if s.azure_openai_endpoint and s.azure_openai_api_key and s.azure_openai_deployment:
            return "azure_openai"
        return "template"
    return p


def _llm_provider(name: str):
    s = get_settings()
    if name == "anthropic":
        return AnthropicCopilot(s.anthropic_api_key, s.anthropic_model, s.llm_timeout_sec, s.anthropic_effort)
    if name == "azure_openai":
        from .provider_azure import AzureOpenAICopilot
        return AzureOpenAICopilot(s.azure_openai_endpoint, s.azure_openai_api_key, s.azure_openai_deployment,
                                  s.azure_openai_api_version, s.llm_timeout_sec)
    return None


def _normalise(data: dict) -> dict:
    """Guarantee every schema field is present with the right type."""
    out = {}
    for k, spec in RESPONSE_SCHEMA["properties"].items():
        v = data.get(k)
        if spec["type"] == "array":
            out[k] = [str(x) for x in v] if isinstance(v, list) else ([] if v is None else [str(v)])
        elif spec["type"] == "integer":
            try:
                out[k] = max(0, min(100, int(v)))
            except (TypeError, ValueError):
                out[k] = 0
        else:
            out[k] = "" if v is None else str(v)
    return out


def ask(question: str, device_id: str | None = None, ticket_text: str | None = None,
        week: int | None = None, history: list[dict] | None = None, provider: str | None = None) -> dict:
    started = time.perf_counter()
    name = provider or resolve_provider_name()
    fallback_reason = None
    model = TemplateCopilot.model
    llm = _llm_provider(name) if name != "template" else None
    try:
        if llm is None:
            name = "template"
            raise LookupError
        data, trace = llm.run(build_user_message(question, device_id, ticket_text, week), history)
        model = llm.model
    except LookupError:
        data, trace = TemplateCopilot().run(question, device_id, ticket_text, week)
    except CopilotProviderError as e:
        log.warning("copilot provider %s failed, falling back to template: %s", name, e)
        fallback_reason = str(e)
        name = "template"
        data, trace = TemplateCopilot().run(question, device_id, ticket_text, week)
    latency = int((time.perf_counter() - started) * 1000)
    response = _normalise(data)
    result = {"provider": name, "model": model, "latency_ms": latency, "fallback_reason": fallback_reason,
              "response": response, "tool_calls": trace}
    try:
        db.log_copilot(name, device_id, question, response, latency)
    except Exception:  # audit logging must never break the answer
        log.exception("failed to log copilot call")
    return result
