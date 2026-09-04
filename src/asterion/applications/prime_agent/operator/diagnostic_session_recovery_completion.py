"""Strict parser for the fixed P4 diagnostic-recovery completion."""
from __future__ import annotations
from dataclasses import dataclass
import json
from asterion.applications.prime_agent.diagnostic_session_recovery_receipt import DiagnosticSessionRecoveryReceiptError, DiagnosticSessionRecoveryTrace, validate_diagnostic_session_recovery_trace

class DiagnosticSessionRecoveryCompletionError(ValueError):
    pass

@dataclass(frozen=True, repr=False)
class DiagnosticSessionRecoveryCompletion:
    trace: DiagnosticSessionRecoveryTrace
    def __repr__(self) -> str:
        return "DiagnosticSessionRecoveryCompletion(redacted)"

_FIELDS = frozenset({"format", *DiagnosticSessionRecoveryTrace.__dataclass_fields__})
def parse_diagnostic_session_recovery_completion(payload: object) -> DiagnosticSessionRecoveryCompletion:
    try:
        if type(payload) is not dict or frozenset(payload) != _FIELDS or payload["format"] != "asterion.prime-diagnostic-session-recovery/v1":
            raise ValueError
        values = {key: value for key, value in payload.items() if key != "format"}
        for key in ("root_tool_names", "child_tool_names"):
            if type(values[key]) is not list or values[key] != ["ipython"]:
                raise ValueError
            values[key] = ("ipython",)
        trace = DiagnosticSessionRecoveryTrace(**values)
        validate_diagnostic_session_recovery_trace(trace)
        return DiagnosticSessionRecoveryCompletion(trace)
    except (KeyError, TypeError, ValueError, DiagnosticSessionRecoveryReceiptError):
        raise DiagnosticSessionRecoveryCompletionError("diagnostic session recovery completion is invalid") from None


def canonical_diagnostic_session_recovery_completion_bytes(
    completion: DiagnosticSessionRecoveryCompletion,
) -> bytes:
    """Render the only accepted, body-bounded P4 completion encoding."""
    if type(completion) is not DiagnosticSessionRecoveryCompletion:
        raise DiagnosticSessionRecoveryCompletionError(
            "diagnostic session recovery completion is invalid"
        )
    trace = completion.trace
    payload: dict[str, object] = {
        "format": "asterion.prime-diagnostic-session-recovery/v1"
    }
    payload.update(vars(trace))
    payload["root_tool_names"] = list(trace.root_tool_names)
    payload["child_tool_names"] = list(trace.child_tool_names)
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
