"""P6's deterministic six-turn DeepSeek payload contract."""

from __future__ import annotations

from collections.abc import Mapping

P6_PROVIDER_CALLBACK_LIMIT = 6
P6_PROVIDER_INPUT_LIMIT = 49_152
P6_PROVIDER_OUTPUT_LIMIT = 3_456
P6_PROVIDER_COST_LIMIT = 30_000
P6_PROVIDER_DEADLINE_SECONDS = 180
P6_PROVIDER_OUTPUT_LIMITS = (1024, 128, 1024, 128, 1024, 128)


class PrimeP6DevelopmentSdkProviderError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P6 development SDK provider is unavailable")


def _deepseek_payload(request: Mapping[str, object], model_id: str, max_output: int, *, turn: int) -> dict[str, object]:
    if type(request) is not dict or type(model_id) is not str or not model_id or type(turn) is not int or turn not in range(P6_PROVIDER_CALLBACK_LIMIT) or max_output != P6_PROVIDER_OUTPUT_LIMITS[turn]:
        raise ValueError
    context = request.get("context")
    if type(context) is not dict or type(context.get("systemPrompt")) is not str or type(context.get("messages")) is not list or type(context.get("tools")) is not list or len(context["tools"]) != 1 or type(context["tools"][0]) is not dict:
        raise ValueError
    tool = context["tools"][0]
    if tool.get("name") != "ipython" or type(tool.get("description")) is not str or type(tool.get("parameters")) is not dict:
        raise ValueError
    messages = [{"role": "system", "content": context["systemPrompt"]}]
    for item in context["messages"]:
        if type(item) is not dict or item.get("role") not in {"user", "assistant", "tool"}:
            raise ValueError
        messages.append(dict(item))
    return {"model": model_id, "messages": messages, "max_tokens": max_output, "stream": False, "temperature": 0, "thinking": {"type": "disabled"}, "tools": [{"type": "function", "function": {"name": "ipython", "description": tool["description"], "parameters": tool["parameters"]}}], "tool_choice": {"type": "function", "function": {"name": "ipython"}} if turn in (0, 2, 4) else "none"}


__all__ = ("P6_PROVIDER_CALLBACK_LIMIT", "P6_PROVIDER_INPUT_LIMIT", "P6_PROVIDER_OUTPUT_LIMIT", "P6_PROVIDER_COST_LIMIT", "P6_PROVIDER_DEADLINE_SECONDS", "P6_PROVIDER_OUTPUT_LIMITS", "PrimeP6DevelopmentSdkProviderError", "_deepseek_payload")
