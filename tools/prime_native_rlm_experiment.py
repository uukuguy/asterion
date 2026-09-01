"""Pure preparation boundary for one bounded native Prime RLM experiment."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field, replace
from hashlib import sha256
import asyncio
import inspect
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
from asterion.control.application_executor import ApplicationActionExecutor
from asterion.control.factory import ControlPlaneFactoryRegistry
from asterion.control.host import ControlCommand, ControlEvent
from asterion.control.journal import FileCanonicalJournal
from asterion.control.manager import (
    ControlHost,
    ControlHostError,
    ControlHostTransportError,
)
from asterion.control.providers.prime.client import (
    PrimeControlPlaneClient,
    RlmAdmissionBinding,
)
from asterion.control.providers.prime.factory import prime_control_plane_binding
from asterion.control.providers.prime.rlm import build_prime_rlm_control_host
from asterion.control.providers.prime.system_actions import PrimeSystemActionService
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
from asterion.runtime.factory import RuntimeFactoryBinding, RuntimeFactoryRegistry
from asterion.runtime.host import RuntimeManifest
try:
    from tools.verify_prime_loop import PrimeVerificationError, load_bounded_rlm_authority
except ModuleNotFoundError:  # Direct ``python tools/verify_prime_loop.py`` execution.
    from verify_prime_loop import PrimeVerificationError, load_bounded_rlm_authority


_MAX_COST_MICROS = 500_000
_MAX_DEADLINE_MS = 600_000
_PUMP_TIMEOUT_SECONDS = 10
_NATIVE_RLM_SYSTEM_ACTION_DEADLINE_MS = 300_000
_MODEL_KEY = "ASTERION_PRIME_EXPERIMENT_MODEL"
_SESSION_ID = "native-rlm-root"
_GOAL_REFERENCE = "native-rlm-goal"
_START_REFERENCE = "native-rlm-start-input"
_CONTINUE_REFERENCE = "native-rlm-continue-input"
_APPLICATION_TARGET = {
    "kind": "application",
    "provider_id": "asterion.prime-gateway",
    "application_id": "native-rlm-probe",
    "version": "0.1.0",
    "runtime_id": "prime.gateway",
}
_PERSISTENT_PROBE_GOAL = (
    "Complete one native RLM child lifecycle: start one child, deliver one ping, "
    "delete that child, then complete the goal."
)
_PROBE_START = (
    "Do not answer with prose. Use the IPython tool now and execute exactly this code:\n"
    "handle = await rlm('Reply exactly pong to the parent, then finish.', "
    "name='native-rlm-child')\n"
    "await agent_message.send('ping', receiver_role='child', receiver_name=handle.name)\n"
    "Do not use another tool or create another child. When pong arrives as a later prompt, use IPython "
    "to execute `await rlm.delete_subagent(handle.rlm_child_id)` and then `await goal.complete()`."
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

    _SAFE_CODES = frozenset(
        {
            "pump_timeout",
            "pump_timeout-authority-sync",
            "pump_timeout-binding-rebuild",
            "pump_timeout-provider-reconcile",
            "pump_timeout-pending-actions",
            "pump_timeout-event-read",
            "pump_timeout-event-accept",
            "pump_timeout-action-admission",
            "observation_timeout",
            "control",
            "event-transport",
            "event-transport-authority-sync",
            "event-transport-event-read",
            "event-transport-event-read-response-timeout",
            "event-transport-event-read-sidecar-error",
            "event-transport-event-read-response-eof",
            "event-transport-event-read-response-invalid",
            "event-transport-event-read-event-protocol",
            "event-transport-event-read-event-runtime",
            "event-transition",
            "event-transition-action-proposed-created",
            "event-transition-action-proposed-paused",
            "event-transition-action-proposed-recovery-required",
            "event-transition-action-proposed-none",
            "event-transition-action-proposed-other",
            "action-admission",
            "provider-lifecycle",
            "provider-lifecycle-gateway",
            "provider-lifecycle-binding",
            "provider-lifecycle-transition",
            "provider-lifecycle-terminal",
            "provider-lifecycle-reconcile",
            "provider-lifecycle-settlement",
            "event-journal",
            "budget-report",
            "event-invalid",
            "detach-control",
            "attach-control",
            "daemon-start",
            "sidecar-start",
            "probe",
        }
    )

    def __init__(self, message: str, *, safe_code: str | None = None) -> None:
        if safe_code is not None and safe_code not in self._SAFE_CODES:
            raise ValueError("Native RLM experiment error is invalid")
        caller = inspect.currentframe()
        line = caller.f_back.f_lineno if caller is not None and caller.f_back is not None else 0
        self.safe_code = safe_code or f"experiment_line_{line}"
        super().__init__(message)


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
    checkpoint_recovered: bool = False
    detach_attached: bool = False
    cancelled: bool = False
    budget_limited: bool = False
    application_receipted: bool = False
    child_model_selected: bool = False
    generated_program_admitted: bool = False
    recursion_depth_limited: bool = False
    observed_event_types: tuple[str, ...] = ()
    causal_identities: Mapping[str, tuple[str, str]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    children_started: int = 0
    children_completed: int = 0
    children_deleted: int = 0
    work_continued_after_attach: bool = False
    control_event_sequence_contiguous: bool = False
    terminal_count: int = 0
    observation_health: str = "unknown"
    observation_gap_count: int = 0


def _require_native_rlm_skill_success(
    result: object, *, operation: str
) -> None:
    """Validate the closed Skill Bridge admission/terminal pair."""

    if not isinstance(result, Mapping) or operation not in {"application", "checkpoint", "goal"}:
        raise PrimeRlmExperimentError("Native RLM controlled probe skill result is invalid")
    admission = result.get("admission")
    terminal = result.get("terminal")
    if not isinstance(admission, Mapping):
        raise PrimeRlmExperimentError(
            f"Native RLM controlled probe {operation} admission is invalid"
        )
    if admission.get("resolution") != "admitted":
        raise PrimeRlmExperimentError(
            f"Native RLM controlled probe {operation} admission was rejected "
            + _native_rlm_admission_failure_category(admission.get("reason_code"))
        )
    if not isinstance(terminal, Mapping):
        raise PrimeRlmExperimentError(
            f"Native RLM controlled probe {operation} terminal is invalid"
        )
    if terminal.get("resolution") != "succeeded":
        raise PrimeRlmExperimentError(
            f"Native RLM controlled probe {operation} terminal did not succeed"
        )


def _require_native_rlm_skill_budget_rejection(result: object) -> None:
    """Require the host to reject the deliberate over-budget proposal."""
    if not isinstance(result, Mapping):
        raise PrimeRlmExperimentError("Native RLM budget probe result is invalid")
    admission = result.get("admission")
    if (
        not isinstance(admission, Mapping)
        or admission.get("resolution") != "rejected"
        or admission.get("reason_code") != "budget-exceeded"
        or "terminal" in result
    ):
        raise PrimeRlmExperimentError(
            "Native RLM budget probe was not rejected"
        )


@dataclass(frozen=True, repr=False)
class NativeRlmPrivateGoal:
    """One private root instruction; its text never enters public evidence."""

    goal_text: str
    start_text: str | None = None
    continue_text: str | None = None

    def resolve_text(self, reference: str, *, max_bytes: int) -> str:
        values = {
            _GOAL_REFERENCE: self.goal_text,
            _START_REFERENCE: self.start_text or self.goal_text,
            _CONTINUE_REFERENCE: self.continue_text or self.goal_text,
        }
        value = values.get(reference)
        if not isinstance(value, str) or not isinstance(max_bytes, int) or max_bytes < len(value.encode("utf-8")):
            raise KeyError("private native RLM input is unavailable")
        return value

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
LifecyclePreflight = Callable[[Path], Awaitable[None]]


async def _send_native_rlm_skill_effect(
    root: Path, *, operation: str, payload: Mapping[str, object]
) -> Mapping[str, object]:
    """Use the same private skill socket as Prime's kernel, without model mediation."""

    if operation not in {
        "application.invoke",
        "child.spawn",
        "child.message",
        "child.cancel",
        "checkpoint.request",
        "goal.complete",
        "goal.fail",
    } or not isinstance(root, Path):
        raise PrimeRlmExperimentError("Native RLM skill effect is invalid")
    stage = "discovery"
    try:
        discovery = json.loads((root / "agent" / "asterion-control.json").read_text("utf-8"))
        socket_path = discovery["socket_path"]
        token = discovery["token"]
        session_id = discovery["session_id"]
        if not all(isinstance(value, str) and value for value in (socket_path, token, session_id)):
            raise ValueError
        request_id = "probe-" + secrets.token_hex(16)
        stage = "connect"
        reader, writer = await asyncio.open_unix_connection(socket_path)
        try:
            stage = "request"
            for value in (
                {"protocol": "asterion.skill-control/v1", "type": "authenticate", "token": token, "session_id": session_id},
                {"protocol": "asterion.skill-control/v1", "request_id": request_id, "session_id": session_id, "operation": operation, "payload": dict(payload)},
            ):
                writer.write(json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n")
            await writer.drain()
            raw = await reader.readline()
            response = json.loads(raw)
        finally:
            writer.close()
            await writer.wait_closed()
        if isinstance(response, Mapping) and response.get("status") == "error":
            code = response.get("code")
            stage = {
                "authentication-failed": "authentication",
                "request-invalid": "request-invalid",
                "request-conflicts": "request-conflicts",
                "request-too-large": "request-too-large",
            }.get(code, "request")
            raise ValueError
        if (
            not isinstance(response, Mapping)
            or response.get("protocol") != "asterion.skill-control/v1"
            or response.get("request_id") != request_id
            or response.get("status") != "ok"
            or not isinstance(response.get("result"), Mapping)
        ):
            raise ValueError
        return MappingProxyType(dict(response["result"]))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        raise PrimeRlmExperimentError(
            f"Native RLM skill {stage} did not complete"
        ) from None


async def _probe_native_rlm_depth_limit(
    root: Path,
    reservation: NativeRlmExperimentReservation,
    model_selector_digest: str,
) -> str:
    """Submit one over-depth private bridge proposal and retain only its resolution."""

    stage = "discovery"
    try:
        discovery = json.loads(
            (root / "agent" / "asterion-rlm-host.json").read_text("utf-8")
        )
        if (
            not isinstance(discovery, Mapping)
            or set(discovery)
            != {"protocol", "socket_path", "token", "session_id", "budget"}
            or discovery.get("protocol") != "asterion.prime-rlm-host-discovery/v1"
            or not isinstance(discovery.get("socket_path"), str)
            or not isinstance(discovery.get("token"), str)
            or not isinstance(discovery.get("session_id"), str)
            or not isinstance(discovery.get("budget"), Mapping)
        ):
            raise ValueError
        stage = "connect"
        reader, writer = await asyncio.open_unix_connection(discovery["socket_path"])
        try:
            request_id = "rlm-depth-" + secrets.token_hex(16)
            proposal = {
                "type": "rlm.spawn.propose",
                "request_id": request_id,
                "child_id": "rlm-depth-probe",
                "idempotency_key": request_id,
                "goal_text": "",
                "rlm_depth": reservation.authority.max_recursion_depth + 1,
                "model_selector_digest": model_selector_digest,
                "budget": dict(discovery["budget"]),
            }
            for frame in (
                {
                    "protocol": "asterion.prime-rlm-host/v1",
                    "type": "authenticate",
                    "token": discovery["token"],
                    "session_id": discovery["session_id"],
                },
                proposal,
            ):
                writer.write(
                    json.dumps(frame, sort_keys=True, separators=(",", ":")).encode()
                    + b"\n"
                )
            await writer.drain()
            response = json.loads(await reader.readline())
        finally:
            writer.close()
            await writer.wait_closed()
        if (
            not isinstance(response, Mapping)
            or set(response) != {"resolution", "childId"}
            or response.get("childId") != "rlm-depth-probe"
            or response.get("resolution") not in {"admitted", "rejected", "uncertain"}
        ):
            raise ValueError
        return str(response["resolution"])
    except Exception:
        raise PrimeRlmExperimentError(
            f"Native RLM depth probe {stage} did not complete"
        ) from None


def _native_rlm_system_action_deadline(
    reservation: NativeRlmExperimentReservation,
) -> int:
    """Return the bounded default deadline for a gateway-materialized action."""

    if not isinstance(reservation, NativeRlmExperimentReservation):
        raise PrimeRlmExperimentError("Native RLM action deadline is invalid")
    return min(
        _NATIVE_RLM_SYSTEM_ACTION_DEADLINE_MS,
        reservation.authority.max_action_deadline_ms,
        reservation.limits.deadline_ms,
    )


def _native_rlm_pump_timeout_seconds(
    reservation: NativeRlmExperimentReservation,
    exercise_checkpoint: bool,
    *,
    active_detach: bool = False,
) -> int:
    """Allow one authorized native gateway operation to settle."""

    if (
        not isinstance(reservation, NativeRlmExperimentReservation)
        or not isinstance(exercise_checkpoint, bool)
        or not isinstance(active_detach, bool)
    ):
        raise PrimeRlmExperimentError("Native RLM pump deadline is invalid")
    return max(
        _PUMP_TIMEOUT_SECONDS,
        _native_rlm_system_action_deadline(reservation) // 1_000 + 5,
    )


class _NativeRlmActionExecutor:
    """Defensive fence: admitted native RLM work must remain provider-owned."""

    async def execute(
        self, proposal: ControlEvent, signal: object
    ) -> ActionExecutionReceipt:
        del proposal, signal
        raise RuntimeError("native RLM action escaped provider ownership")


class _NativeRlmDeniedOperationDispatcher:
    """Identity-bound callback surface for a probe with no operation grants."""

    def __init__(
        self, reservation: NativeRlmExperimentReservation, session_id: str
    ) -> None:
        self._session_id = session_id
        self._authority_id = reservation.authority.authority_id
        self._authority_revision = reservation.authority.revision

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def generation(self) -> int:
        return 1

    @property
    def authority_id(self) -> str:
        return self._authority_id

    @property
    def authority_revision(self) -> int:
        return self._authority_revision

    async def execute(self, transaction: object) -> object:
        del transaction
        raise PrimeRlmExperimentError("Native RLM operation is not authorized")

    async def cancel(self, operation_id: str, *, authority_revision: int) -> object:
        del operation_id, authority_revision
        raise PrimeRlmExperimentError("Native RLM operation is not authorized")

    async def reconcile(self, transaction: object) -> object:
        del transaction
        raise PrimeRlmExperimentError("Native RLM operation is not authorized")


class _BoundedProbeRuntime:
    """A no-capability runtime for the explicit verification application."""

    manifest = RuntimeManifest(runtime_id="prime.gateway", capabilities=())

    async def run(self, *args: object, **kwargs: object):
        del args, kwargs
        if False:
            yield None


def build_native_rlm_application_executor(
    plan: AgentSystemPlan, client: PrimeControlPlaneClient, root: Path
) -> ApplicationActionExecutor:
    """Bind the virtual probe application to the normal host execution path."""
    if not isinstance(plan, AgentSystemPlan) or not isinstance(root, Path):
        raise PrimeRlmExperimentError("Native RLM application executor is invalid")
    try:
        from tools.prime_bounded_loop_experiment import BoundedLoopPrivateResultStore

        applications = tuple(entry.application for entry in plan.portfolio)
        provider = InstalledApplicationProvider(
            protocol=APPLICATION_PROVIDER_PROTOCOL,
            provider_id="asterion.prime-gateway",
            resource_root=root,
            applications=applications,
        )
        factories = RuntimeFactoryRegistry(
            (
                RuntimeFactoryBinding(
                    runtime_id="prime.gateway",
                    capabilities=(),
                    factory=lambda _context: _BoundedProbeRuntime(),
                ),
            )
        )
        return ApplicationActionExecutor(
            plan=plan,
            providers=(provider,),
            runtime_factories=factories,
            runtime_options={identity: {} for identity in plan.portfolio_by_identity},
            content=client,
            results=BoundedLoopPrivateResultStore(),
            host_services={},
            system_service=PrimeSystemActionService(client),
        )
    except (ImportError, TypeError, ValueError):
        raise PrimeRlmExperimentError(
            "Native RLM application executor is invalid"
        ) from None


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
    session_id: str = _SESSION_ID,
    clock_ms: Callable[[], int] | None = None,
    event_observer: Callable[[ControlEvent], None] | None = None,
) -> ControlHost:
    """Wire the real Prime client to provider-owned native RLM lifecycle state."""
    if (
        not isinstance(reservation, NativeRlmExperimentReservation)
        or not isinstance(root, Path)
        or not root.is_dir()
        or not isinstance(goal, NativeRlmPrivateGoal)
        or not isinstance(session_id, str)
        or not session_id
        or not callable(getattr(sidecar, "request", None))
        or not callable(getattr(sidecar, "events", None))
        or not callable(getattr(sidecar, "close", None))
        or event_observer is not None and not callable(event_observer)
    ):
        raise PrimeRlmExperimentError("Native RLM control host is invalid")
    try:
        client = PrimeControlPlaneClient(
            process=sidecar,
            private_content=goal,
            private_attachments=goal,
            event_observer=event_observer,
        )
        system = build_native_rlm_experiment_system(root)
        return build_prime_rlm_control_host(
            session_id=session_id,
            generation=1,
            plan=system,
            authority=AuthorityLedger(reservation.authority),
            journal=FileCanonicalJournal.open(root / "journal", session_id),
            client=client,
            action_executor=build_native_rlm_application_executor(system, client, root),
            clock_ms=(lambda: int(time.time() * 1000)) if clock_ms is None else clock_ms,
            private_root=root / "rlm-private",
        )
    except (OSError, TypeError, ValueError, RuntimeError):
        raise PrimeRlmExperimentError("Native RLM control host is invalid") from None


