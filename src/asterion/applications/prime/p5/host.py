"""Runtime-host Protocol + frozen dataclasses for native P5 propose/verify/repair.

The P5 operator exercises the host surface in a single process: open a root
session, run one propose/verify/repair loop until it terminates, and exit.
There is no cross-process continuation and no recovery semantics — those belong
to P4's ``prime.continuity-store`` host service and are not part of P5's
contract. P5 has no recovery.

This module mirrors P3 / P4's ``host.py`` shape (one ``@runtime_checkable``
Protocol plus frozen dataclasses), but with P5's load-bearing surface:
``run_loop`` + ``report_loop_stopped`` instead of P3's ``run_root`` /
``report_admission_refused`` and P4's ``commit_checkpoint`` /
``wait_recovery``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping, Protocol, runtime_checkable

from asterion.runtime.host import CancellationSignal


# Closed 5-element terminal_reason enum. Mirror of P3's refusal enum: any
# new code is a breaking change and must be added here (and to the witness
# assertion) before it appears in a runtime result.
P5TerminalReason = Literal[
    "success",
    "iteration-cap-exceeded",
    "duration-cap-exceeded",
    "no-progress",
    "cancelled",
]


@dataclass(frozen=True, slots=True)
class P5LoopCall:
    """Inputs of one ``run_loop`` invocation against the injected host."""

    root_run_id: str


@dataclass(frozen=True, slots=True)
class P5LoopResult:
    """Outputs of one ``run_loop`` invocation.

    ``root_generation`` is always 1 — P5 has no continuity. ``propose_step_count``
    and ``verify_step_count`` are >= 1 by the spec witness; ``repair_step_count``
    is >= 0. ``failed_verify_count`` is the closed metric the oracle keys on
    (>= 1). ``joined_workspace_digest`` is the closed digest the runtime seals
    over the final joined workspace; ``receipt_sha256`` is the canonical-JSON
    seal digest.
    """

    root_run_id: str
    root_generation: int
    propose_step_count: int
    verify_step_count: int
    repair_step_count: int
    failed_verify_count: int
    terminal_reason: P5TerminalReason
    joined_workspace_digest: str
    receipt_sha256: str


@dataclass(frozen=True, slots=True)
class P5StoppedResult:
    """Record of a loop that did not succeed.

    ``terminal_reason`` is the closed 5-element enum. ``elapsed_ms`` is the
    wall-clock duration the operator observed; ``last_step_timed_out`` flags
    a duration-cap stop on a single step.
    """

    terminal_reason: P5TerminalReason
    root_run_id: str
    elapsed_ms: int
    last_step_timed_out: bool


@dataclass(frozen=True, slots=True)
class P5Finalization:
    """Cleanup-gated terminal classification transferred to the runtime.

    Mirrors P3 / P4's finalization shape: ``completed`` carries the sealed
    receipt digest; ``stopped`` / ``recovery-required`` carry ``None`` on the
    digest field (but ``receipt_sha256`` is closed-typed as ``str`` here because
    P5's loop result is always receipted by the loop service before the
    host transfers final status).
    """

    terminal_status: Literal["completed", "stopped", "recovery-required"]
    receipt_sha256: str


@runtime_checkable
class P5RuntimeHost(Protocol):
    """Protocol surface the P5 operator exercises against a built runtime.

    Four methods, mirroring P3 / P4's shape but scoped to the
    propose/verify/repair loop:

    - ``validate_runtime_services`` — pre-execution capability check.
    - ``run_loop`` — open the root session, run the loop, return the sealed
      loop result (terminal_reason may be success or any of the four stop
      reasons).
    - ``report_loop_stopped`` — non-blocking record of a closed-enum stop
      reason so the host service can keep iteration / duration / progress /
      cancellation observability without leaking private state.
    - ``wait_finalization`` — block until the runtime transfers terminal
      status to the host.
    """

    def validate_runtime_services(self, services: Mapping[str, object]) -> None: ...

    async def run_loop(
        self,
        *,
        root_run_id: str,
        signal: CancellationSignal,
    ) -> P5LoopResult: ...

    def report_loop_stopped(
        self,
        *,
        terminal_reason: P5TerminalReason,
        root_run_id: str,
    ) -> None: ...

    async def wait_finalization(
        self, *, signal: CancellationSignal
    ) -> P5Finalization: ...


__all__ = (
    "P5Finalization",
    "P5LoopCall",
    "P5LoopResult",
    "P5RuntimeHost",
    "P5StoppedResult",
    "P5TerminalReason",
)