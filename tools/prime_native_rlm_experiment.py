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
import textwrap
import time
from types import MappingProxyType
from typing import Awaitable, Callable, IO

from asterion.control.authority import (
    AuthorityEnvelope,
    AuthorityLedger,
    BudgetLimit,
    BudgetUsage,
    PortfolioGrant,
)
from asterion.control.execution import ActionExecutionReceipt
from asterion.control.factory import ControlPlaneFactoryRegistry
from asterion.control.host import ControlCommand, ControlEvent
from asterion.control.journal import FileCanonicalJournal
from asterion.control.manager import ControlHost
from asterion.control.providers.prime.client import PrimeControlPlaneClient
from asterion.control.providers.prime.factory import prime_control_plane_binding
from asterion.control.providers.prime.rlm import build_prime_rlm_control_host
from asterion.control.system import AgentSystemPlan, resolve_agent_system
from asterion.applications.provider import (
    APPLICATION_PROVIDER_PROTOCOL,
    InstalledApplication,
    InstalledApplicationProvider,
    InstalledAssembly,
)
from asterion.assembly.protocol import AssemblyPlan
from asterion.capabilities.composition import CapabilityComposition
from asterion.immutable import RedactedImmutableMapping
try:
    from tools.verify_prime_loop import PrimeVerificationError, load_bounded_rlm_authority
except ModuleNotFoundError:  # Direct ``python tools/verify_prime_loop.py`` execution.
    from verify_prime_loop import PrimeVerificationError, load_bounded_rlm_authority


_MAX_COST_MICROS = 500_000
_MAX_DEADLINE_MS = 600_000
_MODEL_KEY = "ASTERION_PRIME_EXPERIMENT_MODEL"
_SESSION_ID = "native-rlm-root"
_GOAL_REFERENCE = "native-rlm-goal"
_START_REFERENCE = "native-rlm-start-input"
_PROBE_GOAL = (
    "Execute this exact bounded native-RLM protocol. Do not inspect documentation, "
    "call help or shell tools, write files, or perform unrelated work. In one Python "
    "cell, import asyncio, then call `child = await rlm('Reply pong to your parent "
    "using agent_message.send with receiver_role=parent, then stop.', "
    "name='native-rlm-child')`. Poll `await rlm.list_subagents()` for this child's "
    "nonempty active_session_id, sleeping 0.25 seconds between polls, before calling "
    "`await agent_message.send('ping', receiver_role='child', "
    "receiver_name=child.session_name)`. Do not create another child or send another "
    "message. When the child's ordinary reply starts the next parent turn, call "
    "`child = (await rlm.list_subagents())[0]` and `await rlm.delete_subagent(child)`, "
    "then finish."
)
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


@dataclass(frozen=True, repr=False)
class NativeRlmPrivateGoal:
    """One private root instruction; its text never enters public evidence."""

    text: str

    def resolve_text(self, reference: str, *, max_bytes: int) -> str:
        if (
            reference not in {_GOAL_REFERENCE, _START_REFERENCE}
            or not isinstance(max_bytes, int)
            or max_bytes < len(self.text.encode("utf-8"))
        ):
            raise KeyError("private native RLM input is unavailable")
        return self.text

    def resolve_bytes(self, *args: object, **kwargs: object) -> bytes:
        del args, kwargs
        raise KeyError("private native RLM attachment is unavailable")


ProbeRunner = Callable[[NativeRlmExperimentReservation], Awaitable[NativeRlmProbeResult]]
DaemonLauncher = Callable[[NativeRlmDaemonPlan], Awaitable[object]]
SidecarLauncher = Callable[
    [Mapping[str, object], NativeRlmRuntimeResources], Awaitable[object]
]
SidecarProbe = Callable[[object], Awaitable[NativeRlmProbeResult]]
OwnedWorkerCleanup = Callable[[], Awaitable[None]]
OwnedDaemonShutdown = Callable[[NativeRlmDaemonPlan, NativeRlmRuntimeResources], Awaitable[None]]


