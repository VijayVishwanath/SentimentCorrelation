"""DEX Copilot on the Claude API — manual agentic tool-use loop with structured output.

A manual loop (rather than the beta tool runner) keeps the tool registry
provider-neutral and lets us capture a tool-call trace for the UI.

Every request runs on the one configured model (Claude Sonnet 5.5). Server-side fallbacks are deliberately
not enabled, so a declined request is never re-run on another model; the agent answers from the grounded
template engine instead and says so.
"""
from __future__ import annotations

import json
import logging

import anthropic

from .prompts import RESPONSE_SCHEMA, SYSTEM_PROMPT
from .tools import TOOLS, run_tool

log = logging.getLogger(__name__)

MAX_STEPS = 8
MODEL = "claude-sonnet-5-5"  # Claude Sonnet 5.5 is the only model the Copilot uses


class CopilotProviderError(RuntimeError):
    pass


class AnthropicCopilot:
    name = "anthropic"

    def __init__(self, api_key: str | None, timeout: float, effort: str = "medium", client=None):
        self.model = MODEL
        self.effort = effort
        self.client = client or anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=2)
        self.tools = [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in TOOLS]

    def run(self, user_message: str, history: list[dict] | None = None) -> tuple[dict, list[dict]]:
        messages: list = [*(history or []), {"role": "user", "content": user_message}]
        trace: list[dict] = []
        for _ in range(MAX_STEPS):
            try:
                resp = self.client.messages.create(
                    model=self.model,
                    max_tokens=16000,
                    system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                    tools=self.tools,
                    messages=messages,
                    output_config={"effort": self.effort,
                                   "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
                )
            except anthropic.AuthenticationError as e:
                raise CopilotProviderError("Claude API authentication failed — check ANTHROPIC_API_KEY") from e
            except anthropic.RateLimitError as e:
                raise CopilotProviderError("Claude API rate limit reached — retry shortly") from e
            except anthropic.APIStatusError as e:
                raise CopilotProviderError(f"Claude API error {e.status_code}: {e.message}") from e
            except anthropic.APIConnectionError as e:
                raise CopilotProviderError("Could not reach the Claude API") from e

            if resp.stop_reason == "refusal":
                raise CopilotProviderError("The model declined this request")
            if resp.stop_reason == "max_tokens":
                raise CopilotProviderError("Response exceeded the token limit")

            if resp.stop_reason in ("tool_use", "pause_turn"):
                messages.append({"role": "assistant", "content": resp.content})
                if resp.stop_reason == "pause_turn":
                    continue
                results = []
                for block in resp.content:
                    if block.type != "tool_use":
                        continue
                    out, is_err = run_tool(block.name, block.input if isinstance(block.input, dict) else {})
                    trace.append({"tool": block.name, "input": block.input, "is_error": is_err,
                                  "output_preview": out[:300]})
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": out,
                                    **({"is_error": True} if is_err else {})})
                messages.append({"role": "user", "content": results})  # all results in one message
                continue

            text = next((b.text for b in resp.content if b.type == "text"), "")
            try:
                data = json.loads(text)
            except json.JSONDecodeError as e:
                raise CopilotProviderError("Model returned malformed JSON") from e
            log.info("copilot(anthropic) finished in %d tool calls", len(trace))
            return data, trace
        raise CopilotProviderError(f"Copilot did not finish within {MAX_STEPS} steps")