def native_rlm_session_create_command(
    reservation: NativeRlmExperimentReservation,
    *,
    session_id: str = _SESSION_ID,
) -> ControlCommand:
    """Build the sole root-session command without exposing its private goal."""
    if not isinstance(reservation, NativeRlmExperimentReservation) or not isinstance(session_id, str) or not session_id:
        raise PrimeRlmExperimentError("Native RLM session command is invalid")
    try:
        return ControlCommand(
            command_id="native-rlm-create",
            session_id=session_id,
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
    *,
    session_id: str = _SESSION_ID,
) -> ControlCommand:
    """Submit the one private root instruction after session creation."""
    if not isinstance(reservation, NativeRlmExperimentReservation) or not isinstance(session_id, str) or not session_id:
        raise PrimeRlmExperimentError("Native RLM start command is invalid")
    try:
        return ControlCommand(
            command_id="native-rlm-start",
            session_id=session_id,
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


def native_rlm_continue_command(
    reservation: NativeRlmExperimentReservation,
    *,
    session_id: str = _SESSION_ID,
) -> ControlCommand:
    """Submit one distinct private continuation after an active reattach."""
    if not isinstance(reservation, NativeRlmExperimentReservation) or not isinstance(session_id, str) or not session_id:
        raise PrimeRlmExperimentError("Native RLM continuation command is invalid")
    try:
        return ControlCommand(
            command_id="native-rlm-continue", session_id=session_id,
            authority_revision=reservation.authority.revision,
            type="input.submit",
            payload={
                "input_id": "native-rlm-continue", "delivery": "steer",
                "content_ref": _CONTINUE_REFERENCE,
            },
        )
    except (TypeError, ValueError):
        raise PrimeRlmExperimentError("Native RLM continuation command is invalid") from None


def native_rlm_session_detach_command(
    reservation: NativeRlmExperimentReservation,
    *,
    session_id: str = _SESSION_ID,
) -> ControlCommand:
    """Detach the owned Prime root through the public control contract."""
    if not isinstance(reservation, NativeRlmExperimentReservation) or not isinstance(session_id, str) or not session_id:
        raise PrimeRlmExperimentError("Native RLM detach command is invalid")
    try:
        return ControlCommand(
            command_id="native-rlm-detach",
            session_id=session_id,
            authority_revision=reservation.authority.revision,
            type="session.detach",
            payload={"reason_code": "bounded-receipt"},
        )
    except (TypeError, ValueError):
        raise PrimeRlmExperimentError("Native RLM detach command is invalid") from None


def native_rlm_session_pause_command(
    reservation: NativeRlmExperimentReservation,
    *,
    session_id: str = _SESSION_ID,
) -> ControlCommand:
    """Pause an owned root before its independent checkpoint boundary."""
    if not isinstance(reservation, NativeRlmExperimentReservation) or not isinstance(session_id, str) or not session_id:
        raise PrimeRlmExperimentError("Native RLM pause command is invalid")
    try:
        return ControlCommand(
            command_id="native-rlm-maintenance-pause",
            session_id=session_id,
            authority_revision=reservation.authority.revision,
            type="session.pause",
            payload={"reason_code": "checkpoint-boundary"},
        )
    except (TypeError, ValueError):
        raise PrimeRlmExperimentError("Native RLM pause command is invalid") from None


def native_rlm_session_attach_command(
    reservation: NativeRlmExperimentReservation,
    *,
    session_id: str = _SESSION_ID,
) -> ControlCommand:
    """Reattach the exact owned root without deriving authority from Prime."""
    if not isinstance(reservation, NativeRlmExperimentReservation) or not isinstance(session_id, str) or not session_id:
        raise PrimeRlmExperimentError("Native RLM attach command is invalid")
    try:
        return ControlCommand(
            command_id="native-rlm-attach",
            session_id=session_id,
            authority_revision=reservation.authority.revision,
            type="session.attach",
            payload={"cursor": {"generation": 1, "sequence": 0}},
        )
    except (TypeError, ValueError):
        raise PrimeRlmExperimentError("Native RLM attach command is invalid") from None


def native_rlm_session_cancel_command(
    reservation: NativeRlmExperimentReservation,
    *,
    session_id: str = _SESSION_ID,
) -> ControlCommand:
    """Stop the owned root session before its daemon is reaped."""
    if not isinstance(reservation, NativeRlmExperimentReservation) or not isinstance(session_id, str) or not session_id:
        raise PrimeRlmExperimentError("Native RLM cancellation command is invalid")
    try:
        return ControlCommand(
            command_id="native-rlm-cleanup",
            session_id=session_id,
            authority_revision=reservation.authority.revision,
            type="session.cancel",
            payload={"reason_code": "probe-cleanup"},
        )
    except (TypeError, ValueError):
        raise PrimeRlmExperimentError("Native RLM cancellation command is invalid") from None


def resolve_native_rlm_model(environ: Mapping[str, str]) -> NativeRlmModelSelection:
    """Resolve the sole model/provider pairing authorized for this first probe."""
    if not isinstance(environ, Mapping):
        raise PrimeRlmExperimentError("Native RLM experiment model is invalid")
    model = environ.get(_MODEL_KEY)
    if model not in {"deepseek-v4-flash", "deepseek-v4-flash-0731"}:
        raise PrimeRlmExperimentError("Native RLM experiment model is invalid")
    return NativeRlmModelSelection("deepseek", model, "DEEPSEEK_API_KEY")


def native_rlm_model_selector_digest(selection: NativeRlmModelSelection) -> str:
    """Derive the exact private-shim model selector without exposing its values."""

    if not isinstance(selection, NativeRlmModelSelection):
        raise PrimeRlmExperimentError("Native RLM model selection is invalid")
    return sha256((selection.provider + "\0" + selection.model).encode()).hexdigest()


def derive_native_rlm_model_assertions(
    *,
    binding: RlmAdmissionBinding,
    expected_model_selector_digest: str,
    usage: BudgetUsage,
    depth_probe_resolution: str,
) -> dict[str, bool]:
    """Reduce three model-dependent RLM facts from closed bounded observations."""

    if (
        not isinstance(binding, RlmAdmissionBinding)
        or not isinstance(expected_model_selector_digest, str)
        or len(expected_model_selector_digest) != 64
        or any(character not in "0123456789abcdef" for character in expected_model_selector_digest)
        or not isinstance(usage, BudgetUsage)
        or depth_probe_resolution not in {"admitted", "rejected", "uncertain"}
    ):
        raise PrimeRlmExperimentError("Native RLM model evidence is invalid")
    exact_binding = (
        binding.depth == 1
        and binding.model_selector_digest == expected_model_selector_digest
    )
    return {
        "child_model_selected": exact_binding,
        "generated_program_admitted": exact_binding and usage.controller_tokens > 0,
        "recursion_depth_limited": depth_probe_resolution == "rejected",
    }


def write_native_rlm_model_evidence_receipt(
    root: Path,
    reservation: NativeRlmExperimentReservation,
    assertions: Mapping[str, object],
) -> dict[str, object]:
    """Persist one body-free receipt for the three model-dependent RLM facts."""

    required = {
        "child_model_selected",
        "generated_program_admitted",
        "recursion_depth_limited",
    }
    if (
        not isinstance(root, Path)
        or not root.is_dir()
        or root.is_symlink()
        or not isinstance(reservation, NativeRlmExperimentReservation)
        or not reservation.consumed
        or not isinstance(assertions, Mapping)
        or set(assertions) != required
        or any(assertions[key] is not True for key in required)
    ):
        raise PrimeRlmExperimentError("Native RLM model evidence is incomplete")
    payload: dict[str, object] = {
        "format": "asterion.prime-native-rlm-model-evidence/v1",
        "configuration_digest": reservation.configuration_digest,
        "status": "PASS",
        **{key: True for key in sorted(required)},
    }
    target = root / "native-rlm-model-evidence.json"
    if target.exists():
        raise PrimeRlmExperimentError("Native RLM model evidence is unavailable")
    descriptor, temporary = tempfile.mkstemp(prefix=".native-rlm-model-", dir=root)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except OSError:
        raise PrimeRlmExperimentError("Native RLM model evidence is unavailable") from None
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return payload


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
        children_started=len(active | completed),
        children_completed=len(completed),
        children_deleted=len(deleted),
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
    stage = "lifecycle"
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
        stage = "message-binding"
        delivered = False
        for action_id in message_action_ids:
            try:
                binding = await binding_reader(action_id)
            except Exception:
                # Prime emits family replies as child.message proposals too,
                # while only parent-directed sends have an Asterion binding.
                # Ignore those unbound replies; a bound delivered send remains
                # the sole positive message-evidence path.
                continue
            if getattr(binding, "delivered", None) is True:
                delivered = True
        return classify_native_rlm_probe_observation(
            tuple(records), message_delivered=delivered, usage=usage
        )
    except PrimeRlmExperimentError:
        raise
    except Exception:
        raise PrimeRlmExperimentError(
            f"Native RLM probe observation {stage} is invalid"
        ) from None


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
    client: object,
    *,
    usage: BudgetUsage,
    message_action_ids: Sequence[str] | None = None,
) -> NativeRlmProbeResult:
    """Compose closed Gateway evidence, reusing the validated pump when present."""
    if message_action_ids is None:
        try:
            action_ids = await collect_native_rlm_message_action_ids(client)
        except PrimeRlmExperimentError:
            raise PrimeRlmExperimentError(
                "Native RLM probe observation message-actions is invalid"
            ) from None
    elif (
        isinstance(message_action_ids, (str, bytes))
        or not isinstance(message_action_ids, Sequence)
        or any(not isinstance(action_id, str) or not action_id for action_id in message_action_ids)
    ):
        raise PrimeRlmExperimentError(
            "Native RLM probe observation message-actions is invalid"
        )
    else:
        action_ids = tuple(sorted(set(message_action_ids)))
    return await observe_native_rlm_probe(
        client, message_action_ids=action_ids, usage=usage
    )


