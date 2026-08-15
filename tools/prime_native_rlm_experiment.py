"""Pure preparation boundary for one bounded native Prime RLM experiment."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from hashlib import sha256
import asyncio
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
from types import MappingProxyType
from typing import Awaitable, Callable

from asterion.control.authority import (
    AuthorityEnvelope,
    BudgetLimit,
    BudgetUsage,
    PortfolioGrant,
)
from asterion.immutable import RedactedImmutableMapping
from tools.verify_prime_loop import PrimeVerificationError, load_bounded_rlm_authority


_MAX_COST_MICROS = 500_000
_MAX_DEADLINE_MS = 600_000
_MODEL_KEY = "ASTERION_PRIME_EXPERIMENT_MODEL"
_DEFAULT_OPERATIONS = tuple(
    sorted(
        {
            "application.invoke",
            "checkpoint.create",
            "child.cancel",
            "child.message",
            "child.spawn",
            "goal.complete",
            "goal.fail",
            "rlm.child.delete",
            "rlm.child.message",
            "rlm.child.spawn",
        }
    )
)


class PrimeRlmExperimentError(RuntimeError):
    """Raised with a public-safe native RLM experiment preparation failure."""


@dataclass(frozen=True, repr=False)
class NativeRlmExperimentLimits:
    cost_micros: int
    deadline_ms: int


@dataclass(frozen=True, repr=False)
class NativeRlmModelSelection:
    provider: str
    model: str
    credential_env: str


@dataclass(frozen=True, repr=False)
class NativeRlmRuntimeResources:
    """Pinned private paths required to launch one native RLM sidecar."""

    node_executable: Path
    daemon_entry: Path
    sidecar_entry: Path
    artifact_lock_path: Path
    prime_source_root: Path
    skill_path: Path
    expected_runtime_build_id: str

    def __post_init__(self) -> None:
        if (
            not all(
                isinstance(value, Path)
                for value in (
                    self.node_executable,
                    self.daemon_entry,
                    self.sidecar_entry,
                    self.artifact_lock_path,
                    self.prime_source_root,
                    self.skill_path,
                )
            )
            or not isinstance(self.expected_runtime_build_id, str)
            or not self.expected_runtime_build_id
        ):
            raise PrimeRlmExperimentError("Native RLM runtime resources are invalid")


@dataclass(frozen=True, repr=False)
class NativeRlmDaemonPlan:
    argv: tuple[str, ...]
    environ: Mapping[str, str]
    socket_path: Path

    def __repr__(self) -> str:
        return "NativeRlmDaemonPlan(argv=<redacted>, environ=<redacted>)"


@dataclass(frozen=True, repr=False)
class NativeRlmExperimentReservation:
    authority: AuthorityEnvelope
    limits: NativeRlmExperimentLimits
    configuration_digest: str
    consumed: bool = False

    def consume(self) -> NativeRlmExperimentReservation:
        if self.consumed:
            raise PrimeRlmExperimentError("Native RLM experiment reservation is inactive")
        return replace(self, consumed=True)


@dataclass(frozen=True, repr=False)
class NativeRlmProbeResult:
    terminal: str
    child_started: bool
    message_delivered: bool
    child_deleted: bool
    usage: BudgetUsage


ProbeRunner = Callable[[NativeRlmExperimentReservation], Awaitable[NativeRlmProbeResult]]
DaemonLauncher = Callable[[NativeRlmDaemonPlan], Awaitable[object]]
SidecarLauncher = Callable[
    [Mapping[str, object], NativeRlmRuntimeResources], Awaitable[object]
]
SidecarProbe = Callable[[object], Awaitable[NativeRlmProbeResult]]


def resolve_native_rlm_model(environ: Mapping[str, str]) -> NativeRlmModelSelection:
    """Resolve the sole model/provider pairing authorized for this first probe."""
    if not isinstance(environ, Mapping) or environ.get(_MODEL_KEY) != "deepseek-v4-flash":
        raise PrimeRlmExperimentError("Native RLM experiment model is invalid")
    return NativeRlmModelSelection("deepseek", "deepseek-v4-flash", "DEEPSEEK_API_KEY")


def build_native_rlm_daemon_plan(
    node_executable: Path,
    runtime_entry: Path,
    socket_path: Path,
    selection: NativeRlmModelSelection,
    environ: Mapping[str, str],
) -> NativeRlmDaemonPlan:
    """Build the exact direct daemon invocation without starting it."""
    if (
        not all(isinstance(value, Path) for value in (node_executable, runtime_entry, socket_path))
        or not isinstance(selection, NativeRlmModelSelection)
    ):
        raise PrimeRlmExperimentError("Native RLM daemon plan is invalid")
    environment = build_native_rlm_daemon_environment(
        environ, credential_env=selection.credential_env
    )
    return NativeRlmDaemonPlan(
        (
            str(node_executable), str(runtime_entry), "--mode", "daemon", "--daemon-socket",
            str(socket_path), "--provider", selection.provider, "--model", selection.model,
        ),
        environment,
        socket_path,
    )


def classify_native_rlm_probe_observation(
    lifecycle: Sequence[Mapping[str, str]],
    *,
    message_delivered: bool,
    usage: BudgetUsage,
) -> NativeRlmProbeResult:
    """Reduce only closed lifecycle observations into a safe probe outcome."""
    if (
        not isinstance(lifecycle, Sequence)
        or isinstance(lifecycle, (str, bytes))
        or not isinstance(message_delivered, bool)
        or not isinstance(usage, BudgetUsage)
    ):
        raise PrimeRlmExperimentError("Native RLM probe observation is invalid")
    active: set[str] = set()
    completed: set[str] = set()
    try:
        for event in lifecycle:
            if not isinstance(event, Mapping):
                raise ValueError
            event_type = event.get("type")
            child_id = event.get("child_id")
            if not isinstance(child_id, str) or not child_id:
                raise ValueError
            if event_type == "rlm.child.started" and set(event) == {"type", "child_id"}:
                if child_id in active or child_id in completed:
                    raise ValueError
                active.add(child_id)
            elif (
                event_type == "rlm.child.terminal"
                and set(event) == {"type", "child_id", "status"}
                and event.get("status") in {"completed", "failed", "cancelled"}
                and child_id in active
            ):
                active.remove(child_id)
                if event["status"] == "completed":
                    completed.add(child_id)
            else:
                raise ValueError
    except (TypeError, ValueError):
        raise PrimeRlmExperimentError("Native RLM probe observation is invalid") from None
    child_started = bool(completed)
    child_deleted = child_started and not active
    terminal = "completed" if child_deleted and message_delivered else "uncertain"
    return NativeRlmProbeResult(
        terminal=terminal,
        child_started=child_started,
        message_delivered=message_delivered,
        child_deleted=child_deleted,
        usage=usage,
    )


def build_native_rlm_sidecar_descriptor(
    reservation: NativeRlmExperimentReservation,
    selection: NativeRlmModelSelection,
    root: Path,
    resources: NativeRlmRuntimeResources,
) -> Mapping[str, object]:
    """Build the closed private descriptor for the single native probe session."""
    if (
        not isinstance(reservation, NativeRlmExperimentReservation)
        or not isinstance(selection, NativeRlmModelSelection)
        or not isinstance(root, Path)
        or not isinstance(resources, NativeRlmRuntimeResources)
    ):
        raise PrimeRlmExperimentError("Native RLM sidecar descriptor is invalid")
    budget = reservation.authority.budget_limit
    return RedactedImmutableMapping({
        "agentDir": str(root / "agent"), "artifactLockPath": str(resources.artifact_lock_path),
        "authorityId": reservation.authority.authority_id, "authorityRevision": reservation.authority.revision,
        "expectedRuntimeBuildId": resources.expected_runtime_build_id, "gatewayRoot": str(root / "gateway"), "generation": 1,
        "maxContinuations": 1, "maxControllerTokens": budget.controller_tokens, "maxTurns": 1,
        "model": selection.model,
        "portfolio": [{"kind": "application", "provider_id": grant.provider_id, "application_id": grant.application_id, "version": grant.version, "runtime_id": grant.runtime_id} for grant in reservation.authority.allowed_portfolio],
        "primeSocketPath": str(root / "prime.sock"), "primeSourceRoot": str(resources.prime_source_root), "provider": selection.provider, "rlmMaxDepth": 1,
        "remainingBudget": {"controller_tokens": budget.controller_tokens, "application_tokens": budget.application_tokens, "child_tokens": budget.child_tokens, "aggregate_tokens": budget.aggregate_tokens, "cost_micros": budget.cost_micros, "deadline_ms": reservation.limits.deadline_ms},
        "sessionDir": str(root / "sessions"), "sessionId": "native-rlm-root", "skillPath": str(resources.skill_path), "timeoutMs": reservation.limits.deadline_ms, "workspace": str(root / "workspace"),
    })
async def start_native_rlm_daemon(
    plan: NativeRlmDaemonPlan,
    *,
    launcher: Callable[[NativeRlmDaemonPlan], Awaitable[object]],
    timeout_seconds: float,
) -> object:
    """Start one owned daemon and wait only for its designated socket."""
    if not isinstance(plan, NativeRlmDaemonPlan) or not callable(launcher) or timeout_seconds <= 0:
        raise PrimeRlmExperimentError("Native RLM daemon launch is invalid")
    process = await launcher(plan)
    deadline = time.monotonic() + timeout_seconds
    while not plan.socket_path.exists():
        if getattr(process, "returncode", None) is not None or time.monotonic() >= deadline:
            if getattr(process, "returncode", None) is None:
                terminate = getattr(process, "terminate", None)
                wait = getattr(process, "wait", None)
                if callable(terminate) and callable(wait):
                    terminate()
                    try:
                        await asyncio.wait_for(wait(), timeout=min(timeout_seconds, 2))
                    except (TimeoutError, OSError):
                        pass
            raise PrimeRlmExperimentError("Native RLM daemon did not become ready")
        await asyncio.sleep(0.01)
    return process


async def execute_native_rlm_sidecar_probe(
    reservation: NativeRlmExperimentReservation,
    selection: NativeRlmModelSelection,
    root: Path,
    resources: NativeRlmRuntimeResources,
    *,
    environ: Mapping[str, str],
    daemon_launcher: DaemonLauncher,
    sidecar_launcher: SidecarLauncher,
    probe: SidecarProbe,
) -> NativeRlmProbeResult:
    """Run one injected probe and always release the processes it owns."""
    if (
        not isinstance(reservation, NativeRlmExperimentReservation)
        or not isinstance(selection, NativeRlmModelSelection)
        or not isinstance(root, Path)
        or not isinstance(resources, NativeRlmRuntimeResources)
        or not isinstance(environ, Mapping)
        or any(not isinstance(key, str) or not isinstance(value, str) for key, value in environ.items())
        or not all(callable(value) for value in (daemon_launcher, sidecar_launcher, probe))
    ):
        raise PrimeRlmExperimentError("Native RLM sidecar probe is invalid")
    plan = build_native_rlm_daemon_plan(
        resources.node_executable,
        resources.daemon_entry,
        root / "prime.sock",
        selection,
        environ,
    )
    daemon = await start_native_rlm_daemon(
        plan, launcher=daemon_launcher, timeout_seconds=10
    )
    sidecar: object | None = None
    try:
        descriptor = build_native_rlm_sidecar_descriptor(
            reservation, selection, root, resources
        )
        sidecar = await sidecar_launcher(descriptor, resources)
        result = await probe(sidecar)
        if not isinstance(result, NativeRlmProbeResult):
            raise PrimeRlmExperimentError("Native RLM probe result is invalid")
        return result
    except PrimeRlmExperimentError:
        raise
    except Exception:
        raise PrimeRlmExperimentError("Native RLM probe did not complete") from None
    finally:
        await _close_owned_sidecar(sidecar)
        await _reap_owned_daemon(daemon)


async def start_native_rlm_sidecar(
    descriptor: Mapping[str, object],
    resources: NativeRlmRuntimeResources,
    *,
    environ: Mapping[str, str],
    starter: Callable[[object], Awaitable[object]] | None = None,
) -> object:
    """Start the Asterion sidecar with its model credential deliberately absent."""
    try:
        if (
            not isinstance(descriptor, Mapping)
            or not isinstance(resources, NativeRlmRuntimeResources)
            or not isinstance(environ, Mapping)
            or any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in environ.items()
            )
            or "HOME" not in environ
            or "PATH" not in environ
            or starter is not None and not callable(starter)
        ):
            raise ValueError
        from asterion.control.providers.prime.process import PrimeSidecarLaunchOptions

        options = PrimeSidecarLaunchOptions(
            node_executable=resources.node_executable,
            sidecar_entry=resources.sidecar_entry,
            private_descriptor=descriptor,
            environ={"HOME": environ["HOME"], "PATH": environ["PATH"]},
            request_timeout=30,
        )
        if starter is not None:
            return await starter(options)
        from asterion.control.providers.prime.process import PrimeSidecarProcess

        return await PrimeSidecarProcess.start(options)
    except (OSError, TypeError, ValueError):
        raise PrimeRlmExperimentError("Native RLM sidecar could not start") from None


async def launch_owned_native_rlm_daemon(
    plan: NativeRlmDaemonPlan,
    resources: NativeRlmRuntimeResources,
    *,
    spawn: Callable[..., Awaitable[object]] | None = None,
) -> object:
    """Launch the exact daemon directly under its locked source root."""
    if not isinstance(plan, NativeRlmDaemonPlan) or not isinstance(
        resources, NativeRlmRuntimeResources
    ):
        raise PrimeRlmExperimentError("Native RLM daemon launch is invalid")
    starter = asyncio.create_subprocess_exec if spawn is None else spawn
    try:
        return await starter(
            *plan.argv,
            cwd=resources.prime_source_root,
            env=dict(plan.environ),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        raise PrimeRlmExperimentError("Native RLM daemon could not start") from None


async def run_owned_native_rlm_sidecar_probe(
    reservation: NativeRlmExperimentReservation,
    selection: NativeRlmModelSelection,
    root: Path,
    resources: NativeRlmRuntimeResources,
    *,
    environ: Mapping[str, str],
    probe: SidecarProbe,
    daemon_spawn: Callable[..., Awaitable[object]] | None = None,
    sidecar_starter: Callable[[object], Awaitable[object]] | None = None,
) -> NativeRlmProbeResult:
    """Compose the real owned process launchers for one explicitly admitted probe."""

    async def launch_daemon(plan: NativeRlmDaemonPlan) -> object:
        return await launch_owned_native_rlm_daemon(
            plan, resources, spawn=daemon_spawn
        )

    async def launch_sidecar(
        descriptor: Mapping[str, object], _: NativeRlmRuntimeResources
    ) -> object:
        return await start_native_rlm_sidecar(
            descriptor, resources, environ=environ, starter=sidecar_starter
        )

    return await execute_native_rlm_sidecar_probe(
        reservation,
        selection,
        root,
        resources,
        environ=environ,
        daemon_launcher=launch_daemon,
        sidecar_launcher=launch_sidecar,
        probe=probe,
    )


async def _close_owned_sidecar(sidecar: object | None) -> None:
    if sidecar is None:
        return
    close = getattr(sidecar, "close", None)
    if not callable(close):
        raise PrimeRlmExperimentError("Native RLM sidecar cleanup failed")
    try:
        result = close()
        if hasattr(result, "__await__"):
            await result
    except (OSError, RuntimeError, TypeError, ValueError):
        raise PrimeRlmExperimentError("Native RLM sidecar cleanup failed") from None


async def _reap_owned_daemon(daemon: object) -> None:
    if getattr(daemon, "returncode", None) is not None:
        return
    terminate = getattr(daemon, "terminate", None)
    wait = getattr(daemon, "wait", None)
    if not callable(terminate) or not callable(wait):
        raise PrimeRlmExperimentError("Native RLM daemon cleanup failed")
    try:
        terminate()
        await asyncio.wait_for(wait(), timeout=2)
    except (TimeoutError, OSError, RuntimeError, TypeError, ValueError):
        raise PrimeRlmExperimentError("Native RLM daemon cleanup failed") from None


def build_native_rlm_daemon_environment(
    environ: Mapping[str, str], *, credential_env: str
) -> Mapping[str, str]:
    """Forward the sole selected credential to the owned Prime daemon."""
    try:
        if (
            not isinstance(environ, Mapping)
            or not isinstance(credential_env, str)
            or not credential_env
            or any(not isinstance(key, str) or not isinstance(value, str) for key, value in environ.items())
            or credential_env not in environ
        ):
            raise ValueError
        values = {
            key: environ[key]
            for key in ("HOME", "PATH", credential_env)
            if key in environ
        }
        if "HOME" not in values or "PATH" not in values:
            raise ValueError
        return RedactedImmutableMapping(values)
    except (TypeError, ValueError):
        raise PrimeRlmExperimentError("Native RLM daemon environment is invalid") from None


def prepare_native_rlm_experiment(
    authority_path: Path | None,
    *,
    max_cost_micros: int | None,
    deadline_ms: int | None,
    environ: Mapping[str, str],
    now_ms: int | None = None,
) -> NativeRlmExperimentReservation:
    """Validate all non-executing admission inputs without reading process state."""
    try:
        cost_limit = _MAX_COST_MICROS if max_cost_micros is None else max_cost_micros
        action_deadline = _MAX_DEADLINE_MS if deadline_ms is None else deadline_ms
        if (
            not isinstance(environ, Mapping)
            or any(not isinstance(key, str) or not isinstance(value, str) for key, value in environ.items())
            or authority_path is not None and not isinstance(authority_path, Path)
            or isinstance(cost_limit, bool)
            or not isinstance(cost_limit, int)
            or cost_limit < 1
            or cost_limit > _MAX_COST_MICROS
            or isinstance(action_deadline, bool)
            or not isinstance(action_deadline, int)
            or action_deadline < 1
            or action_deadline > _MAX_DEADLINE_MS
        ):
            raise ValueError
        model = environ.get(_MODEL_KEY)
        if not isinstance(model, str) or not model:
            raise ValueError
        current = int(time.time() * 1000) if now_ms is None else now_ms
        authority = (
            _default_native_rlm_authority(current, action_deadline)
            if authority_path is None
            else load_bounded_rlm_authority(
                authority_path, max_cost_micros=cost_limit, now_ms=current
            )
        )
        if authority.max_action_deadline_ms > action_deadline:
            raise ValueError
        digest = sha256(b"asterion.prime.native-rlm\0" + model.encode()).hexdigest()
        return NativeRlmExperimentReservation(
            authority=authority,
            limits=NativeRlmExperimentLimits(cost_limit, action_deadline),
            configuration_digest=digest,
        )
    except (PrimeVerificationError, TypeError, ValueError):
        raise PrimeRlmExperimentError("Native RLM experiment authorization is invalid") from None


def _default_native_rlm_authority(
    now_ms: int, deadline_ms: int
) -> AuthorityEnvelope:
    """Mint a one-command envelope that is never persisted or reused."""
    return AuthorityEnvelope(
        authority_id=f"native-rlm-{secrets.token_hex(16)}",
        revision=1,
        allowed_portfolio=(
            PortfolioGrant(
                provider_id="asterion.prime-gateway",
                application_id="native-rlm-probe",
                version="0.1.0",
                runtime_id="prime.gateway",
            ),
        ),
        allowed_operations=_DEFAULT_OPERATIONS,
        budget_limit=BudgetLimit(
            controller_tokens=100,
            application_tokens=100,
            child_tokens=100,
            aggregate_tokens=300,
            cost_micros=_MAX_COST_MICROS,
        ),
        expires_at_ms=now_ms + deadline_ms,
        max_action_deadline_ms=deadline_ms,
        max_recursion_depth=1,
        max_concurrent_children=1,
        execution_domain="trusted-local",
        host_service_grants=("artifact.write",),
    )


def write_native_rlm_experiment_receipt(
    root: Path,
    reservation: NativeRlmExperimentReservation,
    *,
    terminal: str,
    child_started: bool,
    message_delivered: bool,
    child_deleted: bool,
    usage: BudgetUsage,
) -> Mapping[str, object]:
    """Atomically write a private, public-safe observation for one reservation."""
    if (
        not isinstance(root, Path)
        or not root.is_dir()
        or not isinstance(reservation, NativeRlmExperimentReservation)
        or not reservation.consumed
        or terminal not in {"completed", "failed", "cancelled", "uncertain"}
        or not all(isinstance(value, bool) for value in (child_started, message_delivered, child_deleted))
        or not isinstance(usage, BudgetUsage)
    ):
        raise PrimeRlmExperimentError("Native RLM experiment receipt is invalid")
    complete = child_started and message_delivered and child_deleted
    in_budget = usage.cost_micros <= reservation.limits.cost_micros
    status = "PASS" if terminal == "completed" and complete and in_budget else "uncertain"
    payload = {
        "format": "asterion.prime-native-rlm-receipt/v1",
        "authority_id": reservation.authority.authority_id,
        "authority_revision": reservation.authority.revision,
        "configuration_digest": reservation.configuration_digest,
        "terminal": terminal,
        "child_started": child_started,
        "message_delivered": message_delivered,
        "child_deleted": child_deleted,
        "usage": vars(usage),
        "status": status,
    }
    descriptor, temporary = tempfile.mkstemp(prefix=".native-rlm-", dir=root)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        os.replace(temporary, root / "native-rlm-experiment-receipt.json")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return MappingProxyType(
        {
            "format": payload["format"],
            "configuration_digest": reservation.configuration_digest,
            "status": status,
            "terminal": terminal,
            "child_started": child_started,
            "message_delivered": message_delivered,
            "child_deleted": child_deleted,
            "usage": MappingProxyType(dict(vars(usage))),
        }
    )


async def run_native_rlm_experiment(
    reservation: NativeRlmExperimentReservation,
    runner: ProbeRunner,
) -> Mapping[str, object]:
    """Consume a reservation once and classify an injected native probe result."""
    if not isinstance(reservation, NativeRlmExperimentReservation) or not callable(runner):
        raise PrimeRlmExperimentError("Native RLM experiment runner is invalid")
    consumed = reservation.consume()
    try:
        async with asyncio.timeout(consumed.limits.deadline_ms / 1000):
            result = await runner(consumed)
    except TimeoutError:
        return MappingProxyType({"status": "uncertain", "terminal": "uncertain"})
    if not isinstance(result, NativeRlmProbeResult) or not isinstance(result.usage, BudgetUsage):
        raise PrimeRlmExperimentError("Native RLM experiment result is invalid")
    complete = result.child_started and result.message_delivered and result.child_deleted
    in_budget = result.usage.cost_micros <= consumed.limits.cost_micros
    status = "PASS" if result.terminal == "completed" and complete and in_budget else "External-limited"
    return MappingProxyType({"status": status, "terminal": result.terminal})