class _NativeRlmActionExecutor:
    """Defensive fence: admitted native RLM work must remain provider-owned."""

    async def execute(
        self, proposal: ControlEvent, signal: object
    ) -> ActionExecutionReceipt:
        del proposal, signal
        raise RuntimeError("native RLM action escaped provider ownership")


def build_native_rlm_experiment_system(root: Path) -> AgentSystemPlan:
    """Resolve the exact control-only portfolio required by the one-shot probe.

    This virtual application is a static authority anchor only.  Native RLM
    actions are reconciled by the Prime provider and never invoke it.
    """
    if not isinstance(root, Path) or not root.is_dir():
        raise PrimeRlmExperimentError("Native RLM experiment system is invalid")
    try:
        plan = AssemblyPlan(
            application_id="native-rlm-probe",
            version="0.1.0",
            runtime_id="prime.gateway",
            capability_package_refs=(),
            capability_refs=(),
            capability_manifests=(),
            composition=CapabilityComposition((), (), (), ()),
            runtime_capabilities=(),
            host_capabilities=(),
            host_events=(),
            host_artifacts=(),
        )
        assembly = InstalledAssembly(
            runtime_id="prime.gateway", path=root / "control-anchor.json", plan=plan
        )
        application = InstalledApplication(
            application_id="native-rlm-probe",
            version="0.1.0",
            assembly_paths=(assembly.path,),
            capability_packages=(),
            runtime_ids=("prime.gateway",),
            assemblies=(assembly,),
        )
        provider = InstalledApplicationProvider(
            protocol=APPLICATION_PROVIDER_PROTOCOL,
            provider_id="asterion.prime-gateway",
            resource_root=root,
            applications=(application,),
        )
        return resolve_agent_system(
            {
                "protocol": "asterion.agent-system/v1",
                "system_id": "native-rlm-probe",
                "version": "0.1.0",
                "control_plane": {
                    "control_plane_id": "prime.gateway",
                    "version": "0.1.0",
                },
                "applications": [
                    {
                        "provider_id": "asterion.prime-gateway",
                        "application_id": "native-rlm-probe",
                        "version": "0.1.0",
                        "runtime_id": "prime.gateway",
                    }
                ],
                "policies": [],
                "host_capabilities": ["clock.monotonic", "storage.private"],
                "control_capabilities": [
                    "action-proposals",
                    "checkpointing",
                    "event-replay",
                    "session-lifecycle",
                ],
            },
            application_providers=(provider,),
            control_factories=ControlPlaneFactoryRegistry((prime_control_plane_binding(),)),
            host_capabilities=("clock.monotonic", "storage.private"),
        )
    except (TypeError, ValueError):
        raise PrimeRlmExperimentError("Native RLM experiment system is invalid") from None


def build_native_rlm_control_host(
    sidecar: object,
    reservation: NativeRlmExperimentReservation,
    root: Path,
    *,
    goal: NativeRlmPrivateGoal,
    clock_ms: Callable[[], int] | None = None,
) -> ControlHost:
    """Wire the real Prime client to provider-owned native RLM lifecycle state."""
    if (
        not isinstance(reservation, NativeRlmExperimentReservation)
        or not isinstance(root, Path)
        or not root.is_dir()
        or not isinstance(goal, NativeRlmPrivateGoal)
        or not callable(getattr(sidecar, "request", None))
        or not callable(getattr(sidecar, "events", None))
        or not callable(getattr(sidecar, "close", None))
    ):
        raise PrimeRlmExperimentError("Native RLM control host is invalid")
    try:
        client = PrimeControlPlaneClient(
            process=sidecar,
            private_content=goal,
            private_attachments=goal,
        )
        return build_prime_rlm_control_host(
            session_id=_SESSION_ID,
            generation=1,
            plan=build_native_rlm_experiment_system(root),
            authority=AuthorityLedger(reservation.authority),
            journal=FileCanonicalJournal.open(root / "journal", _SESSION_ID),
            client=client,
            action_executor=_NativeRlmActionExecutor(),
            clock_ms=(lambda: int(time.time() * 1000)) if clock_ms is None else clock_ms,
            private_root=root / "rlm-private",
        )
    except (OSError, TypeError, ValueError, RuntimeError):
        raise PrimeRlmExperimentError("Native RLM control host is invalid") from None


