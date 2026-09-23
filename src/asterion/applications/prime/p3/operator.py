"""Operator-owned native P3 recursive-workflow witness.

Single-mode operator: reads ``ASTERION_PRIME_P3_MODE`` and dispatches to
either the success path (``"success"``) or the four-scenario limits
path (``"limits"``). There is no commit/recover split — P3 owns one
bounded root run per invocation, so the operator reads either mode and
emits one JSON record (success) or four JSON records (limits, one per
refused scenario).

The Makefile target ``asterion-prime-p3-run`` invokes the operator in
``success`` mode: one root run admits one child at depth=2, the child
result joins the root, and the operator seals a single receipt. The
sibling target ``asterion-prime-p3-run-limits`` invokes ``limits`` mode:
four refusal scenarios (depth, concurrency, budget, cancellation) each
emit their own record.

The fake-worker contract is deterministic: given ``(mode, depth, run_id)``
the same payload SHA is produced across host runs. No real Pi subprocess
is involved on this path; the operator is itself the host service
owner, mirroring P2's pattern.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
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
from asterion.applications.prime.p3.oracle import P3Oracle
from asterion.applications.prime.p3.host import (
    P3AdmissionRefused,
    P3ChildRequest,
    P3Finalization,
    P3RootResult,
)
from asterion.applications.prime.p3.receipt import seal as seal_receipt
from asterion.applications.prime.p3.runtime_binding import (
    P3_RUNTIME_OPTIONS,
    build_p3_runtime,
)
from asterion.applications.prime.provider import create_prime_recursive_workflow_provider
from asterion.applications.provider import compose_installed_provider
from asterion.capabilities.prime_recursive_workflow_native.provider import (
    P3_INPUT_PRESET,
    create_prime_recursive_workflow_native_package,
)
from asterion.applications.prime.services import (
    ChildAdmissionRefused,
    ChildRunnerHostService,
    create_child_runner_host_service,
)
from asterion.services.progress import NOOP_HOST_PROGRESS_REPORTER
from asterion.services.diagnostics import DiagnosticSink, capture_failure
from asterion.services.presentation import NOOP_HOST_PRESENTATION_SINK
from asterion.services.registry import HostServiceFactoryContext
from asterion.runner.composed import run_composed_application
from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryRegistry
from asterion.runtime.host import CancellationSignal


_OPERATOR_ROOT_ENV = "ASTERION_PRIME_OPERATOR_ROOT"
_PI_ENTRY_ENV = "ASTERION_PRIME_PI_ENTRY"
_PRIVATE_ROOT_ENV = "ASTERION_PRIME_P3_PRIVATE_ROOT"
_MODE_ENV = "ASTERION_PRIME_P3_MODE"


class P3OperatorError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("P3 operator is unavailable")


# ---------------------------------------------------------------------------
# Public result shapes (one JSON record per root run)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class P3PublicResult:
    """Success-path public result.

    ``status`` is ``"completed"`` when the root run admitted a child,
    joined its result, and sealed a receipt. All other fields are
    content-safe projections of the sealed receipt plus a constant
    ``private_root_redacted=True`` marker; no prompts, paths, or worker
    output is exposed.
    """

    status: str
    root_run_id: str
    root_generation: int
    child_run_id: str | None
    child_generation: int | None
    child_result_sha256: str | None
    joined_result_sha256: str
    depth_reached: int
    refusal_reason: str | None
    receipt_sha256: str
    private_root_redacted: bool = True


@dataclass(frozen=True, slots=True)
class P3LimitsRecord:
    """Limits-path refusal record (one per refused scenario)."""

    status: str
    scenario: str
    refusal_reason: str
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
    """Validate env vars and runtime preflight. Raises P3OperatorError on miss."""

    operator_value = environment.get(_OPERATOR_ROOT_ENV, "").strip()
    private_value = environment.get(_PRIVATE_ROOT_ENV, "").strip()
    mode_value = environment.get(_MODE_ENV, "").strip()
    if (
        not operator_value
        or not private_value
        or mode_value not in _VALID_MODES
    ):
        raise P3OperatorError()
    try:
        operator_root = Path(operator_value).resolve(strict=True)
    except OSError:
        raise P3OperatorError() from None
    if not operator_root.is_dir():
        raise P3OperatorError()
    worker_python = Path(sys.executable).absolute()
    if not worker_python.is_file():
        raise P3OperatorError()
    try:
        probe = subprocess.run(
            (str(worker_python), "-I", "-c", "import sys; print(sys.version_info[:2])"),
            check=True,
            capture_output=True,
            timeout=10,
            env={"LANG": "C.UTF-8"},
        )
    except (OSError, subprocess.SubprocessError):
        raise P3OperatorError() from None
    if not probe.stdout or not probe.stdout.strip():
        raise P3OperatorError()
    try:
        private_root = Path(private_value).resolve()
    except OSError:
        raise P3OperatorError() from None
    pi_entry: Path | None = None
    raw_pi = environment.get(_PI_ENTRY_ENV, "").strip()
    if raw_pi:
        try:
            pi_entry = Path(raw_pi).resolve(strict=False)
        except OSError:
            raise P3OperatorError() from None
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


# Default runtime-binding SHAs. Same fixture-pinning approach as P4:
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
        application_id="prime.recursive-workflow",
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
# Deterministic fake-worker
# ---------------------------------------------------------------------------


def _fake_worker_payload_sha(*, mode: str, depth: int, run_id: str) -> str:
    """Deterministic SHA-256 over ``(mode, depth, run_id)``.

    Different tuples produce different SHAs, so the no-replay and
    joined-result checks are meaningful by construction. The same
    tuple maps to the same SHA across host runs.
    """

    payload = json.dumps(
        {"mode": mode, "depth": depth, "run_id": run_id},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _fake_worker_identity_sha(*, mode: str) -> str:
    """Stable per-mode worker identity used by the operator's binding."""

    return sha256(f"p3-deterministic-{mode}".encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Cancellation signal stub
# ---------------------------------------------------------------------------


class _NeverCancelled:
    """A non-cancelling CancellationSignal implementation."""

    @property
    def cancelled(self) -> bool:
        return False


class _AlwaysCancelled:
    """A cancelling CancellationSignal implementation for the cancellation scenario."""

    @property
    def cancelled(self) -> bool:
        return True


class _FakeWorkerBoundary:
    """Operator-owned marker for this preset's deterministic worker."""


# ---------------------------------------------------------------------------
# Operator resources — host services + identity the operator owns
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _OperatorResources:
    """One preflighted set of operator-owned resources for the P3 witness."""

    mode: str
    private_root: Path
    root_run_id: str
    root_identity: PrimeBackendIdentity
    child_identity: PrimeBackendIdentity
    child_runner: ChildRunnerHostService
    p3_oracle: P3Oracle
    pi_extension: object
    private_trace: object
    diagnostics: DiagnosticSink | None = None


async def _open_child_runner() -> ChildRunnerHostService:
    """Open a fresh in-process child-runner host service with spec defaults.

    Async: the operator runs every host-service open inside one event
    loop. Each scenario on the limits path opens its own service so
    the ledger does not bleed between refused attempts.
    """

    factory = create_child_runner_host_service().factory
    context = HostServiceFactoryContext(
        provider_id="prime-applications",
        application_id="prime.recursive-workflow",
        application_version="1.0.0",
        capability_id="prime.child-runner",
        options={},
        progress=NOOP_HOST_PROGRESS_REPORTER,
        presentation=NOOP_HOST_PRESENTATION_SINK,
    )

    async with factory(context) as service:  # type: ignore[arg-type]
        return service  # type: ignore[return-value]


async def _build_resources(preflight: _Preflight) -> _OperatorResources:
    """Build the host services + identity for one operator invocation."""

    mode = preflight.mode
    private_root = preflight.private_root.resolve()
    private_root.parent.mkdir(parents=True, exist_ok=True)
    # P3 has no cross-process continuation; prior private_root state
    # is irrelevant and may have stale children. Wipe it.
    if private_root.exists():
        shutil.rmtree(private_root)
    private_root.mkdir(parents=True, exist_ok=True, mode=0o700)

    root_run_id = "p3-root-" + secrets.token_hex(8)
    session_id = "p3-" + secrets.token_hex(8)
    continuation_id = "continuation-" + secrets.token_hex(8)
    worker_sha = _fake_worker_identity_sha(mode=mode)

    root_identity = _build_identity(
        private_root=private_root,
        generation=1,
        session_id=session_id,
        continuation_id=continuation_id,
        worker_sha=worker_sha,
    )
    # The operator owns child identity construction: bump generation
    # while preserving runtime-binding SHAs per D-2026-09-18-01.
    child_identity = root_identity.bump_generation()

    child_runner = await _open_child_runner()
    p3_oracle = P3Oracle()

    return _OperatorResources(
        mode=mode,
        private_root=private_root,
        root_run_id=root_run_id,
        root_identity=root_identity,
        child_identity=child_identity,
        child_runner=child_runner,
        p3_oracle=p3_oracle,
        pi_extension=_FakeWorkerBoundary(),
        private_trace=None,
    )


# ---------------------------------------------------------------------------
# Result sealing — one function per dispatch path
# ---------------------------------------------------------------------------


def _joined_result_sha(
    *,
    root_result_sha256: str,
    child_result_sha256: str,
    depth_reached: int,
) -> str:
    """Closed-form ``joined_result_sha256`` per the receipt spec."""

    payload = {
        "child_result_sha256": child_result_sha256,
        "depth_reached": depth_reached,
        "root_result_sha256": root_result_sha256,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _refusal_receipt_sha(
    *, scenario: str, refusal_reason: str, attempted_depth: int, attempted_at: str
) -> str:
    """Closed-form receipt SHA for a refused scenario.

    The receipt is the canonical-JSON SHA-256 of the refusal tuple;
    a deterministic, content-safe projection.
    """

    payload = {
        "attempted_at": attempted_at,
        "attempted_depth": attempted_depth,
        "refusal_reason": refusal_reason,
        "scenario": scenario,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


async def _drive_success(
    resources: _OperatorResources, signal: CancellationSignal | None = None
) -> P3PublicResult:
    """Drive one admitted-child root run end-to-end."""

    root_run_id = resources.root_run_id
    root_generation = resources.root_identity.generation
    child_generation = resources.child_identity.generation
    depth = 2

    # Stage 1: admission against the in-process child-runner.
    active_signal = signal if signal is not None else _NeverCancelled()
    admission = await resources.child_runner.admit_child(
        parent_run_id=root_run_id,
        depth=depth,
        child_identity=resources.child_identity,
        signal=active_signal,
    )
    if isinstance(admission, ChildAdmissionRefused):
        # On the success path a refusal is a programming error: the
        # spec defaults admit one child at depth=2 cleanly. Surface
        # as operator error.
        raise P3OperatorError()
    child_run_id = admission.child_run_id
    if active_signal.cancelled:
        raise asyncio.CancelledError()

    # Stage 2: deterministic fake-worker payload.
    try:
        child_result_sha = _fake_worker_payload_sha(
            mode=resources.mode, depth=depth, run_id=child_run_id
        )
    except Exception as error:
        capture_failure(
            resources.diagnostics,
            stage="prime.worker",
            error=error,
            subject_id=child_run_id,
        )
        raise
    # Stage 3: close out the admission slot.
    resources.child_runner.record_child_cost(
        Decimal("0.05"), child_run_id=child_run_id
    )
    if active_signal.cancelled:
        raise asyncio.CancelledError()
    # Stage 4: closed-form join.
    root_result_sha = _fake_worker_payload_sha(
        mode=resources.mode, depth=1, run_id=root_run_id
    )
    joined_sha = _joined_result_sha(
        root_result_sha256=root_result_sha,
        child_result_sha256=child_result_sha,
        depth_reached=depth,
    )
    # Stage 5: oracle check.
    try:
        resources.p3_oracle.check(
            root_run_id=root_run_id,
            root_generation=root_generation,
            child_run_id=child_run_id,
            child_generation=child_generation,
            child_result_sha256=child_result_sha,
            joined_result_sha256=joined_sha,
            depth_reached=depth,
            refusal_reason=None,
        )
    except Exception as error:
        capture_failure(
            resources.diagnostics,
            stage="prime.oracle",
            error=error,
            subject_id=root_run_id,
        )
        raise
    # Stage 6: receipt seal.
    receipt = seal_receipt(
        root_run_id=root_run_id,
        root_generation=root_generation,
        child_run_id=child_run_id,
        child_generation=child_generation,
        child_result_sha256=child_result_sha,
        joined_result_sha256=joined_sha,
        depth_reached=depth,
        refusal_reason=None,
    )
    return P3PublicResult(
        status="completed",
        root_run_id=root_run_id,
        root_generation=root_generation,
        child_run_id=child_run_id,
        child_generation=child_generation,
        child_result_sha256=child_result_sha,
        joined_result_sha256=joined_sha,
        depth_reached=depth,
        refusal_reason=None,
        receipt_sha256=receipt.sha256(),
    )


class _OperatorP3RuntimeHost:
    """Connect the selected runtime to the operator's actual child workflow."""

    def __init__(self, resources: _OperatorResources) -> None:
        self._resources = resources
        self.result: P3PublicResult | None = None

    def validate_runtime_services(self, services: Mapping[str, object]) -> None:
        if (
            set(services) != {
                "prime.child-runner", "prime.p3-oracle", "prime.pi-extension",
                "prime.private-trace", "prime.session-backend",
            }
            or services["prime.child-runner"] is not self._resources.child_runner
            or services["prime.p3-oracle"] is not self._resources.p3_oracle
            or services["prime.pi-extension"] is not self._resources.pi_extension
            or services["prime.private-trace"] is not self._resources.private_trace
            or services["prime.session-backend"] is not self
        ):
            raise P3OperatorError()

    async def run_root(
        self,
        *,
        parent_run_id: str,
        child_request: P3ChildRequest | None,
        signal: object,
    ) -> P3RootResult:
        if (
            parent_run_id != self._resources.root_run_id
            or child_request is not None
            or getattr(signal, "cancelled", True)
            or self.result is not None
        ):
            raise P3OperatorError()
        result = await _drive_success(self._resources, signal)
        self.result = result
        return P3RootResult(
            root_run_id=result.root_run_id,
            root_generation=result.root_generation,
            child_run_id=result.child_run_id,
            child_generation=result.child_generation,
            child_result_sha256=result.child_result_sha256,
            joined_result_sha256=result.joined_result_sha256,
            depth_reached=result.depth_reached,
            refusal_reason=result.refusal_reason,
        )

    def report_admission_refused(self, *, refusal: P3AdmissionRefused) -> None:
        raise P3OperatorError()

    async def wait_finalization(self, *, signal: object) -> P3Finalization:
        if self.result is None:
            raise P3OperatorError()
        return P3Finalization("completed", self.result.receipt_sha256)


async def _drive_limits_async(resources: _OperatorResources) -> list[P3LimitsRecord]:
    """Async limits driver: four refused scenarios in fixed order.

    The order is the spec's closed order: depth, concurrency, budget,
    cancellation. Each scenario opens a fresh child-runner so limit
    state from one scenario does not bleed into the next.
    """

    return [
        await _drive_depth_scenario(resources),
        await _drive_concurrency_scenario(resources),
        await _drive_budget_scenario(resources),
        await _drive_cancellation_scenario(resources),
    ]


async def _drive_depth_scenario(resources: _OperatorResources) -> P3LimitsRecord:
    runner = await _open_child_runner()
    refusal = await runner.admit_child(
        parent_run_id=resources.root_run_id,
        depth=3,
        child_identity=resources.child_identity,
        signal=_NeverCancelled(),
    )
    if not isinstance(refusal, ChildAdmissionRefused):
        raise P3OperatorError()
    receipt_sha = _refusal_receipt_sha(
        scenario="depth",
        refusal_reason=refusal.refusal_reason,
        attempted_depth=refusal.attempted_depth,
        attempted_at=refusal.attempted_at,
    )
    return P3LimitsRecord(
        status="refused",
        scenario="depth",
        refusal_reason=refusal.refusal_reason,
        receipt_sha256=receipt_sha,
    )


async def _drive_concurrency_scenario(
    resources: _OperatorResources,
) -> P3LimitsRecord:
    runner = await _open_child_runner()
    # First admit at depth=2 — succeeds.
    first = await runner.admit_child(
        parent_run_id=resources.root_run_id,
        depth=2,
        child_identity=resources.child_identity,
        signal=_NeverCancelled(),
    )
    if isinstance(first, ChildAdmissionRefused):
        raise P3OperatorError()
    # Second admit at depth=2 — concurrency=1 default, refuses.
    second = await runner.admit_child(
        parent_run_id=resources.root_run_id,
        depth=2,
        child_identity=resources.child_identity,
        signal=_NeverCancelled(),
    )
    if not isinstance(second, ChildAdmissionRefused):
        raise P3OperatorError()
    receipt_sha = _refusal_receipt_sha(
        scenario="concurrency",
        refusal_reason=second.refusal_reason,
        attempted_depth=second.attempted_depth,
        attempted_at=second.attempted_at,
    )
    return P3LimitsRecord(
        status="refused",
        scenario="concurrency",
        refusal_reason=second.refusal_reason,
        receipt_sha256=receipt_sha,
    )


async def _drive_budget_scenario(resources: _OperatorResources) -> P3LimitsRecord:
    runner = await _open_child_runner()
    # Pre-admit one child at depth=2 and spend the full default 0.10
    # USD budget. The next admission then trips the budget gate.
    first = await runner.admit_child(
        parent_run_id=resources.root_run_id,
        depth=2,
        child_identity=resources.child_identity,
        signal=_NeverCancelled(),
    )
    if isinstance(first, ChildAdmissionRefused):
        raise P3OperatorError()
    runner.record_child_cost(Decimal("0.10"), child_run_id=first.child_run_id)
    second = await runner.admit_child(
        parent_run_id=resources.root_run_id,
        depth=2,
        child_identity=resources.child_identity,
        signal=_NeverCancelled(),
    )
    if not isinstance(second, ChildAdmissionRefused):
        raise P3OperatorError()
    receipt_sha = _refusal_receipt_sha(
        scenario="budget",
        refusal_reason=second.refusal_reason,
        attempted_depth=second.attempted_depth,
        attempted_at=second.attempted_at,
    )
    return P3LimitsRecord(
        status="refused",
        scenario="budget",
        refusal_reason=second.refusal_reason,
        receipt_sha256=receipt_sha,
    )


async def _drive_cancellation_scenario(
    resources: _OperatorResources,
) -> P3LimitsRecord:
    runner = await _open_child_runner()
    refusal = await runner.admit_child(
        parent_run_id=resources.root_run_id,
        depth=2,
        child_identity=resources.child_identity,
        signal=_AlwaysCancelled(),
    )
    if not isinstance(refusal, ChildAdmissionRefused):
        raise P3OperatorError()
    receipt_sha = _refusal_receipt_sha(
        scenario="cancellation",
        refusal_reason=refusal.refusal_reason,
        attempted_depth=refusal.attempted_depth,
        attempted_at=refusal.attempted_at,
    )
    return P3LimitsRecord(
        status="refused",
        scenario="cancellation",
        refusal_reason=refusal.refusal_reason,
        receipt_sha256=receipt_sha,
    )


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


async def _invoke_composed_success(
    resources: _OperatorResources, signal: CancellationSignal | None = None
) -> P3PublicResult:
    package = create_prime_recursive_workflow_native_package()
    provider = compose_installed_provider(
        create_prime_recursive_workflow_provider(),
        runtime_factories=RuntimeFactoryRegistry(()),
        installed_packages=(package,),
    )
    application = provider.applications[0]
    assembly = application.assemblies[0]
    session_backend = _OperatorP3RuntimeHost(resources)
    host_services = {
        "prime.child-runner": resources.child_runner,
        "prime.p3-oracle": resources.p3_oracle,
        "prime.pi-extension": resources.pi_extension,
        "prime.private-trace": resources.private_trace,
        "prime.session-backend": session_backend,
    }
    runtime = build_p3_runtime(
        RuntimeFactoryContext(
            "prime-applications",
            "prime.recursive-workflow",
            "1.0.0",
            "asterion.prime",
            assembly.path,
            P3_RUNTIME_OPTIONS,
            host_services,
        )
    )
    result = await run_composed_application(
        assembly.plan,
        implementations=application.implementations,
        runtime=runtime,
        run_id=resources.root_run_id,
        input_text=P3_INPUT_PRESET,
        host_services=host_services,
        signal=signal,
    )
    public = session_backend.result
    if (
        public is None
        or len(result.artifacts) != 1
        or result.artifacts[0]["value"]["receipt_sha256"] != public.receipt_sha256
    ):
        raise P3OperatorError()
    return public


async def _invoke_composed_root_async(
    resources: _OperatorResources,
) -> list[dict[str, object]]:
    """Async dispatch on ``resources.mode`` to the right path.

    Success path returns one record; limits path returns four records
    in fixed order. Each record is a content-safe ``dict`` ready for
    canonical-JSON serialisation.
    """

    if resources.mode == "success":
        result = await _invoke_composed_success(resources)
        return [asdict(result)]
    records = await _drive_limits_async(resources)
    return [asdict(record) for record in records]


def _emit(records: list[dict[str, object]]) -> None:
    for record in records:
        print(json.dumps(record, separators=(",", ":")))
    sys.stdout.flush()


async def _run_async(
    environment: Mapping[str, str],
    *,
    diagnostics: DiagnosticSink | None = None,
) -> tuple[int, list[dict[str, object]]]:
    """Top-level async driver used by the sync entry points.

    Returns ``(exit_code, records)``. Caller emits records to stdout.
    Preflight failure → 2; operator error → 1; success → 0.
    """

    try:
        preflight = _preflight(environment)
    except P3OperatorError:
        return 2, []
    try:
        resources = await _build_resources(preflight)
        if diagnostics is not None:
            resources = replace(resources, diagnostics=diagnostics)
        records = await _invoke_composed_root_async(resources)
    except P3OperatorError:
        return 2, []
    except BaseException:
        return 1, []
    return 0, records


def run_success_path(
    environment: Mapping[str, str], *, diagnostics: DiagnosticSink | None = None
) -> int:
    """Run the operator in ``success`` mode and emit one JSON record.

    Returns 0 on success, 2 on preflight failure, 1 on operator error.
    """

    rc, records = asyncio.run(_run_async(environment, diagnostics=diagnostics))
    if rc != 0:
        return rc
    _emit(records)
    if records and records[0].get("status") == "completed":
        return 0
    return 2


def run_limits_path(environment: Mapping[str, str]) -> int:
    """Run the operator in ``limits`` mode and emit four JSON records.

    Returns 0 on success (four refusal records), 2 on preflight failure,
    1 on operator error.
    """

    rc, records = asyncio.run(_run_async(environment))
    if rc != 0:
        return rc
    _emit(records)
    if (
        len(records) == 4
        and all(record.get("status") == "refused" for record in records)
    ):
        return 0
    return 2


def main() -> int:
    """Run one operator invocation; print one or four JSON lines; exit 0/2/1."""

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
    "P3LimitsRecord",
    "P3OperatorError",
    "P3PublicResult",
    "_entrypoint",
    "main",
    "run_limits_path",
    "run_success_path",
)
