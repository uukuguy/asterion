"""Runtime-host Protocol + frozen dataclasses for native P3 recursive workflow.

The P3 operator exercises the host surface in a single process: open a root
session, admit one child at depth=2, join the child's result, and exit. There
is no cross-process continuation and no recovery semantics — those belong to
P4's `prime.continuity-store` host service and are not part of P3's contract.

This module mirrors P4's `host.py` shape (one ``@runtime_checkable`` Protocol
plus frozen dataclasses), but with P3's load-bearing surface: ``run_root`` +
``report_admission_refused`` instead of P4's ``commit_checkpoint`` /
``wait_recovery``. P3 has no recovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping, Protocol, runtime_checkable

from asterion.agents.prime.state import PrimeBackendIdentity
from asterion.runtime.host import CancellationSignal


@dataclass(frozen=True, slots=True)
class P3RootCall:
    """Inputs of one ``run_root`` invocation against the injected host."""

    parent_run_id: str
    child_request: "P3ChildRequest | None"


@dataclass(frozen=True, slots=True)
class P3RootResult:
    """Outputs of one ``run_root`` invocation.

    ``joined_result_sha256`` is the closed digest the runtime seals; it is
    non-null whether the child was admitted (joined over root + child) or
    refused (joined over root alone with a refusal code). ``refusal_reason``
    is the closed enum string from ``P3AdmissionRefused.refusal_reason`` when
    admission was refused, otherwise ``None``.
    """

    root_run_id: str
    root_generation: int
    child_run_id: str | None
    child_generation: int | None
    child_result_sha256: str | None
    joined_result_sha256: str
    depth_reached: int
    refusal_reason: str | None


@dataclass(frozen=True, slots=True)
class P3ChildRequest:
    """One child-runner admission request the root forwards.

    ``child_identity`` is the next-generation ``PrimeBackendIdentity`` the
    operator derived from the root via ``bump_generation()``. At the public
    surface the ``private_root_identity`` field is redacted by the host
    service; the internal surface still carries the full identity so the
    runner can authorize the admission. ``task_kind`` is a closed enum:
    ``"synthetic"`` for the deterministic fake-worker witness path and
    ``"child-of-synthetic"`` for child-of-child paths (reserved).
    """

    child_run_id: str
    child_identity: PrimeBackendIdentity
    parent_run_id: str
    depth: int
    task_kind: str
    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class P3AdmissionRefused:
    """Record of a refused child admission.

    ``refusal_reason`` is the closed enum consumed by P5/P6 and asserted by
    ``make asterion-prime-p3-run-limits``: any new code is a breaking change.
    """

    refusal_reason: Literal[
        "depth-exceeded",
        "concurrency-exceeded",
        "budget-exceeded",
        "cancelled",
        "session-backend-rejected",
    ]
    attempted_depth: int
    attempted_at: str


@dataclass(frozen=True, slots=True)
class P3Finalization:
    """Cleanup-gated terminal classification transferred to the runtime.

    Mirrors P4's ``P4Finalization`` shape: completed carries the sealed
    receipt digest; refused / recovery-required carry ``None``. P3 has no
    "budget-limited" / "cancelled" branch — the runtime sees either a
    completed admission, a refused admission, or a recovery-required
    stop on the root side.
    """

    terminal_status: Literal["completed", "refused", "recovery-required"]
    receipt_sha256: str | None


@runtime_checkable
class P3RuntimeHost(Protocol):
    """Protocol surface the P3 operator exercises against a built runtime.

    Four methods, mirroring P4's shape but without recovery:

    - ``validate_runtime_services`` — pre-execution capability check.
    - ``run_root`` — open the root session, admit/join the child, return the
      sealed root result.
    - ``report_admission_refused`` — non-blocking record of a closed-enum
      refusal code so the host service can keep depth / concurrency /
      budget / cancellation observability without leaking private state.
    - ``wait_finalization`` — block until the runtime transfers terminal
      status to the host.
    """

    def validate_runtime_services(self, services: Mapping[str, object]) -> None: ...

    async def run_root(
        self,
        *,
        parent_run_id: str,
        child_request: P3ChildRequest | None,
        signal: CancellationSignal,
    ) -> P3RootResult: ...

    def report_admission_refused(
        self,
        *,
        refusal: P3AdmissionRefused,
    ) -> None: ...

    async def wait_finalization(
        self, *, signal: CancellationSignal
    ) -> P3Finalization: ...


__all__ = (
    "P3AdmissionRefused",
    "P3ChildRequest",
    "P3Finalization",
    "P3RootCall",
    "P3RootResult",
    "P3RuntimeHost",
)