def native_rlm_session_create_command(
    reservation: NativeRlmExperimentReservation,
) -> ControlCommand:
    """Build the sole root-session command without exposing its private goal."""
    if not isinstance(reservation, NativeRlmExperimentReservation):
        raise PrimeRlmExperimentError("Native RLM session command is invalid")
    try:
        return ControlCommand(
            command_id="native-rlm-create",
            session_id=_SESSION_ID,
            authority_revision=reservation.authority.revision,
            type="session.create",
            payload={
                "system_id": "native-rlm-probe",
                "system_version": "0.1.0",
                "goal_id": "native-rlm-goal",
                "goal_ref": _GOAL_REFERENCE,
            },
        )
    except (TypeError, ValueError):
        raise PrimeRlmExperimentError("Native RLM session command is invalid") from None


def native_rlm_start_command(
    reservation: NativeRlmExperimentReservation,
) -> ControlCommand:
    """Submit the one private root instruction after session creation."""
    if not isinstance(reservation, NativeRlmExperimentReservation):
        raise PrimeRlmExperimentError("Native RLM start command is invalid")
    try:
        return ControlCommand(
            command_id="native-rlm-start",
            session_id=_SESSION_ID,
            authority_revision=reservation.authority.revision,
            type="input.submit",
            payload={
                "input_id": "native-rlm-start",
                "delivery": "direct",
                "content_ref": _START_REFERENCE,
            },
        )
    except (TypeError, ValueError):
        raise PrimeRlmExperimentError("Native RLM start command is invalid") from None


def native_rlm_session_cancel_command(
    reservation: NativeRlmExperimentReservation,
) -> ControlCommand:
    """Stop the owned root session before its daemon is reaped."""
    if not isinstance(reservation, NativeRlmExperimentReservation):
        raise PrimeRlmExperimentError("Native RLM cancellation command is invalid")
    try:
        return ControlCommand(
            command_id="native-rlm-cleanup",
            session_id=_SESSION_ID,
            authority_revision=reservation.authority.revision,
            type="session.cancel",
            payload={"reason_code": "probe-cleanup"},
        )
    except (TypeError, ValueError):
        raise PrimeRlmExperimentError("Native RLM cancellation command is invalid") from None


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
            str(socket_path),
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
    deleted: set[str] = set()
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
            elif (
                event_type == "rlm.child.deleted"
                and set(event) == {"type", "child_id"}
                and child_id in completed
                and child_id not in deleted
            ):
                deleted.add(child_id)
            else:
                raise ValueError
    except (TypeError, ValueError):
        raise PrimeRlmExperimentError("Native RLM probe observation is invalid") from None
    child_started = bool(completed)
    child_deleted = child_started and bool(deleted) and not active
    terminal = "completed" if child_deleted and message_delivered else "uncertain"
    return NativeRlmProbeResult(
        terminal=terminal,
        child_started=child_started,
        message_delivered=message_delivered,
        child_deleted=child_deleted,
        usage=usage,
    )


