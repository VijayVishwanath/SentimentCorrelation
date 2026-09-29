"""DEX Copilot on Azure OpenAI — alternative provider for tenants standardised on Azure.

Same tool registry, prompt and response schema as the Claude provider.
"""
from __future__ import annotations

import json
import logging

from .prompts import RESPONSE_SCHEMA, SYSTEM_PROMPT
from .provider_anthropic import CopilotProviderError
from .tools import TOOLS, run_tool

log = logging.getLogger(__name__)
MAX_STEPS = 8


class AzureOpenAICopilot:
    name = "azure_openai"

    def __init__(self, endpoint: str, api_key: str, deployment: str, api_version: str, timeout: float, client=None):
        from openai import AzureOpenAI  # imported lazily: optional dependency path

        self.model = deployment
        self.client = client or AzureOpenAI(azure_endpoint=endpoint, api_key=api_key,
                                            api_version=api_version, timeout=timeout, max_retries=2)
        self.tools = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                        "parameters": t.parameters}} for t in TOOLS]

    def run(self, user_message: str, history: list[dict] | None = None) -> tuple[dict, list[dict]]:
        import openai

        messages: list = [{"role": "system", "content": SYSTEM_PROMPT}, *(history or []),
                          {"role": "user", "content": user_message}]
        trace: list[dict] = []
        for _ in range(MAX_STEPS):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model, messages=messages, tools=self.tools,
                    response_format={"type": "json_schema",
                                     "json_schema": {"name": "copilot_response", "schema": RESPONSE_SCHEMA,
                                                     "strict": True}})
            except openai.APIError as e:
                raise CopilotProviderError(f"Azure OpenAI error: {e}") from e
            msg = resp.choices[0].message
            if msg.tool_calls:
                messages.append({"role": "assistant", "content": msg.content or "",
                                 "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    out, is_err = run_tool(tc.function.name, args)
                    trace.append({"tool": tc.function.name, "input": args, "is_error": is_err,
                                  "output_preview": out[:300]})
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": out})
                continue
            try:
                return json.loads(msg.content or ""), trace
            except json.JSONDecodeError as e:
                raise CopilotProviderError("Model returned malformed JSON") from e
        raise CopilotProviderError(f"Copilot did not finish within {MAX_STEPS} steps")