def build_native_rlm_sidecar_descriptor(
    reservation: NativeRlmExperimentReservation,
    selection: NativeRlmModelSelection,
    root: Path,
    resources: NativeRlmRuntimeResources,
    *,
    session_id: str = _SESSION_ID,
    daemon_lifecycle: Mapping[str, str] | None = None,
    operation_host: Mapping[str, str],
) -> Mapping[str, object]:
    """Build the closed private descriptor for the single native probe session."""
    if (
        not isinstance(reservation, NativeRlmExperimentReservation)
        or not isinstance(selection, NativeRlmModelSelection)
        or not isinstance(root, Path)
        or not isinstance(resources, NativeRlmRuntimeResources)
        or not isinstance(session_id, str)
        or not session_id
        or daemon_lifecycle is not None
        and (
            not isinstance(daemon_lifecycle, Mapping)
            or set(daemon_lifecycle) != {"socketPath", "token"}
            or any(not isinstance(value, str) or not value for value in daemon_lifecycle.values())
        )
        or not isinstance(operation_host, Mapping)
        or set(operation_host) != {"socketPath", "token"}
        or any(not isinstance(value, str) or not value for value in operation_host.values())
    ):
        raise PrimeRlmExperimentError("Native RLM sidecar descriptor is invalid")
    budget = reservation.authority.budget_limit
    descriptor: dict[str, object] = {
        "agentDir": str(root / "agent"), "artifactLockPath": str(resources.artifact_lock_path),
        "authorityId": reservation.authority.authority_id, "authorityRevision": reservation.authority.revision,
        "authorityExpiresAtMs": reservation.authority.expires_at_ms,
        "expectedRuntimeBuildId": resources.expected_runtime_build_id, "gatewayRoot": str(root / "gateway"), "generation": 1,
        "maxContinuations": 3, "maxControllerTokens": budget.controller_tokens, "maxTurns": 12,
        "model": selection.model,
        "operationHost": dict(operation_host),
        "portfolio": [{"kind": "application", "provider_id": grant.provider_id, "application_id": grant.application_id, "version": grant.version, "runtime_id": grant.runtime_id} for grant in reservation.authority.allowed_portfolio],
        "primeSocketPath": str(root / "prime.sock"), "primeSourceRoot": str(resources.prime_source_root), "provider": selection.provider, "probeReady": True, "rlmMaxChildren": reservation.authority.max_concurrent_children, "rlmMaxDepth": 1,
        "remainingBudget": {"controller_tokens": budget.controller_tokens, "application_tokens": budget.application_tokens, "child_tokens": budget.child_tokens, "aggregate_tokens": budget.aggregate_tokens, "cost_micros": budget.cost_micros, "deadline_ms": reservation.limits.deadline_ms},
        "sessionDir": str(root / "sessions"), "sessionId": session_id, "skillPath": str(resources.skill_path), "timeoutMs": reservation.limits.deadline_ms, "workspace": str(root / "workspace"),
    }
    if daemon_lifecycle is not None:
        descriptor["daemonLifecycle"] = dict(daemon_lifecycle)
    return RedactedImmutableMapping(descriptor)


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
    session_id: str = _SESSION_ID,
    owned_worker_cleanup: OwnedWorkerCleanup | None = None,
    owned_daemon_shutdown: OwnedDaemonShutdown | None = None,
    lifecycle_preflight: LifecyclePreflight | None = None,
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
        or not isinstance(session_id, str)
        or not session_id
        or owned_worker_cleanup is not None and not callable(owned_worker_cleanup)
        or owned_daemon_shutdown is not None and not callable(owned_daemon_shutdown)
        or lifecycle_preflight is not None and not callable(lifecycle_preflight)
    ):
        raise PrimeRlmExperimentError("Native RLM sidecar probe is invalid")
    prepare_native_rlm_workspace(root)
    phase = "daemon-plan"
    def boundary(stage: str) -> None:
        nonlocal phase
        phase = stage
        try:
            (root / "asterion-native-boundary").write_text(stage + "\n", encoding="ascii")
        except OSError:
            pass
    boundary("daemon-plan")
    plan = build_native_rlm_daemon_plan(
        resources.node_executable,
        resources.daemon_entry,
        root / "prime.sock",
        selection,
        environ,
    )
    # Prime's supervisor persists update manifests under its *process-default*
    # agentDir, not the per-session create command.  Bind that default to the
    # same private root used by the descriptor and coordinator so recovery has
    # one exact manifest authority.
    plan = NativeRlmDaemonPlan(
        argv=plan.argv,
        environ=MappingProxyType({
            **dict(plan.environ),
            "PRIME_AGENT_CODING_AGENT_DIR": str(root / "agent"),
        }),
        socket_path=plan.socket_path,
    )
    boundary("daemon-start")
    daemon = await start_native_rlm_daemon(
        plan, launcher=daemon_launcher, timeout_seconds=10
    )
    sidecar: object | None = None
    lifecycle_server: object | None = None
    operation_host: object | None = None
    primary_failure = False
    completed_probe = False
    try:
        from asterion.control.providers.prime.process import (
            PrimeDaemonLifecycle,
            PrimeDaemonLifecycleFailure,
            PrimeDaemonLifecycleServer,
        )
        from asterion.control.providers.prime.operation_host import PrimeOperationHostServer

        async def stop_daemon(active_session_id: str) -> None:
            # `prepare_update_restart` has persisted the recovery manifest.
            # Its coordinator must observe a stopped predecessor before it can
            # restore the manifest; calling the public update CLI is neither
            # necessary nor permitted here.
            nonlocal daemon
            lifecycle_marker = root / "daemon-lifecycle-stage"
            if getattr(daemon, "returncode", None) is None:
                wait = getattr(daemon, "wait", None)
                if not callable(wait):
                    raise PrimeRlmExperimentError("Native RLM daemon restart failed")
                # The original transport issued Prime's prepared-state
                # shutdown.  Waiting for that graceful exit preserves the
                # upstream startup fence; a host SIGTERM would erase it.
                await asyncio.wait_for(wait(), timeout=15)
            coordinator_module = (
                resources.prime_source_root
                / "packages" / "coding-agent" / "dist" / "package-manager-cli.js"
            )
            status_path = root / "daemon-restart-status.json"
            runner_path = root / "daemon-restart-coordinator.mjs"
            script = textwrap.dedent(
                f'''\
                if (process.argv.includes("--mode")) {{
                  process.argv[1] = {str(resources.daemon_entry)!r};
                  await import({resources.daemon_entry.as_uri()!r});
                }} else {{
                const {{ runDaemonUpdateRestartCoordinator }} = await import({coordinator_module.as_uri()!r});
                const result = await runDaemonUpdateRestartCoordinator({{
                  socketPath: {str(plan.socket_path)!r}, agentDir: {str(root / 'agent')!r},
                  statusPath: {str(status_path)!r}, originActiveSessionId: {active_session_id!r},
                }});
                if (!["complete", "skipped"].includes(result.phase)) {{
                  process.stderr.write(`asterion-prime-coordinator-phase:${{result.phase}}\\n`);
                }}
                if (result.phase !== "complete" || result.counts.failed !== 0) process.exit(2);
                // The successor daemon is detached by Prime's launcher.
                // Exit this coordinator wrapper after a completed handoff.
                process.exit(0);
                }}
                '''
            )
            runner_path.write_text(script, encoding="utf-8")
            runner_path.chmod(0o600)
            restart = await asyncio.create_subprocess_exec(
                str(resources.node_executable), str(runner_path),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                # Coordinator details can contain private daemon state.  The
                # lifecycle boundary returns only its fixed failure category.
                stderr=asyncio.subprocess.DEVNULL,
                cwd=resources.prime_source_root,
                env=dict(plan.environ),
            )
            try:
                restart_code = await asyncio.wait_for(restart.wait(), timeout=180)
            except TimeoutError:
                if restart.returncode is None:
                    restart.terminate()
                    with suppress(TimeoutError):
                        await asyncio.wait_for(restart.wait(), timeout=5)
                raise PrimeDaemonLifecycleFailure("coordinator") from None
            if restart_code != 0:
                phase = "coordinator"
                try:
                    status = json.loads(status_path.read_text(encoding="utf-8"))
                    status_phase = status.get("phase") if isinstance(status, Mapping) else None
                    if status_phase == "skipped":
                        phase = "manifest"
                    message = status.get("message") if isinstance(status, Mapping) else None
                    if isinstance(message, str):
                        lower = message.lower()
                        if "no running daemon needed" in lower:
                            phase = "manifest"
                        elif "prepare" in lower:
                            phase = "prepare"
                        elif "stop" in lower or "predecessor" in lower:
                            phase = "shutdown"
                        elif "fence" in lower:
                            phase = "fence"
                        elif "starting" in lower or "replacement" in lower:
                            phase = "start"
                        elif "restore" in lower:
                            phase = "restore"
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    pass
                raise PrimeDaemonLifecycleFailure(phase)
            lifecycle_marker.write_text("coordinator-exited\n", encoding="ascii")

        async def start_daemon(_: str) -> None:
            (root / "daemon-lifecycle-stage").write_text("lifecycle-returned\n", encoding="ascii")
            return None

        lifecycle = PrimeDaemonLifecycle(
            stop=stop_daemon, start=start_daemon, timeout=240
        )
        boundary("lifecycle-server")
        lifecycle_server = PrimeDaemonLifecycleServer(
            lifecycle=lifecycle,
            socket_path=root / "daemon-lifecycle.sock",
            token=secrets.token_hex(32),
            session_id=session_id,
            diagnostic=lambda stage: (root / "daemon-lifecycle-request").write_text(
                stage + "\n", encoding="ascii"
            ),
        )
        await lifecycle_server.start()
        boundary("operation-host")
        operation_host = PrimeOperationHostServer(
            dispatcher=_NativeRlmDeniedOperationDispatcher(reservation, session_id),
            private_root=root.resolve(strict=True),
            token=secrets.token_hex(32),
            request_timeout=min(5.0, reservation.limits.deadline_ms / 1_000),
        )
        await operation_host.start()
        if lifecycle_preflight is not None:
            await lifecycle_preflight(root / "daemon-lifecycle.sock")
        descriptor = build_native_rlm_sidecar_descriptor(
            reservation,
            selection,
            root,
            resources,
            session_id=session_id,
            daemon_lifecycle=lifecycle_server.descriptor,
            operation_host=operation_host.descriptor,
        )
        boundary("sidecar-start")
        sidecar = await sidecar_launcher(descriptor, resources)
        boundary("probe")
        result = await probe(sidecar)
        if not isinstance(result, NativeRlmProbeResult):
            raise PrimeRlmExperimentError("Native RLM probe result is invalid")
        completed_probe = True
        boundary("probe-return")
        return result
    except PrimeRlmExperimentError as error:
        if str(error).startswith("Native RLM skill "):
            primary_failure = True
            raise
        if await _owned_native_rlm_root_is_inactive(plan, resources):
            return NativeRlmProbeResult(
                terminal="failed",
                child_started=False,
                message_delivered=False,
                child_deleted=False,
                usage=BudgetUsage.zero(),
            )
        primary_failure = True
        raise
    except Exception:
        if await _owned_native_rlm_root_is_inactive(plan, resources):
            return NativeRlmProbeResult(
                terminal="failed",
                child_started=False,
                message_delivered=False,
                child_deleted=False,
                usage=BudgetUsage.zero(),
            )
        primary_failure = True
        safe_code = phase if phase in PrimeRlmExperimentError._SAFE_CODES else None
        raise PrimeRlmExperimentError(
            "Native RLM probe did not complete", safe_code=safe_code
        ) from None
    finally:
        boundary("cleanup")
        sidecar_cleanup_error: PrimeRlmExperimentError | None = None
        daemon_cleanup_error: PrimeRlmExperimentError | None = None
        try:
            await _close_owned_sidecar(sidecar)
        except PrimeRlmExperimentError as error:
            sidecar_cleanup_error = error
        try:
            if sidecar is not None and owned_worker_cleanup is not None:
                await owned_worker_cleanup()
        finally:
            try:
                if lifecycle_server is not None:
                    boundary("cleanup-lifecycle")
                    await lifecycle_server.close()
                if operation_host is not None:
                    boundary("cleanup-operation-host")
                    await operation_host.close()
                boundary("cleanup-daemon")
                await _reap_owned_daemon(
                    daemon, plan, resources,
                    shutdown=owned_daemon_shutdown,
                )
                boundary("cleanup-complete")
            except PrimeRlmExperimentError as error:
                daemon_cleanup_error = error
        if (
            sidecar_cleanup_error is not None
            and not primary_failure
            and not completed_probe
        ):
            boundary("cleanup-sidecar-error")
            raise sidecar_cleanup_error
        if daemon_cleanup_error is not None and not primary_failure:
            boundary("cleanup-daemon-error")
            raise daemon_cleanup_error


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

        timeout_ms = descriptor.get("timeoutMs")
        if type(timeout_ms) is not int or timeout_ms <= 0:
            raise ValueError
        options = PrimeSidecarLaunchOptions(
            node_executable=resources.node_executable,
            sidecar_entry=resources.sidecar_entry,
            private_descriptor=descriptor,
            environ={
                "ASTERION_PRIME_PRIVATE_DIAGNOSTICS": "1",
                "HOME": environ["HOME"],
                "PATH": environ["PATH"],
            },
            # Long-running Prime turns can legitimately hold an IPC request
            # while the native kernel awaits a control-plane admission.  This
            # is bounded by the already-authorized session deadline, not a
            # second, shorter transport deadline.
            request_timeout=timeout_ms / 1_000,
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
            start_new_session=True,
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        raise PrimeRlmExperimentError("Native RLM daemon could not start") from None


async def await_owned_native_rlm_worker_cleanup() -> None:
    """Yield once so Prime observes owner disconnect before bounded reaping."""
    await asyncio.sleep(0)


async def run_owned_native_rlm_sidecar_probe(
    reservation: NativeRlmExperimentReservation,
    selection: NativeRlmModelSelection,
    root: Path,
    resources: NativeRlmRuntimeResources,
    *,
    environ: Mapping[str, str],
    probe: SidecarProbe,
    session_id: str = _SESSION_ID,
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
    async def preflight_lifecycle(socket_path: Path) -> None:
        if sidecar_starter is not None:
            return
        script = textwrap.dedent(
            f'''\
            import {{ createConnection }} from "node:net";
            const socket = createConnection({str(socket_path)!r});
            const timeout = setTimeout(() => process.exit(2), 3000);
            socket.once("error", () => process.exit(2));
            socket.once("connect", () => socket.end("\\n"));
            socket.once("close", () => {{ clearTimeout(timeout); process.exit(0); }});
            '''
        )
        try:
            process = await asyncio.create_subprocess_exec(
                str(resources.node_executable), "--input-type=module", "-e", script,
                cwd=resources.prime_source_root,
                env={"HOME": environ["HOME"], "PATH": environ["PATH"]},
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            if await asyncio.wait_for(process.wait(), timeout=5) != 0:
                raise RuntimeError()
        except (OSError, RuntimeError, TimeoutError, ValueError):
            raise PrimeRlmExperimentError("Native RLM lifecycle preflight failed") from None

    return await execute_native_rlm_sidecar_probe(
        reservation,
        selection,
        root,
        resources,
        environ=environ,
        daemon_launcher=launch_daemon,
        sidecar_launcher=launch_sidecar,
        probe=probe,
        session_id=session_id,
        owned_worker_cleanup=cleanup,
        owned_daemon_shutdown=owned_daemon_shutdown,
        lifecycle_preflight=preflight_lifecycle,
    )


async def run_native_rlm_controlled_probe(
    sidecar: object,
    reservation: NativeRlmExperimentReservation,
    root: Path,
    *,
    goal: NativeRlmPrivateGoal | None = None,
    progress_root: Path | None = None,
    exercise_application: bool = False,
    exercise_checkpoint: bool = False,
    exercise_cancellation: bool = False,
    exercise_budget_probe: bool = False,
    expected_model_selector_digest: str | None = None,
    required_child_count: int = 1,
    detach_while_active: bool = False,
    require_observation_health: bool = False,
    continue_after_attach: bool = False,
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
        or not isinstance(exercise_application, bool)
        or not isinstance(exercise_checkpoint, bool)
        or not isinstance(exercise_cancellation, bool)
        or not isinstance(exercise_budget_probe, bool)
        or not isinstance(required_child_count, int)
        or required_child_count not in {1, 2}
        or not isinstance(detach_while_active, bool)
        or not isinstance(require_observation_health, bool)
        or not isinstance(continue_after_attach, bool)
        or expected_model_selector_digest is not None
        and (
            not isinstance(expected_model_selector_digest, str)
            or len(expected_model_selector_digest) != 64
            or any(
                character not in "0123456789abcdef"
                for character in expected_model_selector_digest
            )
        )
        or progress_root is not None
        and (not isinstance(progress_root, Path) or not progress_root.is_dir())
    ):
        raise PrimeRlmExperimentError("Native RLM controlled probe is invalid")
    checkpoint_created = False
    last_event_type: str | None = None
    last_action_kind: str | None = None
    observed_event_types: list[str] = []
    observed_identities: dict[str, tuple[str, str]] = {}
    observed_message_action_ids: set[str] = set()
    previous_control_sequence = 0
    control_event_sequence_contiguous = True
    terminal_count = 0

    def observe_event(event: ControlEvent) -> None:
        nonlocal checkpoint_created, last_action_kind, last_event_type
        nonlocal previous_control_sequence, control_event_sequence_contiguous, terminal_count
        last_event_type = event.type
        if not isinstance(event.sequence, int) or event.sequence != previous_control_sequence + 1:
            control_event_sequence_contiguous = False
        else:
            previous_control_sequence = event.sequence
        if event.type in {"session.completed", "session.failed", "session.cancelled", "session.budget_limited"}:
            terminal_count += 1
        _record_native_rlm_control_fact(event, observed_event_types, observed_identities)
        if (
            event.type == "checkpoint.created"
            and event.payload.get("checkpoint_id") == "native-rlm-checkpoint"
        ):
            checkpoint_created = True
        action_kind = _native_rlm_safe_action_kind(event)
        if action_kind is not None:
            last_action_kind = action_kind
        if event.type == "action.proposed" and event.payload.get("kind") == "child.message":
            action_id = event.payload.get("action_id")
            if isinstance(action_id, str) and action_id:
                observed_message_action_ids.add(action_id)

    private_goal = NativeRlmPrivateGoal(
        _PERSISTENT_PROBE_GOAL, _PROBE_START
    ) if goal is None else goal
    host = build_native_rlm_control_host(
        sidecar,
        reservation,
        root,
        goal=private_goal,
        event_observer=observe_event,
    )
    observer = PrimeControlPlaneClient(
        process=sidecar,
        private_content=private_goal,
        private_attachments=private_goal,
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
    cleanup_cancel_attempted = False
    primary_failure = False
    children_started_at_detach = 0
    spawn_task: asyncio.Task[Mapping[str, object]] | None = None
    message_task: asyncio.Task[Mapping[str, object]] | None = None
    application_task: asyncio.Task[Mapping[str, object]] | None = None
    checkpoint_task: asyncio.Task[Mapping[str, object]] | None = None
    budget_task: asyncio.Task[Mapping[str, object]] | None = None
    completion_task: asyncio.Task[Mapping[str, object]] | None = None
    model_evidence_collected = expected_model_selector_digest is None

    def checkpoint() -> None:
        if progress_root is None:
            return
        _write_native_rlm_progress(progress_root, stage, latest)

    async def pump_bounded() -> None:
        try:
            await asyncio.wait_for(
                host.pump(),
                timeout=_native_rlm_pump_timeout_seconds(
                    reservation, exercise_checkpoint,
                    active_detach=(
                        detach_while_active and latest.detach_attached
                    ),
                ),
            )
        except TimeoutError:
            pump_stage = getattr(host, "pump_stage", None)
            safe_code = (
                "pump_timeout-" + pump_stage
                if isinstance(pump_stage, str)
                and "pump_timeout-" + pump_stage
                in PrimeRlmExperimentError._SAFE_CODES
                else "pump_timeout"
            )
            raise PrimeRlmExperimentError(
                "Native RLM controlled probe event pump timed out",
                safe_code=safe_code,
            ) from None

    async def observe_bounded(
        usage: BudgetUsage, *, message_action_ids: Sequence[str]
    ) -> NativeRlmProbeResult:
        try:
            return await asyncio.wait_for(
                observe_native_rlm_gateway_probe(
                    observer, usage=usage, message_action_ids=message_action_ids
                ),
                timeout=_PUMP_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            raise PrimeRlmExperimentError(
                "Native RLM controlled probe event observation timed out",
                safe_code="observation_timeout",
            ) from None

    try:
        checkpoint()
        await host.dispatch(native_rlm_session_create_command(reservation))
        session_created = True
        stage = "created"
        checkpoint()
        stage = "running"
        checkpoint()
        await host.dispatch(native_rlm_start_command(reservation))
        stage = "start"
        checkpoint()
        if exercise_budget_probe:
            stage = "budget"
            budget = reservation.authority.budget_limit
            budget_task = asyncio.create_task(
                _send_native_rlm_skill_effect(
                    root,
                    operation="application.invoke",
                    payload={
                        "idempotency_key": "native-rlm-budget",
                        "target": _APPLICATION_TARGET,
                        "input_text": "bounded-budget",
                        "expected_artifacts": [],
                        "budget": {
                            "controller_tokens": budget.controller_tokens + 1,
                            "application_tokens": 0,
                            "child_tokens": 0,
                            "aggregate_tokens": budget.controller_tokens + 1,
                            "cost_micros": 0,
                            "deadline_ms": _native_rlm_system_action_deadline(reservation),
                        },
                    },
                )
            )
            budget_deadline = time.monotonic() + _PUMP_TIMEOUT_SECONDS
            while not budget_task.done() and time.monotonic() < budget_deadline:
                await pump_bounded()
                await asyncio.sleep(0.025)
            if not budget_task.done():
                raise PrimeRlmExperimentError(
                    "Native RLM budget probe did not complete"
                )
            _require_native_rlm_skill_budget_rejection(await budget_task)
            latest = replace(latest, budget_limited=True)
        if exercise_application:
            stage = "application"
            application_task = asyncio.create_task(
            _send_native_rlm_skill_effect(
                root,
                operation="application.invoke",
                payload={
                    "idempotency_key": "native-rlm-application",
                    "target": _APPLICATION_TARGET,
                    "input_text": "bounded-application",
                    "expected_artifacts": [],
                    "budget": {
                        "controller_tokens": 0,
                        "application_tokens": 1,
                        "child_tokens": 0,
                        "aggregate_tokens": 1,
                        "cost_micros": 0,
                        "deadline_ms": _native_rlm_system_action_deadline(reservation),
                    },
                },
            )
            )
            application_deadline = time.monotonic() + _PUMP_TIMEOUT_SECONDS
            while (
                not application_task.done()
                and time.monotonic() < application_deadline
            ):
                await pump_bounded()
                await asyncio.sleep(0.025)
            if not application_task.done():
                raise PrimeRlmExperimentError(
                    "Native RLM controlled probe application did not complete"
                )
            _require_native_rlm_skill_success(
                await application_task, operation="application"
            )
            latest = replace(latest, application_receipted=True)
        stage = "running"
        checkpoint()
        # The root model turn is already bounded by the admitted session
        # deadline.  Do not impose a second, shorter child-initiation cutoff:
        # a valid Prime turn may spend its first several minutes preparing the
        # direct README RLM call before proposing the child action.
        initiation_deadline = deadline
        while time.monotonic() < deadline:
            await asyncio.sleep(0)
            await pump_bounded()
            snapshot = host.snapshot()
            terminal = snapshot.state.session_status
            if snapshot.state.terminal_event_id is not None:
                if terminal not in {"cancelled", "completed", "failed", "budget_limited"}:
                    raise PrimeRlmExperimentError("Native RLM terminal state is invalid")
                if terminal != "completed":
                    session_terminal = True
                    latest = replace(latest, terminal=terminal, usage=snapshot.authority_usage)
                    checkpoint()
                    return latest
            observed = await observe_bounded(
                snapshot.authority_usage,
                message_action_ids=tuple(sorted(observed_message_action_ids)),
            )
            latest = replace(
                observed,
                application_receipted=latest.application_receipted,
                detach_attached=latest.detach_attached,
                checkpoint_recovered=latest.checkpoint_recovered,
                cancelled=latest.cancelled,
                budget_limited=latest.budget_limited,
            )
            if (
                detach_while_active
                and not latest.detach_attached
                and latest.children_started > latest.children_completed
                and snapshot.state.terminal_event_id is None
            ):
                stage = "detach"
                await host.dispatch(native_rlm_session_detach_command(reservation))
                stage = "attach"
                await host.dispatch(native_rlm_session_attach_command(reservation))
                if continue_after_attach:
                    stage = "continue"
                    await host.dispatch(native_rlm_continue_command(reservation))
                stage = "detach-attach"
                children_started_at_detach = latest.children_started
                latest = replace(latest, detach_attached=True)
                checkpoint()
            if (
                latest.detach_attached
                and latest.children_started > children_started_at_detach
            ):
                latest = replace(latest, work_continued_after_attach=True)
            checkpoint()
            if not latest.child_started and time.monotonic() >= initiation_deadline:
                return latest
            core_lifecycle_complete = (
                latest.child_started
                and latest.child_deleted
                if required_child_count == 1
                else latest.children_started >= required_child_count
                and latest.children_completed >= required_child_count
                and latest.children_deleted >= required_child_count
            )
            if _native_rlm_model_evidence_due(
                core_lifecycle_complete=core_lifecycle_complete,
                detach_attached=latest.detach_attached,
                work_continued_after_attach=latest.work_continued_after_attach,
                already_collected=model_evidence_collected,
            ):
                stage = "model-evidence"
                child_identity = observed_identities.get("child.spawn")
                if child_identity is None:
                    raise PrimeRlmExperimentError(
                        "Native RLM model evidence did not complete"
                    )
                binding = await observer.rlm_binding(child_identity[1])
                depth_resolution = await _probe_native_rlm_depth_limit(
                    root,
                    reservation,
                    expected_model_selector_digest,
                )
                model_assertions = derive_native_rlm_model_assertions(
                    binding=binding,
                    expected_model_selector_digest=expected_model_selector_digest,
                    usage=latest.usage,
                    depth_probe_resolution=depth_resolution,
                )
                latest = replace(latest, **model_assertions)
                model_evidence_collected = True
            if (
                detach_while_active
                and core_lifecycle_complete
                and latest.detach_attached
                and latest.work_continued_after_attach
                and model_evidence_collected
                and completion_task is None
            ):
                stage = "goal-complete"
                completion_task = asyncio.create_task(
                    _send_native_rlm_skill_effect(
                        root,
                        operation="goal.complete",
                        payload={
                            "idempotency_key": "native-rlm-core-complete",
                            "goal_id": _GOAL_REFERENCE,
                            "summary": "native-rlm-core-complete",
                            "budget": {
                                "controller_tokens": 1,
                                "application_tokens": 0,
                                "child_tokens": 0,
                                "aggregate_tokens": 1,
                                "cost_micros": 0,
                                "deadline_ms": _native_rlm_system_action_deadline(reservation),
                            },
                        },
                    )
                )
            if completion_task is not None and completion_task.done():
                _require_native_rlm_skill_success(
                    await completion_task, operation="goal"
                )
            root_terminal_complete = _native_rlm_snapshot_terminal(snapshot) == "completed"
            if root_terminal_complete:
                latest = replace(
                    latest,
                    terminal="completed",
                    usage=snapshot.authority_usage,
                )
            if latest.terminal == "completed" and core_lifecycle_complete and (
                not detach_while_active or root_terminal_complete
            ):
                if _native_rlm_requires_terminal_reconnect(latest.detach_attached):
                    stage = "detach-attach"
                    await host.dispatch(native_rlm_session_detach_command(reservation))
                    await host.dispatch(native_rlm_session_attach_command(reservation))
                    latest = replace(latest, detach_attached=True)
                    checkpoint()
                if exercise_checkpoint:
                    # Prime can only restart from an idle root.  The closed RLM
                    # lifecycle is the quiescence barrier; checkpointing during
                    # root initialization is rejected by its daemon.
                    stage = "checkpoint"
                    checkpoint_task = asyncio.create_task(
                        _send_native_rlm_skill_effect(
                            root,
                            operation="checkpoint.request",
                            payload={
                                "idempotency_key": "native-rlm-checkpoint",
                                "checkpoint_id": "native-rlm-checkpoint",
                                "budget": {
                                    "controller_tokens": 1,
                                    "application_tokens": 0,
                                    "child_tokens": 0,
                                    "aggregate_tokens": 1,
                                    "cost_micros": 0,
                                    "deadline_ms": _native_rlm_system_action_deadline(reservation),
                                },
                            },
                        )
                    )
                    checkpoint_deadline = time.monotonic() + _native_rlm_system_action_deadline(reservation) / 1_000
                    while not checkpoint_task.done() and time.monotonic() < checkpoint_deadline:
                        await pump_bounded()
                        await asyncio.sleep(0.025)
                    if not checkpoint_task.done():
                        raise PrimeRlmExperimentError(
                            "Native RLM controlled probe checkpoint did not complete"
                        )
                    _require_native_rlm_skill_success(
                        await checkpoint_task, operation="checkpoint"
                    )
                    checkpoint_materialization_deadline = (
                        time.monotonic()
                        + _native_rlm_system_action_deadline(reservation) / 1_000
                    )
                    while (
                        not checkpoint_created
                        and time.monotonic() < checkpoint_materialization_deadline
                    ):
                        await pump_bounded()
                        await asyncio.sleep(0.025)
                    if not checkpoint_created:
                        raise PrimeRlmExperimentError(
                            "Native RLM controlled probe checkpoint materialization did not complete"
                        )
                    latest = replace(latest, checkpoint_recovered=True)
                if exercise_cancellation:
                    stage = "cancellation"
                    await host.dispatch(native_rlm_session_cancel_command(reservation))
                    cancellation_deadline = min(
                        deadline, time.monotonic() + _PUMP_TIMEOUT_SECONDS
                    )
                    while time.monotonic() < cancellation_deadline:
                        await pump_bounded()
                        state = host.snapshot().state
                        if (
                            state.terminal_event_id is not None
                            and state.session_status == "cancelled"
                        ):
                            latest = replace(latest, cancelled=True)
                            session_terminal = True
                            break
                        await asyncio.sleep(0.025)
                    if not latest.cancelled:
                        raise PrimeRlmExperimentError(
                            "Native RLM controlled probe cancellation did not complete"
                        )
                latest = replace(
                    latest,
                    observed_event_types=tuple(observed_event_types),
                    causal_identities=MappingProxyType(dict(observed_identities)),
                    control_event_sequence_contiguous=control_event_sequence_contiguous,
                    terminal_count=terminal_count,
                )
                if require_observation_health:
                    health_reader = getattr(observer, "client_observation_health", None)
                    if not callable(health_reader):
                        raise PrimeRlmExperimentError("Native RLM observation health is unavailable")
                    health = await health_reader()
                    health_status = getattr(health, "status", None)
                    if health_status not in {"healthy", "degraded", "resync-required"}:
                        raise PrimeRlmExperimentError("Native RLM observation health is invalid")
                    latest = replace(
                        latest,
                        observation_health=health_status,
                        observation_gap_count=0 if health_status == "healthy" else 1,
                    )
                session_terminal = True
                return latest
            if snapshot.state.terminal_event_id is not None:
                session_terminal = True
                return replace(latest, terminal=terminal)
            await asyncio.sleep(0.025)
        return latest
    except PrimeRlmExperimentError:
        if not _native_rlm_failure_may_reconcile_terminal(stage):
            primary_failure = True
            raise
        terminal = _terminal_native_rlm_probe_result(host, latest)
        if terminal is None:
            primary_failure = True
            raise
        session_terminal = True
        latest = terminal
        checkpoint()
        return latest
    except Exception as error:
        if not _native_rlm_failure_may_reconcile_terminal(stage):
            primary_failure = True
            category = _native_rlm_control_failure_category(error)
            safe_code = {
                "detach": "detach-control",
                "attach": "attach-control",
            }.get(stage, category)
            raise PrimeRlmExperimentError(
                f"Native RLM controlled probe {stage} {category} did not complete",
                safe_code=(
                    safe_code
                    if safe_code in PrimeRlmExperimentError._SAFE_CODES
                    else None
                ),
            ) from None
        terminal = _terminal_native_rlm_probe_result(host, latest)
        if terminal is not None:
            session_terminal = True
            latest = terminal
            checkpoint()
            return latest
        category = _native_rlm_control_failure_category(error)
        if category == "event-transition" and last_event_type is not None:
            category = "event-transition-" + last_event_type.replace(".", "-")
            if last_event_type == "session.completed":
                category += "-" + _native_rlm_terminal_transition_category(host)
            elif last_event_type == "action.proposed":
                category += "-" + _native_rlm_action_transition_session_category(host)
        if category == "action-admission" and last_action_kind is not None:
            category = "action-admission-" + last_action_kind
        primary_failure = True
        raise PrimeRlmExperimentError(
            f"Native RLM controlled probe {stage} {category} did not complete",
            safe_code=category if category in PrimeRlmExperimentError._SAFE_CODES else None,
        ) from None
    finally:
        try:
            pending = tuple(
                task
                for task in (
                    spawn_task,
                    message_task,
                    application_task,
                    checkpoint_task,
                    budget_task,
                )
                if task is not None
            )
            for task in pending:
                if not task.done():
                    task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            if session_created and not session_terminal:
                try:
                    cleanup_cancel_attempted = True
                    await host.dispatch(native_rlm_session_cancel_command(reservation))
                    await asyncio.wait_for(
                        host.pump(until_terminal=True),
                        timeout=_PUMP_TIMEOUT_SECONDS,
                    )
                    session_terminal = host.snapshot().state.terminal_event_id is not None
                except Exception:
                    # The owned sidecar and daemon are reaped below.  A terminal
                    # native session can reject this best-effort cancel without
                    # invalidating the earlier probe result or hiding its cause.
                    pass
        finally:
            try:
                await host.close()
            except Exception:
                # Cancellation is proved by the isolated maintenance root.  The
                # observation root's final cancellation is resource cleanup only;
                # its owned daemon is reaped even if a post-terminal replay cannot
                # be observed after native shutdown.
                if (
                    not session_terminal
                    and not primary_failure
                    and not cleanup_cancel_attempted
                ):
                    raise


async def run_native_rlm_maintenance_probe(
    sidecar: object,
    reservation: NativeRlmExperimentReservation,
    root: Path,
    *,
    session_id: str = "native-rlm-maintenance",
) -> NativeRlmProbeResult:
    """Prove pause → checkpoint recovery → cancellation in an isolated root.

    This deliberately does not start a model turn or an RLM child. Prime keeps
    an RLM root resident while its model-owned turn is active, while its
    checkpoint manager accepts only an idle root. The maintenance root therefore
    proves native checkpoint/recovery/cancellation without falsely claiming an
    active RLM turn is checkpointable; the observation root exercises the actual
    RLM child/message/application/budget path separately.
    """
    if (
        not isinstance(reservation, NativeRlmExperimentReservation)
        or not isinstance(root, Path)
        or not root.is_dir()
        or not isinstance(session_id, str)
        or not session_id
    ):
        raise PrimeRlmExperimentError("Native RLM maintenance probe is invalid")
    checkpoint_created = False
    cancelled_event = False
    event_types: list[str] = []
    identities: dict[str, tuple[str, str]] = {}

    def observe_event(event: ControlEvent) -> None:
        nonlocal checkpoint_created, cancelled_event
        _record_native_rlm_control_fact(event, event_types, identities)
        checkpoint_created = checkpoint_created or (
            event.type == "checkpoint.created"
            and event.payload.get("checkpoint_id") == "native-rlm-maintenance-checkpoint"
        )
        cancelled_event = cancelled_event or event.type == "session.cancelled"

    host = build_native_rlm_control_host(
        sidecar,
        reservation,
        root,
        goal=NativeRlmPrivateGoal("Remain available until the operator pauses this session."),
        session_id=session_id,
        event_observer=observe_event,
    )
    deadline = time.monotonic() + reservation.limits.deadline_ms / 1_000
    session_created = False
    stage = "create"
    try:
        await host.dispatch(native_rlm_session_create_command(reservation, session_id=session_id))
        session_created = True
        stage = "pause"
        await host.dispatch(native_rlm_session_pause_command(reservation, session_id=session_id))
        while time.monotonic() < deadline:
            await asyncio.wait_for(host.pump(), timeout=_PUMP_TIMEOUT_SECONDS)
            if host.snapshot().state.session_status == "paused":
                break
            await asyncio.sleep(0.025)
        else:
            raise PrimeRlmExperimentError("Native RLM maintenance pause did not complete")
        stage = "checkpoint"
        checkpoint_task = asyncio.create_task(
            _send_native_rlm_skill_effect(
                root,
                operation="checkpoint.request",
                payload={
                    "idempotency_key": "native-rlm-maintenance-checkpoint",
                    "checkpoint_id": "native-rlm-maintenance-checkpoint",
                    "budget": {
                        "controller_tokens": 1,
                        "application_tokens": 0,
                        "child_tokens": 0,
                        "aggregate_tokens": 1,
                        "cost_micros": 0,
                        "deadline_ms": _native_rlm_system_action_deadline(reservation),
                    },
                },
            )
        )
        checkpoint_deadline = min(
            deadline,
            time.monotonic() + _native_rlm_system_action_deadline(reservation) / 1_000,
        )
        while time.monotonic() < checkpoint_deadline and (
            not checkpoint_task.done() or not checkpoint_created
        ):
            await asyncio.wait_for(
                host.pump(), timeout=_native_rlm_pump_timeout_seconds(reservation, True)
            )
            if checkpoint_task.done():
                _require_native_rlm_skill_success(
                    await checkpoint_task, operation="checkpoint"
                )
            await asyncio.sleep(0.025)
        if not checkpoint_task.done() or not checkpoint_created:
            if checkpoint_task.done():
                _require_native_rlm_skill_success(
                    await checkpoint_task, operation="checkpoint"
                )
            raise PrimeRlmExperimentError(
                "Native RLM maintenance checkpoint did not complete"
            )
        _require_native_rlm_skill_success(await checkpoint_task, operation="checkpoint")
        stage = "cancellation"
        await host.dispatch(native_rlm_session_cancel_command(reservation, session_id=session_id))
        await asyncio.wait_for(host.pump(until_terminal=True), timeout=_PUMP_TIMEOUT_SECONDS)
        state = host.snapshot().state
        if cancelled_event and state.terminal_event_id is not None and state.session_status == "cancelled":
            return NativeRlmProbeResult(
                terminal="cancelled",
                child_started=False,
                message_delivered=False,
                child_deleted=False,
                usage=host.snapshot().authority_usage,
                checkpoint_recovered=True,
                cancelled=True,
                observed_event_types=tuple(event_types),
                causal_identities=MappingProxyType(dict(identities)),
            )
        raise PrimeRlmExperimentError("Native RLM maintenance cancellation did not complete")
    except ControlHostError as error:
        raise PrimeRlmExperimentError(
            f"Native RLM maintenance {stage} {_native_rlm_control_failure_category(error)} did not complete"
        ) from None
    finally:
        if session_created:
            try:
                state = host.snapshot().state
                if state.terminal_event_id is None:
                    await host.dispatch(native_rlm_session_cancel_command(reservation, session_id=session_id))
            except Exception:
                pass
        try:
            await host.close()
        except Exception:
            # The terminal cancellation and checkpoint facts are durable before
            # close. Prime may race its own supervisor while reaping an already
            # terminated worker; outer owned-process cleanup remains required.
            if not cancelled_event:
                raise


def _native_rlm_control_failure_category(error: Exception) -> str:
    """Project fixed host failures without retaining private transport detail."""
    if isinstance(error, ControlHostTransportError):
        safe_code = getattr(error, "safe_code", None)
        if safe_code in {"authority-sync", "event-read", "event-read-response-timeout", "event-read-sidecar-error", "event-read-response-eof", "event-read-response-invalid", "event-read-event-protocol", "event-read-event-runtime"}:
            return "event-transport-" + safe_code
        return "event-transport"
    if not isinstance(error, ControlHostError):
        return "control"
    categories = {
        "control provider event transition failed": "event-transition",
        "control action admission failed": "action-admission",
        "provider-owned action lifecycle is invalid": "provider-lifecycle",
        "provider-owned action lifecycle gateway is invalid": "provider-lifecycle-gateway",
        "provider-owned action lifecycle binding is invalid": "provider-lifecycle-binding",
        "provider-owned action lifecycle transition is invalid": "provider-lifecycle-transition",
        "provider-owned action lifecycle terminal is invalid": "provider-lifecycle-terminal",
        "provider-owned action lifecycle reconcile is invalid": "provider-lifecycle-reconcile",
        "provider-owned action lifecycle settlement is invalid": "provider-lifecycle-settlement",
        "control provider event journal failed": "event-journal",
        "control provider budget report failed": "budget-report",
        "control provider event is invalid": "event-invalid",
    }
    return categories.get(str(error), "control")


def _native_rlm_action_transition_session_category(host: object) -> str:
    """Return a fixed, public-safe Host state category for a rejected action."""

    try:
        snapshot = getattr(host, "snapshot")()
        status = getattr(getattr(snapshot, "state"), "session_status")
    except Exception:
        return "other"
    return {
        None: "none",
        "created": "created",
        "paused": "paused",
        "recovery_required": "recovery-required",
    }.get(status, "other")


def _native_rlm_failure_may_reconcile_terminal(stage: str) -> bool:
    """Only stream-phase failures may use an already recorded terminal state.

    Once the RLM lifecycle itself has completed, detach, checkpoint, and
    cancellation are independently required proof obligations.  Treating an
    earlier ``session.completed`` as their success hid the actual failed step.
    """

    return stage not in {"detach-attach", "checkpoint", "cancellation"}


def _native_rlm_admission_failure_category(reason: object) -> str:
    """Expose only stable authority reason codes in public probe errors."""

    categories = frozenset(
        {
            "authority-cancelled",
            "authority-expired",
            "authority-revision-mismatch",
            "budget-exceeded",
            "child-concurrency-exceeded",
            "deadline-not-authorized",
            "host-service-not-authorized",
            "operation-not-authorized",
            "recursion-depth-exceeded",
            "target-not-authorized",
        }
    )
    return reason if isinstance(reason, str) and reason in categories else "unknown"


def _native_rlm_terminal_transition_category(host: object) -> str:
    """Classify a terminal invariant without exposing event or action identity."""

    try:
        state = host.snapshot().state
        if state.goal_status != "completed":
            return "goal-not-completed"
        terminal_actions = {
            "rejected", "succeeded", "failed", "cancelled", "uncertain"
        }
        if any(action.status not in terminal_actions for action in state.actions.values()):
            return "active-actions"
        return "invalid"
    except (AttributeError, TypeError):
        return "unknown"


def _native_rlm_safe_action_kind(event: object) -> str | None:
    """Return only a fixed, public action class for private probe diagnostics."""

    if not isinstance(event, ControlEvent) or event.type != "action.proposed":
        return None
    kind = event.payload.get("kind")
    if kind not in {"child.spawn", "child.message", "child.cancel"}:
        return None
    return kind.replace(".", "-")


def _record_native_rlm_control_fact(
    event: ControlEvent,
    event_types: list[str],
    identities: dict[str, tuple[str, str]],
) -> None:
    """Retain only fixed event classes and identity pairs for bounded evidence."""
    if not isinstance(event, ControlEvent):
        raise PrimeRlmExperimentError("Native RLM control fact is invalid")
    event_types.append(event.type)
    if event.type != "action.proposed":
        if event.type == "session.cancelled":
            identities["session.cancel"] = ("native-rlm-cleanup", event.event_id)
        return
    kind = event.payload.get("kind")
    action_id = event.payload.get("action_id")
    idempotency_key = event.payload.get("idempotency_key")
    operation = {
        "child.spawn": "child.spawn",
        "checkpoint.create": "checkpoint.create",
    }.get(kind)
    if kind == "application.invoke":
        operation = (
            "budget.probe"
            if idempotency_key == "native-rlm-budget"
            else "application.invoke"
        )
    if operation is not None and isinstance(action_id, str):
        identities[operation] = (event.event_id, action_id)

def _native_rlm_public_progress_stage(stage: object) -> str:
    """Project only fixed lifecycle labels into private diagnostic evidence."""

    return (
        stage
        if stage
        in {
            "create",
            "created",
            "start",
            "budget",
            "application",
            "running",
            "model-evidence",
            "detach-attach",
            "checkpoint",
            "cancellation",
            "skill-spawn",
            "skill-message",
        }
        else "unknown"
    )


def _write_native_rlm_progress(
    root: Path, stage: str, result: NativeRlmProbeResult
) -> None:
    payload = {
        "format": "asterion.prime-native-rlm-progress/v1",
        "stage": _native_rlm_public_progress_stage(stage),
        "child_started": result.child_started,
        "message_delivered": result.message_delivered,
        "child_deleted": result.child_deleted,
        "usage": vars(result.usage),
    }
    descriptor, temporary = tempfile.mkstemp(prefix=".native-rlm-progress-", dir=root)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        os.replace(temporary, root / "native-rlm-progress.json")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _native_rlm_snapshot_terminal(snapshot: object) -> str | None:
    """Return the completed terminal recorded by the authoritative host snapshot."""

    try:
        state = snapshot.state
        if state.terminal_event_id is not None and state.session_status == "completed":
            return "completed"
    except AttributeError:
        return None
    return None


def _native_rlm_model_evidence_due(
    *,
    core_lifecycle_complete: bool,
    detach_attached: bool,
    work_continued_after_attach: bool,
    already_collected: bool,
) -> bool:
    """Collect root-dependent model evidence before controlled completion closes it."""

    return (
        core_lifecycle_complete
        and detach_attached
        and work_continued_after_attach
        and not already_collected
    )


def _native_rlm_requires_terminal_reconnect(detach_attached: bool) -> bool:
    """Avoid a terminal-only reconnect when active work already proved it."""

    return not detach_attached


def _terminal_native_rlm_probe_result(
    host: object, latest: NativeRlmProbeResult
) -> NativeRlmProbeResult | None:
    """Project a host-recorded terminal state after a stream-side failure."""
    snapshot = getattr(host, "snapshot", None)
    if not callable(snapshot):
        return None
    try:
        state = snapshot().state
        terminal = state.session_status
        if state.terminal_event_id is None or terminal not in {
            "cancelled",
            "completed",
            "failed",
            "budget_limited",
        }:
            return None
    except (AttributeError, TypeError, ValueError):
        return None
    return replace(latest, terminal=terminal)


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


async def _owned_native_rlm_root_is_inactive(
    plan: NativeRlmDaemonPlan, resources: NativeRlmRuntimeResources
) -> bool:
    """Read one owned root's public daemon state without attaching or replaying it."""
    client_entry = resources.sidecar_entry.parent / "index.js"
    script = textwrap.dedent(
        f'''\
        import {{ PrimeDaemonClient }} from {client_entry.as_uri()!r};
        // Client-owned Prime workers are intentionally invisible to every other
        // client. Reuse the root sidecar's stable identity for this read-only
        // recovery query; it grants no new authority and does not attach.
        const client = new PrimeDaemonClient({{clientId: "asterion-{_SESSION_ID}", connectTimeoutMs: 3000, requestTimeoutMs: 3000}});
        await client.connect({str(plan.socket_path)!r});
        const listed = await client.request({{type: "list", includeClientOwned: true}}, "asterion-owned-state-list", 3000);
        const sessions = listed.success && listed.command === "list" && Array.isArray(listed.data?.sessions) ? listed.data.sessions : [];
        const matches = sessions.filter((value) => value?.sessionName === "native-rlm-root");
        if (matches.length !== 1) process.exit(2);
        const activeSessionId = matches[0].activeSessionId ?? matches[0].id;
        if (typeof activeSessionId !== "string") process.exit(2);
        const state = await client.request({{type: "get_state", activeSessionId}}, "asterion-owned-state-read", 3000);
        if (!state.success || state.command !== "get_state" || state.data?.activity !== "idle" || state.data?.isSessionActive !== false || state.data?.isStreaming !== false || state.data?.hasRunningRlmChildren !== false) process.exit(2);
        client.close();
        '''
    )
    try:
        process = await asyncio.create_subprocess_exec(
            str(resources.node_executable), "--input-type=module", "-e", script,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return await asyncio.wait_for(process.wait(), timeout=4) == 0
    except (TimeoutError, OSError, ValueError):
        return False


async def _reap_owned_daemon(
    daemon: object,
    plan: NativeRlmDaemonPlan,
    resources: NativeRlmRuntimeResources,
    *,
    shutdown: OwnedDaemonShutdown | None = None,
) -> None:
    """Use Prime's daemon protocol; SIGTERM leaves detached workers behind."""
    wait = getattr(daemon, "wait", None)
    if not callable(wait):
        raise PrimeRlmExperimentError("Native RLM daemon cleanup failed")
    try:
        if shutdown is not None:
            await shutdown(plan, resources)
            if getattr(daemon, "returncode", None) is None:
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
        if getattr(daemon, "returncode", None) is None:
            await asyncio.wait_for(wait(), timeout=5)
    except (TimeoutError, OSError, RuntimeError, TypeError, ValueError):
        # The protocol shutdown can race Prime's supervisor after a terminal
        # worker has already exited. This daemon is owned by this probe, so
        # reclaim its exact process rather than leaving an orphan that blocks
        # the next independent proof root.
        try:
            if getattr(daemon, "returncode", None) is None:
                terminate = getattr(daemon, "terminate", None)
                if callable(terminate):
                    terminate()
                await asyncio.wait_for(wait(), timeout=5)
        except (TimeoutError, OSError, TypeError, ValueError):
            try:
                if getattr(daemon, "returncode", None) is None:
                    kill = getattr(daemon, "kill", None)
                    if callable(kill):
                        kill()
                    await asyncio.wait_for(wait(), timeout=5)
            except (TimeoutError, OSError, TypeError, ValueError):
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
    max_concurrent_children: int = 1,
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
            or isinstance(max_concurrent_children, bool)
            or not isinstance(max_concurrent_children, int)
            or max_concurrent_children not in {1, 2}
        ):
            raise ValueError
        model = environ.get(_MODEL_KEY)
        if not isinstance(model, str) or not model:
            raise ValueError
        current = int(time.time() * 1000) if now_ms is None else now_ms
        authority = (
            _default_native_rlm_authority(
                current, action_deadline, max_concurrent_children
            )
            if authority_path is None
            else load_bounded_rlm_authority(
                authority_path, max_cost_micros=cost_limit, now_ms=current
            )
        )
        if authority.max_action_deadline_ms > action_deadline:
            raise ValueError
        digest = sha256(
            b"asterion.prime.native-rlm\0"
            + model.encode()
            + b"\0"
            + str(max_concurrent_children).encode()
        ).hexdigest()
        return NativeRlmExperimentReservation(
            authority=authority,
            limits=NativeRlmExperimentLimits(cost_limit, action_deadline),
            configuration_digest=digest,
        )
    except (PrimeVerificationError, TypeError, ValueError):
        raise PrimeRlmExperimentError("Native RLM experiment authorization is invalid") from None


def _default_native_rlm_authority(
    now_ms: int, deadline_ms: int, max_concurrent_children: int = 1
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
        max_concurrent_children=max_concurrent_children,
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
    checkpoint_recovered: bool = False,
    detach_attached: bool = False,
    cancelled: bool = False,
    budget_limited: bool = False,
) -> Mapping[str, object]:
    """Atomically write a private, public-safe observation for one reservation."""
    if (
        not isinstance(root, Path)
        or not root.is_dir()
        or not isinstance(reservation, NativeRlmExperimentReservation)
        or not reservation.consumed
        or terminal not in {"completed", "failed", "cancelled", "uncertain"}
        or not all(
            isinstance(value, bool)
            for value in (
                child_started,
                message_delivered,
                child_deleted,
                checkpoint_recovered,
                detach_attached,
                cancelled,
                budget_limited,
            )
        )
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
        "checkpoint_recovered": checkpoint_recovered,
        "detach_attached": detach_attached,
        "cancelled": cancelled,
        "budget_limited": budget_limited,
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
            "checkpoint_recovered": checkpoint_recovered,
            "detach_attached": detach_attached,
            "cancelled": cancelled,
            "budget_limited": budget_limited,
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