async def observe_native_rlm_probe(
    client: object,
    *,
    message_action_ids: Sequence[str],
    usage: BudgetUsage,
) -> NativeRlmProbeResult:
    """Read only closed Gateway RLM observations for the admitted probe actions."""
    lifecycle_reader = getattr(client, "rlm_lifecycle", None)
    binding_reader = getattr(client, "rlm_message_binding", None)
    if (
        not callable(lifecycle_reader)
        or not callable(binding_reader)
        or not isinstance(message_action_ids, Sequence)
        or isinstance(message_action_ids, (str, bytes))
        or any(not isinstance(action_id, str) or not action_id for action_id in message_action_ids)
        or not isinstance(usage, BudgetUsage)
    ):
        raise PrimeRlmExperimentError("Native RLM probe observation is invalid")
    try:
        lifecycle = await lifecycle_reader()
        records: list[Mapping[str, str]] = []
        for event in lifecycle:
            event_type = getattr(event, "type", None)
            child_id = getattr(event, "child_id", None)
            status = getattr(event, "status", None)
            if event_type == "rlm.child.started":
                records.append({"type": event_type, "child_id": child_id})
            elif event_type == "rlm.child.terminal":
                records.append(
                    {"type": event_type, "child_id": child_id, "status": status}
                )
            elif event_type == "rlm.child.deleted":
                records.append({"type": event_type, "child_id": child_id})
            else:
                raise ValueError
        delivered = False
        for action_id in message_action_ids:
            binding = await binding_reader(action_id)
            if getattr(binding, "delivered", None) is True:
                delivered = True
        return classify_native_rlm_probe_observation(
            tuple(records), message_delivered=delivered, usage=usage
        )
    except PrimeRlmExperimentError:
        raise
    except Exception:
        raise PrimeRlmExperimentError("Native RLM probe observation is invalid") from None


async def collect_native_rlm_message_action_ids(client: object) -> tuple[str, ...]:
    """Collect the exact public action identities for native family messages."""
    events = getattr(client, "events", None)
    if not callable(events):
        raise PrimeRlmExperimentError("Native RLM probe events are invalid")
    action_ids: set[str] = set()
    try:
        stream = events()
        if not hasattr(stream, "__aiter__"):
            raise ValueError
        async for event in stream:
            if getattr(event, "type", None) != "action.proposed":
                continue
            payload = getattr(event, "payload", None)
            if not isinstance(payload, Mapping):
                raise ValueError
            if payload.get("kind") != "child.message":
                continue
            action_id = payload.get("action_id")
            if not isinstance(action_id, str) or not action_id:
                raise ValueError
            action_ids.add(action_id)
    except Exception:
        raise PrimeRlmExperimentError("Native RLM probe events are invalid") from None
    return tuple(sorted(action_ids))


async def observe_native_rlm_gateway_probe(
    client: object, *, usage: BudgetUsage
) -> NativeRlmProbeResult:
    """Compose the closed Gateway event and RLM-read surfaces for one probe."""
    action_ids = await collect_native_rlm_message_action_ids(client)
    return await observe_native_rlm_probe(
        client, message_action_ids=action_ids, usage=usage
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
        "maxContinuations": 3, "maxControllerTokens": budget.controller_tokens, "maxTurns": 12,
        "model": selection.model,
        "portfolio": [{"kind": "application", "provider_id": grant.provider_id, "application_id": grant.application_id, "version": grant.version, "runtime_id": grant.runtime_id} for grant in reservation.authority.allowed_portfolio],
        "primeSocketPath": str(root / "prime.sock"), "primeSourceRoot": str(resources.prime_source_root), "provider": selection.provider, "rlmMaxChildren": 1, "rlmMaxDepth": 1,
        "remainingBudget": {"controller_tokens": budget.controller_tokens, "application_tokens": budget.application_tokens, "child_tokens": budget.child_tokens, "aggregate_tokens": budget.aggregate_tokens, "cost_micros": budget.cost_micros, "deadline_ms": reservation.limits.deadline_ms},
        "sessionDir": str(root / "sessions"), "sessionId": "native-rlm-root", "skillPath": str(resources.skill_path), "timeoutMs": reservation.limits.deadline_ms, "workspace": str(root / "workspace"),
    })


