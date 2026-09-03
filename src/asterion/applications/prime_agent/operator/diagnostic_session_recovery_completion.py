"""Strict parser for the fixed P4 diagnostic-recovery completion."""
from __future__ import annotations
from dataclasses import dataclass
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
