"""Operator-owned native P5 bounded-autonomy witness.

Single-mode operator: reads ``ASTERION_PRIME_P5_MODE`` and dispatches to
either the success path (``"success"``) or the three-scenario limits
path (``"limits"``). There is no commit/recover split — P5 owns one
bounded root run per invocation, so the operator reads either mode and
emits one JSON record (success) or three JSON records (limits, one per
refused scenario).

The Makefile targets ``asterion-prime-p5-run`` and
``asterion-prime-p5-run-limits`` (Task 9) will invoke the operator in
``success`` and ``limits`` mode respectively. The fake-worker contract
is deterministic: given ``(mode, step_kind, run_id)`` the same workspace
SHA is produced across host runs. No real Pi subprocess is involved on
this path; the operator is itself the host service owner, mirroring
P3's pattern.

Per D-2026-09-19-01: cancellation is a closed-enum value of the
``terminal_reason`` field but is NOT a separately-asserted witness
record. The limits path emits exactly three records (one per scenario
that produces a non-success closed-enum value: iteration-cap,
duration-cap, no-progress), not four. The success path emits exactly
one record.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys

from asterion.agents.prime.state import PrimeBackendIdentity
from asterion.agents.prime.store import private_root_identity
from asterion.applications.prime.p5.oracle import P5Oracle
from asterion.applications.prime.p5.receipt import seal as seal_receipt
from asterion.applications.prime.services import (
    BoundedAutonomyLoop,
    P5ProposeStep,
    P5RepairStep,
    P5VerifyStep,
    create_bounded_autonomy_host_service,
)
from asterion.services.progress import NOOP_HOST_PROGRESS_REPORTER
from asterion.services.presentation import NOOP_HOST_PRESENTATION_SINK
from asterion.services.registry import HostServiceFactoryContext


_OPERATOR_ROOT_ENV = "ASTERION_PRIME_OPERATOR_ROOT"
_PI_ENTRY_ENV = "ASTERION_PRIME_PI_ENTRY"
_PRIVATE_ROOT_ENV = "ASTERION_PRIME_P5_PRIVATE_ROOT"
_MODE_ENV = "ASTERION_PRIME_P5_MODE"


class P5OperatorError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("P5 operator is unavailable")


# ---------------------------------------------------------------------------
# Public result shapes (one JSON record per root run)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class P5PublicResult:
    """Success-path public result.

    ``status`` is ``"completed"`` when the bounded-autonomy loop admitted
    a propose step, observed exactly one verify failure followed by one
    repair step, and terminated with ``terminal_reason="success"``. All
    other fields are content-safe projections of the sealed receipt plus
    a constant ``private_root_redacted=True`` marker; no prompts, paths,
    or worker output is exposed.
    """

    status: str
    root_run_id: str
    root_generation: int
    propose_step_count: int
    verify_step_count: int
    repair_step_count: int
    failed_verify_count: int
    terminal_reason: str
    joined_workspace_digest: str
    receipt_sha256: str
    private_root_redacted: bool = True


@dataclass(frozen=True, slots=True)
class P5LimitsRecord:
    """Limits-path refusal record (one per refused scenario).

    Per D-2026-09-19-01 cancellation folds into the closed
    ``terminal_reason`` enum but is NOT a separately-asserted witness
    record; the limits path emits exactly three of these (iteration-cap /
    duration-cap / no-progress), not four.
    """

    status: str
    scenario: str
    terminal_reason: str
    verify_step_count: int | None
    repair_step_count: int | None
    failed_verify_count: int | None
    last_step_timed_out: bool | None
    joined_workspace_digest: str | None
    receipt_sha256: str
    private_root_redacted: bool = True


# ---------------------------------------------------------------------------
# Pre-flight dataclass + env-var parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Preflight:
    operator_root: Path
    worker_python: Path
    private_root: Path
    mode: str
    pi_entry: Path | None


_VALID_MODES: frozenset[str] = frozenset({"success", "limits"})


def _preflight(environment: Mapping[str, str]) -> _Preflight:
    """Validate env vars and runtime preflight. Raises P5OperatorError on miss."""

    operator_value = environment.get(_OPERATOR_ROOT_ENV, "").strip()
    private_value = environment.get(_PRIVATE_ROOT_ENV, "").strip()
    mode_value = environment.get(_MODE_ENV, "").strip()
    if (
        not operator_value
        or not private_value
        or mode_value not in _VALID_MODES
    ):
        raise P5OperatorError()
    try:
        operator_root = Path(operator_value).resolve(strict=True)
    except OSError:
        raise P5OperatorError() from None
    if not operator_root.is_dir():
        raise P5OperatorError()
    worker_python = Path(sys.executable).absolute()
    if not worker_python.is_file():
        raise P5OperatorError()
    try:
        probe = subprocess.run(
            (str(worker_python), "-I", "-c", "import sys; print(sys.version_info[:2])"),
            check=True,
            capture_output=True,
            timeout=10,
            env={"LANG": "C.UTF-8"},
        )
    except (OSError, subprocess.SubprocessError):
        raise P5OperatorError() from None
    if not probe.stdout or not probe.stdout.strip():
        raise P5OperatorError()
    try:
        private_root = Path(private_value).resolve()
    except OSError:
        raise P5OperatorError() from None
    pi_entry: Path | None = None
    raw_pi = environment.get(_PI_ENTRY_ENV, "").strip()
    if raw_pi:
        try:
            pi_entry = Path(raw_pi).resolve(strict=False)
        except OSError:
            raise P5OperatorError() from None
    return _Preflight(
        operator_root=operator_root,
        worker_python=worker_python,
        private_root=private_root,
        mode=mode_value,
        pi_entry=pi_entry,
    )


# ---------------------------------------------------------------------------
# Identity construction
# ---------------------------------------------------------------------------


# Default runtime-binding SHAs. Same fixture-pinning approach as P3 / P4:
# satisfy the SHA-256 shape required by PrimeBackendIdentity's
# validator while keeping the no-replay witness reproducible across
# host runs. In production these come from the operator's
# preflighted bound runtime; on the witness path they are pinned.
_DEFAULT_PI_SHA = sha256(b"prime.pi-native").hexdigest()
_DEFAULT_EXTENSION_SHA = sha256(b"prime.extension").hexdigest()
_DEFAULT_CEILINGS_SHA = sha256(b"prime.ceilings").hexdigest()


def _build_identity(
    *,
    private_root: Path,
    generation: int,
    session_id: str,
    continuation_id: str,
    worker_sha: str,
    pi_command_sha256: str = _DEFAULT_PI_SHA,
    extension_binding_fingerprint: str = _DEFAULT_EXTENSION_SHA,
    ceilings_sha256: str = _DEFAULT_CEILINGS_SHA,
) -> PrimeBackendIdentity:
    return PrimeBackendIdentity(
        session_id=session_id,
        generation=generation,
        provider_id="prime-applications",
        application_id="prime.bounded-autonomy",
        application_version="1.0.0",
        runtime_id="asterion.prime",
        pi_command_sha256=pi_command_sha256,
        extension_binding_fingerprint=extension_binding_fingerprint,
        worker_identity_sha256=worker_sha,
        continuation_id=continuation_id,
        private_root_identity=private_root_identity(private_root),
        ceilings_sha256=ceilings_sha256,
    )


# ---------------------------------------------------------------------------
# Deterministic fake-worker payload
# ---------------------------------------------------------------------------


def _fake_worker_payload_sha(*, mode: str, step_kind: str, run_id: str) -> str:
    """Deterministic SHA-256 over ``(mode, step_kind, run_id)``.

    Different tuples produce different SHAs, so the no-replay witness
    and the no-progress dedup check are meaningful by construction. The
    same tuple maps to the same SHA across host runs.
    """

    payload = json.dumps(
        {"mode": mode, "run_id": run_id, "step_kind": step_kind},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _fake_worker_identity_sha(*, mode: str) -> str:
    """Stable per-mode worker identity used by the operator's binding."""

    return sha256(f"p5-deterministic-{mode}".encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Cancellation signal stub
# ---------------------------------------------------------------------------


class _NeverCancelled:
    """A non-cancelling CancellationSignal implementation."""

    @property
    def cancelled(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# Operator resources — host services + identity the operator owns
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _OperatorResources:
    """One preflighted set of operator-owned resources for the P5 witness."""

    mode: str
    private_root: Path
    root_run_id: str
    root_identity: PrimeBackendIdentity
    p5_oracle: P5Oracle
    pi_extension: object
    private_trace: object


async def _open_bounded_autonomy_loop(
    propose_callable: object,
    verify_callable: object,
    repair_callable: object,
) -> BoundedAutonomyLoop:
    """Open a fresh in-process bounded-autonomy loop with the given callables.

    Async: the operator runs every host-service open inside one event
    loop. Each scenario on the limits path opens its own service so
    cached terminal state from one scenario does not bleed into the
    next.
    """

    binding = create_bounded_autonomy_host_service()
    context = HostServiceFactoryContext(
        provider_id="prime-applications",
        application_id="prime.bounded-autonomy",
        application_version="1.0.0",
        capability_id="prime.bounded-autonomy",
        options={},
        progress=NOOP_HOST_PROGRESS_REPORTER,
        presentation=NOOP_HOST_PRESENTATION_SINK,
    )

    async with binding.factory(context) as service:  # type: ignore[arg-type]
        service.set_step_callables(  # type: ignore[attr-defined]
            propose_callable=propose_callable,  # type: ignore[arg-type]
            verify_callable=verify_callable,  # type: ignore[arg-type]
            repair_callable=repair_callable,  # type: ignore[arg-type]
        )
        return service  # type: ignore[return-value]


async def _build_resources(preflight: _Preflight) -> _OperatorResources:
    """Build the host services + identity for one operator invocation."""

    mode = preflight.mode
    private_root = preflight.private_root.resolve()
    private_root.parent.mkdir(parents=True, exist_ok=True)
    # P5 has no cross-process continuation; prior private_root state
    # is irrelevant and may have stale loop controller state. Wipe it.
    if private_root.exists():
        shutil.rmtree(private_root)
    private_root.mkdir(parents=True, exist_ok=True, mode=0o700)

    root_run_id = "p5-root-" + secrets.token_hex(8)
    session_id = "p5-" + secrets.token_hex(8)
    continuation_id = "continuation-" + secrets.token_hex(8)
    worker_sha = _fake_worker_identity_sha(mode=mode)

    root_identity = _build_identity(
        private_root=private_root,
        generation=1,
        session_id=session_id,
        continuation_id=continuation_id,
        worker_sha=worker_sha,
    )
    p5_oracle = P5Oracle()

    return _OperatorResources(
        mode=mode,
        private_root=private_root,
        root_run_id=root_run_id,
        root_identity=root_identity,
        p5_oracle=p5_oracle,
        pi_extension=None,
        private_trace=None,
    )


# ---------------------------------------------------------------------------
# Result sealing — one function per dispatch path
# ---------------------------------------------------------------------------


def _propose_callable_factory(
    *, mode: str, run_id: str
):
    """Build a deterministic propose callable for the given ``run_id``.

    Each call returns a fresh :class:`P5ProposeStep` whose
    ``workspace_digest_sha256`` is the closed-form SHA of
    ``(mode, "propose", run_id)``.
    """

    async def propose(signal):  # noqa: ARG001
        return P5ProposeStep(
            step_id=f"propose-{run_id}",
            workspace_digest_sha256=_fake_worker_payload_sha(
                mode=mode, step_kind="propose", run_id=run_id
            ),
        )

    return propose


def _repair_callable_factory(
    *, mode: str, run_id: str, same_as_propose: bool = False
):
    """Build a deterministic repair callable for the given ``run_id``.

    When ``same_as_propose`` is True every repair call returns the
    propose's digest (the no-progress scenario's contract); otherwise
    each repair call returns a fresh per-invocation digest so
    successive repairs differ and the dedup-adapter does not
    short-circuit before the iteration cap fires.
    """

    state = {"count": 0}
    propose_digest = _fake_worker_payload_sha(
        mode=mode, step_kind="propose", run_id=run_id
    )

    async def repair(signal):  # noqa: ARG001
        state["count"] += 1
        if same_as_propose:
            digest = propose_digest
        else:
            digest = _fake_worker_payload_sha(
                mode=mode,
                step_kind=f"repair-{state['count']}",
                run_id=run_id,
            )
        return P5RepairStep(
            step_id=f"repair-{run_id}-{state['count']}",
            workspace_digest_sha256=digest,
        )

    return repair


def _verify_callable_factory(
    *,
    mode: str,
    run_id: str,
    verdicts: tuple[str, ...],
):
    """Build a deterministic verify callable that emits the given verdict sequence.

    Each call increments an internal counter and returns the next
    verdict from ``verdicts``; once the sequence is exhausted the
    callable emits ``"pass"``. The ``feedback`` is a deterministic
    public-safe projection — never the oracle's verdict stream.
    """

    state = {"index": 0}

    async def verify(signal):  # noqa: ARG001
        idx = state["index"]
        state["index"] += 1
        if idx < len(verdicts):
            verdict = verdicts[idx]
        else:
            verdict = "pass"
        return P5VerifyStep(
            step_id=f"verify-{run_id}-{idx + 1}",
            verdict=verdict,  # type: ignore[arg-type]
            feedback=_fake_worker_payload_sha(
                mode=mode, step_kind=f"verify:{verdict}", run_id=run_id
            ),
        )

    return verify


async def _drive_success(resources: _OperatorResources) -> P5PublicResult:
    """Drive one bounded propose/verify/repair loop end-to-end on the
    success path.

    The success-path witness shape (per the P5 plan spec):

      * ``propose_step_count == 1``
      * ``verify_step_count == 2`` (1 fail, 1 pass)
      * ``repair_step_count == 1``
      * ``failed_verify_count == 1``
      * ``terminal_reason == "success"``
    """

    root_run_id = resources.root_run_id

    propose = _propose_callable_factory(mode=resources.mode, run_id=root_run_id)
    # Success path: first verify fails, second passes.
    verify = _verify_callable_factory(
        mode=resources.mode,
        run_id=root_run_id,
        verdicts=("fail", "pass"),
    )
    repair = _repair_callable_factory(
        mode=resources.mode, run_id=root_run_id, same_as_propose=False
    )

    loop = await _open_bounded_autonomy_loop(propose, verify, repair)
    receipt = await loop.run_loop(root_run_id=root_run_id, signal=_NeverCancelled())

    # Re-seal so the receipt's digest is the canonical-JSON SHA of all
    # other fields, exactly like the runtime binding would produce.
    sealed = seal_receipt(
        root_run_id=receipt.root_run_id,
        root_generation=receipt.root_generation,
        propose_step_count=receipt.propose_step_count,
        verify_step_count=receipt.verify_step_count,
        repair_step_count=receipt.repair_step_count,
        failed_verify_count=receipt.failed_verify_count,
        terminal_reason=receipt.terminal_reason,
        joined_workspace_digest=receipt.joined_workspace_digest,
    )

    if sealed.terminal_reason != "success":
        # The success path must terminate with "success"; a different
        # terminal_reason is a programming error.
        raise P5OperatorError()

    return P5PublicResult(
        status="completed",
        root_run_id=sealed.root_run_id,
        root_generation=sealed.root_generation,
        propose_step_count=sealed.propose_step_count,
        verify_step_count=sealed.verify_step_count,
        repair_step_count=sealed.repair_step_count,
        failed_verify_count=sealed.failed_verify_count,
        terminal_reason=sealed.terminal_reason,
        joined_workspace_digest=sealed.joined_workspace_digest,
        receipt_sha256=sealed.receipt_sha256,
    )


async def _drive_limits_async(
    resources: _OperatorResources,
) -> list[P5LimitsRecord]:
    """Async limits driver: three refused scenarios in fixed order.

    The order is the spec's closed order (per the plan): iteration-cap,
    duration-cap, no-progress. Cancellation is NOT a separate scenario;
    per D-2026-09-19-01 it folds into the closed
    ``terminal_reason`` enum.
    """

    return [
        await _drive_iteration_cap_scenario(resources),
        await _drive_duration_cap_scenario(resources),
        await _drive_no_progress_scenario(resources),
    ]


async def _drive_iteration_cap_scenario(
    resources: _OperatorResources,
) -> P5LimitsRecord:
    """Drive the iteration-cap scenario: 3 verify-fails trip the cap.

    ``max_iterations = 3`` by default; the loop refuses a 4th repair
    step and seals with ``terminal_reason = "iteration-cap-exceeded"``.
    """

    root_run_id = resources.root_run_id
    propose = _propose_callable_factory(mode=resources.mode, run_id=root_run_id)
    # Three consecutive fails → iteration cap fires on the 3rd.
    verify = _verify_callable_factory(
        mode=resources.mode,
        run_id=root_run_id,
        verdicts=("fail", "fail", "fail"),
    )
    repair = _repair_callable_factory(
        mode=resources.mode, run_id=root_run_id, same_as_propose=False
    )
    loop = await _open_bounded_autonomy_loop(propose, verify, repair)
    receipt = await loop.run_loop(root_run_id=root_run_id, signal=_NeverCancelled())
    if receipt.terminal_reason != "iteration-cap-exceeded":
        raise P5OperatorError()
    return P5LimitsRecord(
        status="refused",
        scenario="iteration-cap",
        terminal_reason=receipt.terminal_reason,
        verify_step_count=receipt.verify_step_count,
        repair_step_count=receipt.repair_step_count,
        failed_verify_count=receipt.failed_verify_count,
        last_step_timed_out=loop.last_step_timed_out,
        joined_workspace_digest=receipt.joined_workspace_digest,
        receipt_sha256=receipt.receipt_sha256,
    )


async def _drive_duration_cap_scenario(
    resources: _OperatorResources,
) -> P5LimitsRecord:
    """Drive the duration-cap scenario: a slow propose times out.

    Uses a bounded-autonomy factory option override
    (``max_total_duration_ms="50"``) so the cap fires before the
    propose step completes. Sealed receipt carries
    ``terminal_reason = "duration-cap-exceeded"`` and
    ``last_step_timed_out = True``.
    """

    root_run_id = resources.root_run_id

    async def slow_propose(signal):  # noqa: ARG001
        # Sleeps longer than the per-step duration cap. asyncio.wait_for
        # in the loop raises TimeoutError, which the loop translates
        # into a duration-cap-exceeded termination.
        import asyncio as _asyncio

        await _asyncio.sleep(0.5)
        return P5ProposeStep(
            step_id=f"propose-{root_run_id}",
            workspace_digest_sha256=_fake_worker_payload_sha(
                mode=resources.mode,
                step_kind="propose",
                run_id=root_run_id,
            ),
        )

    async def verify(signal):  # noqa: ARG001
        return P5VerifyStep(
            step_id=f"verify-{root_run_id}",
            verdict="pass",
            feedback=_fake_worker_payload_sha(
                mode=resources.mode,
                step_kind="verify:pass",
                run_id=root_run_id,
            ),
        )

    async def repair(signal):  # noqa: ARG001
        return P5RepairStep(
            step_id=f"repair-{root_run_id}",
            workspace_digest_sha256=_fake_worker_payload_sha(
                mode=resources.mode,
                step_kind="repair",
                run_id=root_run_id,
            ),
        )

    binding = create_bounded_autonomy_host_service()
    context = HostServiceFactoryContext(
        provider_id="prime-applications",
        application_id="prime.bounded-autonomy",
        application_version="1.0.0",
        capability_id="prime.bounded-autonomy",
        options={"max_total_duration_ms": "50"},
        progress=NOOP_HOST_PROGRESS_REPORTER,
        presentation=NOOP_HOST_PRESENTATION_SINK,
    )
    async with binding.factory(context) as loop:  # type: ignore[arg-type]
        loop.set_step_callables(  # type: ignore[attr-defined]
            propose_callable=slow_propose,  # type: ignore[arg-type]
            verify_callable=verify,  # type: ignore[arg-type]
            repair_callable=repair,  # type: ignore[arg-type]
        )
        receipt = await loop.run_loop(  # type: ignore[attr-defined]
            root_run_id=root_run_id, signal=_NeverCancelled()
        )
    if receipt.terminal_reason != "duration-cap-exceeded":
        raise P5OperatorError()
    return P5LimitsRecord(
        status="refused",
        scenario="duration-cap",
        terminal_reason=receipt.terminal_reason,
        verify_step_count=receipt.verify_step_count,
        repair_step_count=receipt.repair_step_count,
        failed_verify_count=receipt.failed_verify_count,
        last_step_timed_out=True,
        joined_workspace_digest=receipt.joined_workspace_digest,
        receipt_sha256=receipt.receipt_sha256,
    )


async def _drive_no_progress_scenario(
    resources: _OperatorResources,
) -> P5LimitsRecord:
    """Drive the no-progress scenario: repair digest equals propose digest.

    The dedup-adapter short-circuits before the next verify step;
    the sealed receipt carries ``terminal_reason = "no-progress"``.
    """

    root_run_id = resources.root_run_id
    propose = _propose_callable_factory(mode=resources.mode, run_id=root_run_id)
    verify = _verify_callable_factory(
        mode=resources.mode,
        run_id=root_run_id,
        verdicts=("fail",),
    )
    # Repair returns the propose's digest → dedup-adapter short-circuits
    # to no-progress on the next iteration.
    repair = _repair_callable_factory(
        mode=resources.mode, run_id=root_run_id, same_as_propose=True
    )
    loop = await _open_bounded_autonomy_loop(propose, verify, repair)
    receipt = await loop.run_loop(root_run_id=root_run_id, signal=_NeverCancelled())
    if receipt.terminal_reason != "no-progress":
        raise P5OperatorError()
    return P5LimitsRecord(
        status="refused",
        scenario="no-progress",
        terminal_reason=receipt.terminal_reason,
        verify_step_count=receipt.verify_step_count,
        repair_step_count=receipt.repair_step_count,
        failed_verify_count=receipt.failed_verify_count,
        last_step_timed_out=loop.last_step_timed_out,
        joined_workspace_digest=receipt.joined_workspace_digest,
        receipt_sha256=receipt.receipt_sha256,
    )


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


async def _invoke_composed_loop(
    resources: _OperatorResources,
) -> list[dict[str, object]]:
    """Async dispatch on ``resources.mode`` to the right path.

    Success path returns one record; limits path returns three records
    in fixed order. Each record is a content-safe ``dict`` ready for
    canonical-JSON serialisation.
    """

    if resources.mode == "success":
        result = await _drive_success(resources)
        return [asdict(result)]
    records = await _drive_limits_async(resources)
    return [asdict(record) for record in records]


def _emit(records: list[dict[str, object]]) -> None:
    for record in records:
        print(json.dumps(record, separators=(",", ":")))
    sys.stdout.flush()


async def _run_async(
    environment: Mapping[str, str],
) -> tuple[int, list[dict[str, object]]]:
    """Top-level async driver used by the sync entry points.

    Returns ``(exit_code, records)``. Caller emits records to stdout.
    Preflight failure → 2; operator error → 1; success → 0.
    """

    try:
        preflight = _preflight(environment)
    except P5OperatorError:
        return 2, []
    try:
        resources = await _build_resources(preflight)
        records = await _invoke_composed_loop(resources)
    except P5OperatorError:
        return 2, []
    except BaseException:
        return 1, []
    return 0, records


def run_success_path(environment: Mapping[str, str]) -> int:
    """Run the operator in ``success`` mode and emit one JSON record.

    Returns 0 on success, 2 on preflight failure, 1 on operator error.
    """

    rc, records = asyncio.run(_run_async(environment))
    if rc != 0:
        return rc
    _emit(records)
    if records and records[0].get("status") == "completed":
        return 0
    return 2


def run_limits_path(environment: Mapping[str, str]) -> int:
    """Run the operator in ``limits`` mode and emit three JSON records.

    Per D-2026-09-19-01 cancellation folds into the closed
    ``terminal_reason`` enum but is NOT a separately-asserted witness
    record; the limits path emits exactly three refusal records
    (iteration-cap / duration-cap / no-progress), not four.

    Returns 0 on success (three refusal records), 2 on preflight
    failure, 1 on operator error.
    """

    rc, records = asyncio.run(_run_async(environment))
    if rc != 0:
        return rc
    _emit(records)
    if (
        len(records) == 3
        and all(record.get("status") == "refused" for record in records)
    ):
        return 0
    return 2


def main() -> int:
    """Run one operator invocation; print one or three JSON lines; exit 0/2/1."""

    environment = dict(os.environ)
    preflight = _preflight(environment)
    if preflight.mode == "success":
        return run_success_path(environment)
    return run_limits_path(environment)


def _entrypoint() -> None:
    status = main()
    sys.stdout.flush()
    sys.stderr.flush()
    raise SystemExit(status)


if __name__ == "__main__":
    _entrypoint()


__all__ = (
    "P5LimitsRecord",
    "P5OperatorError",
    "P5PublicResult",
    "_entrypoint",
    "main",
    "run_limits_path",
    "run_success_path",
)