def prepare_native_rlm_workspace(root: Path) -> None:
    """Create the closed private directories required by Prime session creation."""
    if not isinstance(root, Path) or not root.is_dir() or root.is_symlink():
        raise PrimeRlmExperimentError("Native RLM workspace is invalid")
    try:
        for name in ("agent", "gateway", "sessions", "workspace"):
            directory = root / name
            directory.mkdir(mode=0o700, exist_ok=True)
            directory.chmod(0o700)
            if (
                not directory.is_dir()
                or directory.is_symlink()
                or directory.stat().st_mode & 0o777 != 0o700
            ):
                raise OSError
    except OSError:
        raise PrimeRlmExperimentError("Native RLM workspace is invalid") from None


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
    owned_worker_cleanup: OwnedWorkerCleanup | None = None,
    owned_daemon_shutdown: OwnedDaemonShutdown | None = None,
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
        or owned_worker_cleanup is not None and not callable(owned_worker_cleanup)
        or owned_daemon_shutdown is not None and not callable(owned_daemon_shutdown)
    ):
        raise PrimeRlmExperimentError("Native RLM sidecar probe is invalid")
    prepare_native_rlm_workspace(root)
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
        sidecar_cleanup_error: PrimeRlmExperimentError | None = None
        try:
            await _close_owned_sidecar(sidecar)
        except PrimeRlmExperimentError as error:
            sidecar_cleanup_error = error
        try:
            if sidecar is not None and owned_worker_cleanup is not None:
                await owned_worker_cleanup()
        finally:
            await _reap_owned_daemon(
                daemon, plan, resources,
                shutdown=owned_daemon_shutdown,
            )
        if sidecar_cleanup_error is not None:
            raise sidecar_cleanup_error


async def start_native_rlm_sidecar(
    descriptor: Mapping[str, object],
    resources: NativeRlmRuntimeResources,
    *,
    environ: Mapping[str, str],
    starter: Callable[[object], Awaitable[object]] | None = None,
    private_stderr_sink: IO[bytes] | None = None,
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
            or private_stderr_sink is not None
            and not callable(getattr(private_stderr_sink, "fileno", None))
        ):
            raise ValueError
        from asterion.control.providers.prime.process import PrimeSidecarLaunchOptions

        options = PrimeSidecarLaunchOptions(
            node_executable=resources.node_executable,
            sidecar_entry=resources.sidecar_entry,
            private_descriptor=descriptor,
            environ={"HOME": environ["HOME"], "PATH": environ["PATH"]},
            request_timeout=30,
            private_stderr_sink=private_stderr_sink,
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


async def await_owned_native_rlm_worker_cleanup() -> None:
    """Allow Prime's owner-disconnect cleanup to stop detached workers first."""
    await asyncio.sleep(31)


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
    owned_worker_cleanup: OwnedWorkerCleanup | None = None,
    owned_daemon_shutdown: OwnedDaemonShutdown | None = None,
    private_stderr_sink: IO[bytes] | None = None,
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
            descriptor,
            resources,
            environ=environ,
            starter=sidecar_starter,
            private_stderr_sink=private_stderr_sink,
        )

    cleanup = await_owned_native_rlm_worker_cleanup if owned_worker_cleanup is None else owned_worker_cleanup
    if not callable(cleanup):
        raise PrimeRlmExperimentError("Native RLM owned cleanup is invalid")
    return await execute_native_rlm_sidecar_probe(
        reservation,
        selection,
        root,
        resources,
        environ=environ,
        daemon_launcher=launch_daemon,
        sidecar_launcher=launch_sidecar,
        probe=probe,
        owned_worker_cleanup=cleanup,
        owned_daemon_shutdown=owned_daemon_shutdown,
    )


