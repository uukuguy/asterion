"""Narrow, replay-free P4 gateway recovery adapter."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import cast

from asterion.applications.prime_agent.operator.diagnostic_session_recovery_workload import (
    P4_DIAGNOSTIC_RECOVERY_MODEL_SHA256,
    P4_DIAGNOSTIC_RECOVERY_ORACLE_SHA256,
    P4_DIAGNOSTIC_RECOVERY_WORKLOAD_DIGEST,
)


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


class DiagnosticSessionRecoveryAdapterError(ValueError):
    """Raised without exposing gateway-private recovery values."""


@dataclass(frozen=True, repr=False)
class DiagnosticRecoveryCheckpoint:
    workload_sha256: str
    root_artifact_sha256: str
    child_registry_sha256: str
    oracle_sha256: str
    model_sha256: str
    cursor_sha256: str


@dataclass(frozen=True, repr=False)
class DiagnosticRecoveryGatewayState:
    session_sha256: str
    transcript_sha256: str
    cursor_sha256: str
    supervisor_generation: int
    recovery_required: bool
    compaction_on_active_path: bool
    durable_assets_only: bool
    uncertain_effect_fenced: bool


_STATE_FIELDS = frozenset(DiagnosticRecoveryGatewayState.__dataclass_fields__)


def _digest(value: object) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def _valid_state(value: object) -> bool:
    return (
        type(value) is DiagnosticRecoveryGatewayState
        and frozenset(vars(value)) == _STATE_FIELDS
        and all(_digest(getattr(value, name)) for name in (
            "session_sha256", "transcript_sha256", "cursor_sha256",
        ))
        and type(value.supervisor_generation) is int
        and value.supervisor_generation >= 0
    )


def _valid_checkpoint(value: object) -> bool:
    return (
        type(value) is DiagnosticRecoveryCheckpoint
        and value.workload_sha256 == P4_DIAGNOSTIC_RECOVERY_WORKLOAD_DIGEST
        and value.oracle_sha256 == P4_DIAGNOSTIC_RECOVERY_ORACLE_SHA256
        and value.model_sha256 == P4_DIAGNOSTIC_RECOVERY_MODEL_SHA256
        and all(_digest(getattr(value, name)) for name in (
            "root_artifact_sha256", "child_registry_sha256", "cursor_sha256",
        ))
    )


async def recover_diagnostic_session(
    gateway: object,
    checkpoint: object,
    before_detach: object,
) -> DiagnosticRecoveryGatewayState:
    """Perform the one sealed detach, attach, and compact recovery sequence."""

    try:
        if not _valid_checkpoint(checkpoint) or not _valid_state(before_detach):
            raise ValueError
        typed_checkpoint = cast(DiagnosticRecoveryCheckpoint, checkpoint)
        typed_before = cast(DiagnosticRecoveryGatewayState, before_detach)
        if typed_before.recovery_required:
            raise ValueError
        detached = await gateway.detach()  # type: ignore[union-attr]
        attached = await gateway.attach(typed_checkpoint.cursor_sha256)  # type: ignore[union-attr]
        compacted = await gateway.compact()  # type: ignore[union-attr]
        states = (detached, attached, compacted)
        if not all(_valid_state(state) for state in states):
            raise ValueError
        typed_detached, typed_attached, typed_compacted = (
            cast(DiagnosticRecoveryGatewayState, state) for state in states
        )
        if (
            any(
                state.session_sha256 != typed_before.session_sha256
                or state.transcript_sha256 != typed_before.transcript_sha256
                for state in (typed_detached, typed_attached, typed_compacted)
            )
            or typed_attached.cursor_sha256 != typed_checkpoint.cursor_sha256
            or typed_compacted.supervisor_generation <= typed_before.supervisor_generation
            or typed_compacted.recovery_required is not True
            or typed_compacted.compaction_on_active_path is not True
            or typed_compacted.durable_assets_only is not True
            or typed_compacted.uncertain_effect_fenced is not True
        ):
            raise ValueError
        return typed_compacted
    except (AttributeError, TypeError, ValueError):
        raise DiagnosticSessionRecoveryAdapterError(
            "diagnostic session recovery is invalid"
        ) from None
