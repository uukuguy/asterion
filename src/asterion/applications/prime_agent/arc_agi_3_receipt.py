"""Closed redacted evidence trace for Prime P7 ARC-AGI-3."""

from __future__ import annotations

from dataclasses import dataclass
import re

from asterion.applications.prime_agent.operator.arc_agi_3_workload import (
    P7_ARC_AGI_3_ACTION_CEILING,
    P7_ARC_AGI_3_MODEL_SHA256,
    P7_ARC_AGI_3_ORACLE_SHA256,
    P7_ARC_AGI_3_SCHEMA_SHA256,
    P7_ARC_AGI_3_USAGE_CEILING,
    P7_ARC_AGI_3_WORKLOAD_DIGEST,
)


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_TRACE_FIELDS = frozenset({
    "workload_sha256", "initial_observation_sha256", "action_chain_sha256",
    "terminal_status_sha256", "score_sha256", "oracle_sha256", "model_sha256",
    "schema_sha256", "tool_names", "game_count", "first_broker_sequence",
    "last_broker_sequence", "broker_call_count", "observation_count",
    "action_count", "status_count", "usage_count", "terminal", "score_replayed",
    "disposed", "reaped",
})
_DIGEST_FIELDS = frozenset(name for name in _TRACE_FIELDS if name.endswith("_sha256"))


class ArcAgi3ReceiptError(ValueError):
    """Raised when P7 facts cannot support a public capability claim."""


@dataclass(frozen=True, repr=False)
class ArcAgi3Trace:
    workload_sha256: str
    initial_observation_sha256: str
    action_chain_sha256: str
    terminal_status_sha256: str
    score_sha256: str
    oracle_sha256: str
    model_sha256: str
    schema_sha256: str
    tool_names: tuple[str]
    game_count: int
    first_broker_sequence: int
    last_broker_sequence: int
    broker_call_count: int
    observation_count: int
    action_count: int
    status_count: int
    usage_count: int
    terminal: bool
    score_replayed: bool
    disposed: bool
    reaped: bool

    def __repr__(self) -> str:
        return "ArcAgi3Trace(redacted)"


def validate_arc_agi_3_trace(trace: object) -> None:
    """Validate a single-game P7 causal trace without issuing evidence."""

    try:
        if (
            type(trace) is not ArcAgi3Trace
            or frozenset(vars(trace)) != _TRACE_FIELDS
            or any(
                type(getattr(trace, name)) is not str
                or _DIGEST.fullmatch(getattr(trace, name)) is None
                for name in _DIGEST_FIELDS
            )
            or trace.workload_sha256 != P7_ARC_AGI_3_WORKLOAD_DIGEST
            or trace.model_sha256 != P7_ARC_AGI_3_MODEL_SHA256
            or trace.oracle_sha256 != P7_ARC_AGI_3_ORACLE_SHA256
            or trace.schema_sha256 != P7_ARC_AGI_3_SCHEMA_SHA256
            or trace.tool_names != ("ipython",)
            or type(trace.game_count) is not int or trace.game_count != 1
            or type(trace.first_broker_sequence) is not int
            or trace.first_broker_sequence != 1
            or type(trace.last_broker_sequence) is not int
            or type(trace.broker_call_count) is not int
            or not 1 <= trace.broker_call_count <= 8
            or trace.last_broker_sequence != trace.broker_call_count
            or type(trace.observation_count) is not int or trace.observation_count < 1
            or type(trace.action_count) is not int
            or not 1 <= trace.action_count <= P7_ARC_AGI_3_ACTION_CEILING
            or type(trace.status_count) is not int or trace.status_count < 1
            or trace.observation_count + trace.action_count + trace.status_count
            != trace.broker_call_count
            or type(trace.usage_count) is not int
            or not 1 <= trace.usage_count <= P7_ARC_AGI_3_USAGE_CEILING
            or any(
                getattr(trace, name) is not True
                for name in ("terminal", "score_replayed", "disposed", "reaped")
            )
        ):
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        raise ArcAgi3ReceiptError("ARC-AGI-3 trace is invalid") from None