async def run_native_rlm_controlled_probe(
    sidecar: object,
    reservation: NativeRlmExperimentReservation,
    root: Path,
    *,
    goal: NativeRlmPrivateGoal | None = None,
) -> NativeRlmProbeResult:
    """Drive one root session until the closed native RLM proof is complete.

    The root instruction is held by the private client.  The public result is
    derived solely from Gateway lifecycle/message observations and metered use.
    """
    if (
        not isinstance(reservation, NativeRlmExperimentReservation)
        or not isinstance(root, Path)
        or not root.is_dir()
        or goal is not None and not isinstance(goal, NativeRlmPrivateGoal)
    ):
        raise PrimeRlmExperimentError("Native RLM controlled probe is invalid")
    host = build_native_rlm_control_host(
        sidecar,
        reservation,
        root,
        goal=NativeRlmPrivateGoal(_PROBE_GOAL) if goal is None else goal,
    )
    observer = PrimeControlPlaneClient(
        process=sidecar,
        private_content=NativeRlmPrivateGoal(_PROBE_GOAL),
        private_attachments=NativeRlmPrivateGoal(_PROBE_GOAL),
    )
    latest = NativeRlmProbeResult(
        terminal="uncertain",
        child_started=False,
        message_delivered=False,
        child_deleted=False,
        usage=BudgetUsage.zero(),
    )
    deadline = time.monotonic() + reservation.limits.deadline_ms / 1_000
    stage = "create"
    session_created = False
    session_terminal = False
    try:
        await host.dispatch(native_rlm_session_create_command(reservation))
        session_created = True
        stage = "created"
        await host.pump()
        stage = "start"
        await host.dispatch(native_rlm_start_command(reservation))
        stage = "running"
        while time.monotonic() < deadline:
            await host.pump()
            snapshot = host.snapshot()
            latest = await observe_native_rlm_gateway_probe(
                observer, usage=snapshot.authority_usage
            )
            if latest.terminal == "completed":
                session_terminal = True
                return latest
            if snapshot.state.terminal_event_id is not None:
                terminal = snapshot.state.session_status
                if terminal not in {"cancelled", "completed", "failed", "budget_limited"}:
                    raise PrimeRlmExperimentError("Native RLM terminal state is invalid")
                session_terminal = True
                return replace(latest, terminal=terminal)
            await asyncio.sleep(0.025)
        return latest
    except PrimeRlmExperimentError:
        raise
    except Exception:
        raise PrimeRlmExperimentError(
            f"Native RLM controlled probe {stage} did not complete"
        ) from None
    finally:
        try:
            if session_created and not session_terminal:
                await host.dispatch(native_rlm_session_cancel_command(reservation))
        finally:
            await host.close()


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


async def _reap_owned_daemon(
    daemon: object,
    plan: NativeRlmDaemonPlan,
    resources: NativeRlmRuntimeResources,
    *,
    shutdown: OwnedDaemonShutdown | None = None,
) -> None:
    """Use Prime's daemon protocol; SIGTERM leaves detached workers behind."""
    if getattr(daemon, "returncode", None) is not None:
        return
    wait = getattr(daemon, "wait", None)
    if not callable(wait):
        raise PrimeRlmExperimentError("Native RLM daemon cleanup failed")
    try:
        if shutdown is not None:
            await shutdown(plan, resources)
            await asyncio.wait_for(wait(), timeout=5)
            return
        client_entry = resources.sidecar_entry.parent / "index.js"
        script = textwrap.dedent(
            f'''\
            import {{ PrimeDaemonClient }} from {client_entry.as_uri()!r};
            const client = new PrimeDaemonClient({{clientId: "asterion-owned-cleanup", connectTimeoutMs: 3000, requestTimeoutMs: 3000}});
            await client.connect({str(plan.socket_path)!r});
            await client.request({{type: "shutdown", force: true}}, "asterion-owned-cleanup", 3000);
            client.close();
            '''
        )
        shutdown = await asyncio.create_subprocess_exec(
            str(resources.node_executable), "--input-type=module", "-e", script,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        if await asyncio.wait_for(shutdown.wait(), timeout=5) != 0:
            raise RuntimeError()
        await asyncio.wait_for(wait(), timeout=5)
    except (TimeoutError, OSError, RuntimeError, TypeError, ValueError):
        raise PrimeRlmExperimentError("Native RLM daemon cleanup failed") from None


_NATIVE_RLM_RUNTIME_ENV = (
    "PRIME_AGENT_KERNEL_PYTHON",
    "PRIME_AGENT_KERNEL_VENV",
)


def build_native_rlm_daemon_environment(
    environ: Mapping[str, str], *, credential_env: str
) -> Mapping[str, str]:
    """Forward the selected credential and explicit private kernel runtime."""
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
            for key in ("HOME", "PATH", credential_env, *_NATIVE_RLM_RUNTIME_ENV)
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
            controller_tokens=50_000,
            application_tokens=50_000,
            child_tokens=50_000,
            aggregate_tokens=150_000,
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
