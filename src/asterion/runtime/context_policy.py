"""Caller-supplied context bounds for an application runtime."""

from __future__ import annotations

import json
from collections.abc import Mapping
from types import MappingProxyType


CONTEXT_POLICY_FIELDS = (
    "compact_chars",
    "retain_turns",
    "summary_failures",
    "summary_tokens",
    "tool_result_chars",
)


class ContextPolicyError(ValueError):
    """Raised when an application context policy is not one exact bound set."""


def parse_context_policy(value: str | None) -> Mapping[str, int] | None:
    """Accept one canonical bound object, or no policy."""

    if value is None:
        return None
    if type(value) is not str:
        raise ContextPolicyError("context policy is invalid")
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        raise ContextPolicyError("context policy is invalid") from None
    if (
        type(payload) is not dict
        or not payload
        or any(type(key) is not str or key not in CONTEXT_POLICY_FIELDS for key in payload)
    ):
        raise ContextPolicyError("context policy is invalid")
    parsed: dict[str, int] = {}
    for key in CONTEXT_POLICY_FIELDS:
        if key not in payload:
            continue
        item = payload[key]
        if isinstance(item, bool) or type(item) is not int or item <= 0:
            raise ContextPolicyError("context policy is invalid")
        parsed[key] = item
    compact = "compact_chars" in parsed
    retain = "retain_turns" in parsed
    summary = "summary_tokens" in parsed
    failures = "summary_failures" in parsed
    if compact != retain or summary != failures or (summary and not compact):
        raise ContextPolicyError("context policy is invalid")
    if "tool_result_chars" not in parsed and not compact:
        raise ContextPolicyError("context policy is invalid")
    canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    if canonical != value:
        raise ContextPolicyError("context policy is invalid")
    return MappingProxyType(parsed)
