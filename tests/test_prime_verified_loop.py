from __future__ import annotations

import tempfile
import unittest
import asyncio
import hashlib
import json
import os
import signal
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import IO, cast

from asterion.applications.provider import (
    APPLICATION_PROVIDER_PROTOCOL,
    InstalledApplicationProvider,
)
from asterion.capabilities.execution import (
    CapabilityExecutionResult,
    CapabilityInvocation,
)
from asterion.control.authority import (
    AuthorityEnvelope,
    AuthorityLedger,
    BudgetLimit,
    BudgetUsage,
)
from asterion.control.application_executor import ApplicationActionExecutor
from asterion.control.children import ChildSessionService
from asterion.control.execution import ActionExecutionFailure, ActionExecutionReceipt
from asterion.control.factory import ControlPlaneFactoryRegistry
from asterion.control.host import ControlCommand, ControlEvent, ControlPlaneClient
from asterion.control.journal import FileCanonicalJournal, JournalCursor
from asterion.control.manager import ControlHost, ControlHostTransportError
from asterion.control.parity import validate_parity_ledger
from asterion.control.parity_testing import ParityScenarioRegistry
from asterion.control.providers.prime.client import PrimeControlPlaneClient
from asterion.control.providers.prime.factory import (
    PRIME_NATIVE_RLM_MAX_DEPTH,
    build_prime_control_plane_client,
    derive_prime_child_control_options,
    prime_control_plane_binding,
)
from asterion.control.providers.prime.process import (
    PrimeSidecarLaunchOptions,
    PrimeSidecarProcess,
)
from asterion.control.providers.prime.system_actions import PrimeSystemActionService
from asterion.control.system import AgentSystemPlan, resolve_agent_system
from asterion.control.providers.prime.parity_testing import (
    PROVEN_PHASE1_PARITY_SCENARIO_IDS,
    register_proven_phase1_prime_subset,
)
from asterion.pathlight import MemoryPathlightRecorder
from asterion.runtime.host import CancellationSignal
from asterion.runtime.factory import RuntimeFactoryBinding, RuntimeFactoryRegistry
from tests.test_control_application_executor import (
    RecordingResultStore,
    RecordingRuntime,
    UsageImplementation,
    _assembly,
)
from tests.test_control_children import _child_envelope
from tests.test_control_authority import _envelope
from tests.test_control_pathlight import _opaque_id
from tests.test_prime_control_factory import make_context, prepare_paths
from tests.test_control_system import _application, _manifest, _provider

EXPECTED_IDS = (
    "prime-loop-application",
    "prime-loop-child",
    "prime-loop-detach-attach",
    "prime-loop-checkpoint",
    "prime-loop-gateway-crash",
    "prime-loop-supervisor-crash",
    "prime-loop-worker-crash",
    "prime-loop-cancel",
    "prime-loop-budget",
    "prime-loop-redaction",
)
SENTINELS = (
    "SENTINEL_PROMPT",
    "SENTINEL_TOKEN",
    "SENTINEL_PATH",
    "SENTINEL_OUTPUT",
)
SCENARIO_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "prime_gateway"
    / "v1"
    / "verified-loop-scenarios.json"
)


@dataclass(frozen=True)
class PrimeLoopScenarioResult:
    scenario_id: str
    status: str
    outcome: str
    evidence_id: str
    provider_operations: int
    application_operations: int
    process_counts: Mapping[str, int]
    pathlight_nodes: tuple[str, ...]
    pathlight_control_events: tuple[str, ...]
    pathlight_gaps: tuple[str, ...]
    serialized_observations: str


def _load_scenarios() -> tuple[Mapping[str, object], ...]:
    value = json.loads(SCENARIO_FIXTURE.read_text())
    if not isinstance(value, list):
        raise AssertionError("scenario ledger must be a list")
    return tuple(cast(Mapping[str, object], item) for item in value)


class _PrivateResolver:
    def resolve_text(self, reference: str, *, max_bytes: int) -> str:
        del max_bytes
        if reference == "goal-ref-1":
            return "SENTINEL_PROMPT SENTINEL_PATH SENTINEL_OUTPUT"
        raise KeyError("private content is unavailable")


class _ScenarioExecutor:
    def __init__(
        self,
        scenario_id: str,
        children: ChildSessionService | None = None,
    ) -> None:
        self.scenario_id = scenario_id
        self.children = children
        self.calls: list[str] = []

    async def execute(
        self, proposal: ControlEvent, signal: CancellationSignal
    ) -> ActionExecutionReceipt:
        if proposal.payload["kind"] == "child.spawn":
            if self.children is None:
                raise ActionExecutionFailure(
                    "uncertain", "child-service-unavailable", None
                )
            return await self.children.spawn(proposal, signal)
        if self.scenario_id == "prime-loop-worker-crash":
            raise ActionExecutionFailure("uncertain", "worker-crash", None)
        del signal
        self.calls.append(str(proposal.payload["action_id"]))
        return ActionExecutionReceipt(
            action_id=str(proposal.payload["action_id"]),
            receipt_ref=f"receipt-{self.scenario_id}",
            usage=BudgetUsage(0, 1, 0, 1, 0),
            artifact_ids=("report.alpha",),
            media_types=("text/plain",),
        )


class _FaultBoundaryExecutor:
    def __init__(
        self,
        delegate: ApplicationActionExecutor,
        scenario_id: str,
        *,
        sidecar: PrimeSidecarProcess,
        supervisor: asyncio.subprocess.Process,
    ) -> None:
        self._delegate = delegate
        self._scenario_id = scenario_id
        self._sidecar = sidecar
        self._supervisor = supervisor

    async def execute(
        self, proposal: ControlEvent, signal: CancellationSignal
    ) -> ActionExecutionReceipt:
        if self._scenario_id == "prime-loop-gateway-crash":
            await _kill_sidecar(self._sidecar)
            raise ActionExecutionFailure("uncertain", "gateway-crash", None)
        if self._scenario_id == "prime-loop-supervisor-crash":
            await _stop_process(self._supervisor)
            raise ActionExecutionFailure("uncertain", "supervisor-crash", None)
        return await self._delegate.execute(proposal, signal)


class _WorkerCrashImplementation(UsageImplementation):
    def __init__(self, audit: list[str], worker_pids: list[int]) -> None:
        super().__init__(audit, input_tokens=4, output_tokens=3)
        self._worker_pids = worker_pids

    async def execute(
        self, invocation: CapabilityInvocation
    ) -> CapabilityExecutionResult:
        self.audit.append("implementation.execute")
        self.calls.append(invocation)
        worker = await asyncio.create_subprocess_exec(
            shutil.which("node") or "node",
            "-e",
            "process.exit(23)",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._worker_pids.append(worker.pid)
        returncode = await asyncio.wait_for(worker.wait(), timeout=5)
        if returncode == 0:
            raise AssertionError("worker crash fixture exited successfully")
        raise RuntimeError("controlled worker exited")


class _StaticCancellation:
    def __init__(self, cancelled: bool) -> None:
        self._cancelled = cancelled

    @property
    def cancelled(self) -> bool:
        return self._cancelled


async def _readline(
    stream: asyncio.StreamReader | None,
    label: str,
) -> str:
    if stream is None:
        raise AssertionError(f"{label} stream is unavailable")
    line = await asyncio.wait_for(stream.readline(), timeout=5)
    if not line:
        raise AssertionError(f"{label} did not become ready")
    return line.decode("utf-8")


async def _start_fake_daemon(
    root: Path, scenario_id: str
) -> tuple[asyncio.subprocess.Process, Path, Path]:
    package_root = (
        Path(__file__).resolve().parents[1] / "packages/typescript/prime-gateway"
    )
    socket_path = root / "p.sock"
    socket_path.unlink(missing_ok=True)
    observations_path = root / "daemon-observations.json"
    process = await asyncio.create_subprocess_exec(
        shutil.which("node") or "node",
        str(package_root / "test/fixtures/fake-prime-daemon.mjs"),
        "--socket-path",
        str(socket_path),
        "--observations",
        str(observations_path),
        "--scenario-id",
        scenario_id,
        cwd=package_root,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    json.loads(await _readline(process.stdout, "fake daemon"))
    return process, socket_path, observations_path


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except TimeoutError:
        process.kill()
        await asyncio.wait_for(process.wait(), timeout=5)


async def _kill_sidecar(process: PrimeSidecarProcess) -> None:
    pid = process.pid
    if not isinstance(pid, int) or pid < 1:
        raise AssertionError("sidecar PID is unavailable")
    os.kill(pid, signal.SIGKILL)
    for _ in range(100):
        if process.returncode is not None:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("sidecar did not terminate")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_prime_source(root: Path) -> Mapping[str, object]:
    contents = {
        "package-lock.json": json.dumps(
            {
                "name": "prime-agent",
                "version": "0.7.1",
                "lockfileVersion": 3,
                "packages": {
                    "": {"name": "prime-agent", "version": "0.7.1"},
                    "packages/coding-agent": {
                        "name": "@earendil-works/pi-coding-agent",
                        "version": "0.7.1",
                    },
                },
            }
        ),
        "packages/coding-agent/package.json": json.dumps(
            {"name": "@earendil-works/pi-coding-agent", "version": "0.7.1"}
        ),
        "packages/coding-agent/src/modes/daemon/daemon-client.ts": (
            "export const fixtureClient = true;\n"
        ),
        "packages/coding-agent/src/modes/daemon/daemon-protocol.ts": (
            "export const DAEMON_PROTOCOL_VERSION = 7;\n"
        ),
        "prime-agent.sh": "#!/bin/sh\nexit 0\n",
    }
    for relative, text in contents.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    (root / "prime-agent.sh").chmod(0o755)
    for command in (
        ("git", "init", "--quiet"),
        ("git", "config", "user.name", "Asterion Test"),
        ("git", "config", "user.email", "asterion@example.invalid"),
        ("git", "add", "."),
        ("git", "commit", "--quiet", "-m", "fixture"),
    ):
        subprocess.run(
            command,
            cwd=root,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    source_commit = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {
        "format": "asterion.prime-artifact-lock/v1",
        "source_commit": source_commit,
        "package_name": "@earendil-works/pi-coding-agent",
        "package_version": "0.7.1",
        "daemon_protocol": 7,
        "daemon_schema_revision": 14,
        "daemon_schema_id": "protocol-7-schema-14-816309b1cd50",
        "files": {relative: _sha256(text) for relative, text in contents.items()},
    }


def _prime_plan(
    root: Path, provider: InstalledApplicationProvider | None = None
) -> AgentSystemPlan:
    manifest = dict(_manifest())
    manifest["control_plane"] = {
        "control_plane_id": "prime.gateway",
        "version": "0.1.0",
    }
    return resolve_agent_system(
        manifest,
        application_providers=(
            provider if provider is not None else _provider(root / "applications"),
        ),
        control_factories=ControlPlaneFactoryRegistry((prime_control_plane_binding(),)),
        host_capabilities=("clock.monotonic", "secret.service", "storage.private"),
    )


def _create_command() -> ControlCommand:
    return ControlCommand(
        command_id="command-create",
        session_id="session-1",
        authority_revision=1,
        type="session.create",
        payload={
            "system_id": "research.system",
            "system_version": "1.0.0",
            "goal_id": "goal-1",
            "goal_ref": "goal-ref-1",
        },
    )


def _attach_command(command_id: str = "command-attach") -> ControlCommand:
    return ControlCommand(
        command_id=command_id,
        session_id="session-1",
        authority_revision=1,
        type="session.attach",
        payload={"cursor": {"generation": 1, "sequence": 0}},
    )


async def _pump_until_actions_settle(
    host: ControlHost,
    scenario_id: str,
    *,
    expected_count: int = 1,
    until_terminal: bool = False,
) -> None:
    settled = False
    for _ in range(60):
        await host.pump()
        state = host.snapshot().state
        actions = state.actions
        if (
            len(actions) == expected_count
            and all(
                action.status
                in {"succeeded", "cancelled", "rejected", "failed", "uncertain"}
                for action in actions.values()
            )
            and (
                not until_terminal
                or state.session_status
                in {"completed", "failed", "cancelled", "budget_limited"}
            )
        ):
            settled = True
            break
        await asyncio.sleep(0.05)
    if not settled:
        raise AssertionError(f"{scenario_id} did not settle")
    if not until_terminal:
        # System actions and action resolution can append canonical events after
        # the proposal poll has returned. Consume that provider-owned tail.
        await host.pump()


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _read_private_sinks(sinks: list[IO[bytes]]) -> str:
    parts: list[str] = []
    for sink in sinks:
        sink.flush()
        sink.seek(0)
        parts.append(sink.read().decode("utf-8", errors="replace"))
    return "".join(parts)


def _integer_observation(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AssertionError("daemon integer observation is invalid")
    return value


async def _run_python_prime_scenario(
    row: Mapping[str, object],
    index: int,
) -> PrimeLoopScenarioResult:
    scenario_id = str(row["scenario_id"])
    package_root = (
        Path(__file__).resolve().parents[1] / "packages/typescript/prime-gateway"
    )
    # macOS's per-user temporary root is already close to the AF_UNIX path
    # limit; the production boundary requires an explicitly short private root.
    with tempfile.TemporaryDirectory(prefix="asterion-prime-", dir="/tmp") as directory:
        root = Path(directory)
        for name in (
            "gateway",
            "workspace",
            "agent",
            "session",
            "prime-source",
            "applications",
            "private",
        ):
            (root / name).mkdir(mode=0o700)
        artifact_lock_path = root / "artifact-lock.json"
        artifact_lock_path.write_text(
            json.dumps(_write_prime_source(root / "prime-source"))
        )
        daemon, socket_path, observations_path = await _start_fake_daemon(
            root, scenario_id
        )
        daemon_starts = 1
        gateway_starts = 0
        worker_pids: list[int] = []
        child_sidecars: list[PrimeSidecarProcess] = []
        completed_graphs: list[Mapping[str, object]] = []
        evidence_gaps: set[str] = set()
        daemon_observation_segments: list[Mapping[str, object]] = []
        daemon_stdout_parts: list[str] = []
        daemon_stderr_parts: list[str] = []
        gateway_stderr_sinks: list[IO[bytes]] = []
        exception_observations: list[str] = []
        client: PrimeControlPlaneClient | None = None

        def private_stderr_sink() -> IO[bytes]:
            sink = cast(IO[bytes], tempfile.TemporaryFile(mode="w+b"))
            gateway_stderr_sinks.append(sink)
            return sink

        try:
            authority = _envelope()
            if scenario_id == "prime-loop-budget":
                authority = _envelope(
                    budget_limit=BudgetLimit(0, 0, 0, 0, 0),
                )
            elif scenario_id == "prime-loop-checkpoint":
                authority = _envelope(
                    allowed_operations=(
                        "application.invoke",
                        "checkpoint.create",
                        "child.spawn",
                    )
                )
            elif scenario_id == "prime-loop-application":
                authority = _envelope(
                    allowed_operations=(
                        "application.invoke",
                        "child.spawn",
                        "goal.complete",
                    )
                )
            common_options = {
                "agent_dir": str(root / "agent"),
                "artifact_lock_path": str(artifact_lock_path),
                "authority_id": authority.authority_id,
                "expected_runtime_build_id": "fake-build-1",
                "execution_domain": "trusted-local",
                "gateway_root": str(root / "gateway"),
                "generation": "1",
                "max_continuations": "1",
                "max_controller_tokens": "100",
                "max_turns": "1",
                "model": "provider-free-model",
                "node_executable": str(Path(shutil.which("node") or "node")),
                "prime_socket_path": str(socket_path),
                "prime_source_root": str(root / "prime-source"),
                "provider": "provider-free",
                "session_dir": str(root / "session"),
                "session_id": "session-1",
                "sidecar_entry": str(package_root / "dist/src/main.js"),
                "timeout_ms": "2000",
                "workspace": str(root / "workspace"),
            }
            descriptor = {
                "agentDir": str(root / "agent"),
                "artifactLockPath": str(artifact_lock_path),
                "authorityId": authority.authority_id,
                "authorityRevision": authority.revision,
                "expectedRuntimeBuildId": "fake-build-1",
                "gatewayRoot": str(root / "gateway"),
                "generation": 1,
                "maxContinuations": 1,
                "maxControllerTokens": 100,
                "maxTurns": 1,
                "model": "provider-free-model",
                "portfolio": [
                    {
                        "kind": "application",
                        "provider_id": grant.provider_id,
                        "application_id": grant.application_id,
                        "version": grant.version,
                        "runtime_id": grant.runtime_id,
                    }
                    for grant in authority.allowed_portfolio
                ],
                "primeSocketPath": str(socket_path),
                "primeSourceRoot": str(root / "prime-source"),
                "provider": "provider-free",
                "remainingBudget": {
                    "controller_tokens": authority.budget_limit.controller_tokens,
                    "application_tokens": authority.budget_limit.application_tokens,
                    "child_tokens": authority.budget_limit.child_tokens,
                    "aggregate_tokens": authority.budget_limit.aggregate_tokens,
                    "cost_micros": authority.budget_limit.cost_micros,
                    "deadline_ms": authority.max_action_deadline_ms,
                },
                "sessionDir": str(root / "session"),
                "sessionId": "session-1",
                "skillPath": str(root / "skill.md"),
                "timeoutMs": 2_000,
                "workspace": str(root / "workspace"),
            }
            (root / "skill.md").write_text("# provider-free skill\n")
            process = await PrimeSidecarProcess.start(
                PrimeSidecarLaunchOptions(
                    node_executable=Path(shutil.which("node") or "node"),
                    sidecar_entry=package_root / "dist/src/main.js",
                    private_descriptor=descriptor,
                    environ={},
                    request_timeout=5,
                    private_stderr_sink=private_stderr_sink(),
                )
            )
            gateway_starts += 1
            private_resolver = _PrivateResolver()
            client = PrimeControlPlaneClient(
                process=process,
                private_content=private_resolver,
                manifest=prime_control_plane_binding().manifest,
            )
            recorder = MemoryPathlightRecorder(_opaque_id(600 + index))
            audit: list[str] = []
            implementation = (
                _WorkerCrashImplementation(audit, worker_pids)
                if scenario_id == "prime-loop-worker-crash"
                else UsageImplementation(audit, input_tokens=4, output_tokens=3)
            )
            provider, application, assembly = _assembly(
                root / "applications",
                implementation,
            )
            provider = InstalledApplicationProvider(
                protocol=APPLICATION_PROVIDER_PROTOCOL,
                provider_id=provider.provider_id,
                resource_root=provider.resource_root,
                applications=(
                    application,
                    _application(root / "applications", "zeta", "2.0.0"),
                ),
            )
            plan = _prime_plan(root, provider)
            prime_binding = prime_control_plane_binding()

            def tracked_process_factory(
                options: PrimeSidecarLaunchOptions,
            ) -> PrimeSidecarProcess:
                tracked = PrimeSidecarProcess(
                    replace(options, private_stderr_sink=private_stderr_sink())
                )
                child_sidecars.append(tracked)
                return tracked

            tracked_binding = replace(
                prime_binding,
                factory=lambda context: build_prime_control_plane_client(
                    context, process_factory=tracked_process_factory
                ),
            )

            def child_executor_factory(
                authority: AuthorityEnvelope,
                children: ChildSessionService,
                client: ControlPlaneClient | None = None,
            ) -> _ScenarioExecutor:
                del authority, client
                return _ScenarioExecutor(f"{scenario_id}-child", children)

            def derive_child_options(
                base: Mapping[str, str],
                *,
                child_root: Path,
                child_session_id: str,
                child_authority: AuthorityEnvelope,
                generation: int,
            ) -> Mapping[str, str]:
                return derive_prime_child_control_options(
                    base,
                    child_root=child_root,
                    child_session_id=child_session_id,
                    child_authority=child_authority,
                    generation=generation,
                )

            children = ChildSessionService(
                plan=plan,
                authority=authority,
                control_factories=ControlPlaneFactoryRegistry((tracked_binding,)),
                private_root=root / "private",
                content=client,
                child_action_executor_factory=child_executor_factory,
                clock_ms=lambda: 1_000,
                control_options=common_options,
                derive_control_options=derive_child_options,
                host_services={"private-content": client},
            )
            runtime_factories = RuntimeFactoryRegistry(
                (
                    RuntimeFactoryBinding(
                        runtime_id="fake.runtime",
                        capabilities=(),
                        factory=lambda _context: RecordingRuntime(audit),
                    ),
                )
            )
            application_executor = ApplicationActionExecutor(
                plan=plan,
                providers=(provider,),
                runtime_factories=runtime_factories,
                runtime_options={
                    identity: {} for identity in plan.portfolio_by_identity
                },
                content=client,
                results=RecordingResultStore(audit),
                host_services={"secret.service": {"ready": True}},
                pathlight=None,
                child_service=children,
                system_service=PrimeSystemActionService(client),
            )
            executor = _FaultBoundaryExecutor(
                application_executor,
                scenario_id,
                sidecar=process,
                supervisor=daemon,
            )
            journal = FileCanonicalJournal.open(root / "journal", "session-1")
            host = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=AuthorityLedger(authority),
                journal=journal,
                client=client,
                action_executor=executor,
                clock_ms=lambda: 1_000,
                cancellation_signal=_StaticCancellation(
                    scenario_id == "prime-loop-cancel"
                ),
                pathlight=recorder,
                child_service=children,
            )

            async def restart_host() -> None:
                nonlocal process, client, recorder, journal, host, gateway_starts
                process = await PrimeSidecarProcess.start(
                    PrimeSidecarLaunchOptions(
                        node_executable=Path(shutil.which("node") or "node"),
                        sidecar_entry=package_root / "dist/src/main.js",
                        private_descriptor=descriptor,
                        environ={},
                        request_timeout=5,
                        private_stderr_sink=private_stderr_sink(),
                    )
                )
                gateway_starts += 1
                client = PrimeControlPlaneClient(
                    process=process,
                    private_content=private_resolver,
                    manifest=prime_control_plane_binding().manifest,
                )
                recorder = MemoryPathlightRecorder(
                    _opaque_id(800 + index + gateway_starts)
                )
                journal = FileCanonicalJournal.open(root / "journal", "session-1")
                recovered_executor = ApplicationActionExecutor(
                    plan=plan,
                    providers=(provider,),
                    runtime_factories=runtime_factories,
                    runtime_options={
                        identity: {} for identity in plan.portfolio_by_identity
                    },
                    content=client,
                    results=RecordingResultStore(audit),
                    host_services={"secret.service": {"ready": True}},
                    pathlight=None,
                    system_service=PrimeSystemActionService(client),
                )
                host = ControlHost(
                    session_id="session-1",
                    generation=1,
                    plan=plan,
                    authority=AuthorityLedger(authority),
                    journal=journal,
                    client=client,
                    action_executor=recovered_executor,
                    clock_ms=lambda: 1_000,
                    cancellation_signal=_StaticCancellation(False),
                    pathlight=recorder,
                )

            async def close_host_for_restart(*, crashed: bool) -> None:
                nonlocal client
                previous = host.snapshot()
                try:
                    await host.close()
                except ControlHostTransportError as error:
                    exception_observations.append(f"{type(error).__name__}:{error}")
                    if not crashed:
                        raise
                graph = recorder.snapshot()
                if graph is not None:
                    completed_graphs.append(graph)
                evidence_gaps.update(previous.evidence_gaps)
                client = None

            await host.dispatch(_create_command())
            if scenario_id in {
                "prime-loop-application",
                "prime-loop-child",
                "prime-loop-redaction",
                "prime-loop-worker-crash",
                "prime-loop-cancel",
                "prime-loop-budget",
                "prime-loop-checkpoint",
            }:
                await _pump_until_actions_settle(
                    host,
                    scenario_id,
                    expected_count=2 if scenario_id == "prime-loop-application" else 1,
                    until_terminal=scenario_id == "prime-loop-application",
                )
            elif scenario_id == "prime-loop-detach-attach":
                await host.pump()
                await close_host_for_restart(crashed=False)
                await restart_host()
                await host.pump()
            elif scenario_id == "prime-loop-gateway-crash":
                try:
                    await _pump_until_actions_settle(host, scenario_id)
                except ControlHostTransportError as error:
                    exception_observations.append(f"{type(error).__name__}:{error}")
                else:
                    raise AssertionError(
                        "gateway crash did not break terminal delivery"
                    )
                await close_host_for_restart(crashed=True)
                await restart_host()
                await host.pump()
            elif scenario_id == "prime-loop-supervisor-crash":
                await _pump_until_actions_settle(host, scenario_id)
                daemon_observation_segments.append(
                    cast(
                        Mapping[str, object], json.loads(observations_path.read_text())
                    )
                )
                daemon_stdout_parts.append(
                    (
                        await daemon.stdout.read() if daemon.stdout is not None else b""
                    ).decode("utf-8", errors="replace")
                )
                daemon_stderr_parts.append(
                    (
                        await daemon.stderr.read() if daemon.stderr is not None else b""
                    ).decode("utf-8", errors="replace")
                )
                daemon, socket_path, observations_path = await _start_fake_daemon(
                    root, scenario_id
                )
                daemon_starts += 1
                await host.dispatch(
                    _attach_command("command-attach-after-supervisor-restart")
                )
                await host.pump()
            else:
                raise AssertionError(f"{scenario_id} is not configured")
            snapshot = host.snapshot()
            actions = tuple(snapshot.state.actions.values())
            expected_action_statuses = {
                "prime-loop-application": ("succeeded", "succeeded"),
                "prime-loop-child": ("succeeded",),
                "prime-loop-redaction": ("succeeded",),
                "prime-loop-checkpoint": ("succeeded",),
                "prime-loop-gateway-crash": ("uncertain",),
                "prime-loop-supervisor-crash": ("uncertain",),
                "prime-loop-worker-crash": ("uncertain",),
                "prime-loop-cancel": ("cancelled",),
                "prime-loop-budget": ("rejected",),
            }.get(scenario_id)
            if expected_action_statuses is None:
                if actions:
                    raise AssertionError(f"{scenario_id} action count is invalid")
            else:
                actual_action_statuses = tuple(action.status for action in actions)
                if actual_action_statuses != expected_action_statuses:
                    raise AssertionError(f"{scenario_id} action count is invalid")
            journal_entries = tuple(journal.replay(JournalCursor(0)))
            journal_kinds = tuple(entry.record.kind for entry in journal_entries)
            if (
                expected_action_statuses is not None
                and "action.decided" not in journal_kinds
            ):
                raise AssertionError(f"{scenario_id} admission was not journaled")
            if scenario_id == "prime-loop-application":
                if (
                    "action.running" not in journal_kinds
                    or "action.receipted" not in journal_kinds
                ):
                    raise AssertionError("application execution was not journaled")
            if scenario_id == "prime-loop-budget" and (
                "action.running" in journal_kinds or "action.receipted" in journal_kinds
            ):
                raise AssertionError("budget rejection executed unexpectedly")
            final_host_snapshot = host.snapshot()
            await host.close()
            evidence_gaps.update(final_host_snapshot.evidence_gaps)
            final_graph = recorder.snapshot()
            if final_graph is not None:
                completed_graphs.append(final_graph)
            await _stop_process(daemon)
            daemon_stdout_parts.append(
                (
                    await daemon.stdout.read() if daemon.stdout is not None else b""
                ).decode("utf-8", errors="replace")
            )
            daemon_stderr_parts.append(
                (
                    await daemon.stderr.read() if daemon.stderr is not None else b""
                ).decode("utf-8", errors="replace")
            )
            daemon_observation_segments.append(
                cast(Mapping[str, object], json.loads(observations_path.read_text()))
            )
            observations = _merge_daemon_observations(daemon_observation_segments)
            daemon_stdout = "".join(daemon_stdout_parts)
            daemon_stderr = "".join(daemon_stderr_parts)
            if observations["skillFailures"] != []:
                raise AssertionError(f"{scenario_id} skill bridge failed")
            if scenario_id == "prime-loop-application" and observations[
                "skillOperations"
            ] != ["application.invoke", "goal.complete"]:
                raise AssertionError("application-to-goal chain was not observed")
            expected_disconnects = (
                ["application.invoke"]
                if scenario_id == "prime-loop-gateway-crash"
                else []
            )
            if observations["skillDisconnects"] != expected_disconnects:
                raise AssertionError(f"{scenario_id} skill disconnect count is invalid")
            skill_responses = cast(
                list[Mapping[str, object]], observations["skillResponses"]
            )
            expected_skill_responses = (
                2
                if scenario_id == "prime-loop-application"
                else 1
                if expected_action_statuses is not None
                and scenario_id
                not in {"prime-loop-gateway-crash", "prime-loop-supervisor-crash"}
                else 0
            )
            if len(skill_responses) != expected_skill_responses:
                raise AssertionError(f"{scenario_id} skill response count is invalid")
            for response in skill_responses:
                operation = str(response.get("operation"))
                expected_admission = {
                    "prime-loop-budget": "rejected",
                }.get(scenario_id, "admitted")
                expected_terminal = {
                    "prime-loop-worker-crash": "uncertain",
                    "prime-loop-cancel": "cancelled",
                    "prime-loop-budget": None,
                }.get(scenario_id, "succeeded")
                if response.get("admission") != expected_admission:
                    raise AssertionError(
                        f"{scenario_id} {operation} admission response is invalid"
                    )
                if response.get("terminal") != expected_terminal:
                    raise AssertionError(
                        f"{scenario_id} {operation} terminal response is invalid"
                    )
            pathlight_nodes = tuple(
                sorted(
                    {
                        str(event["kind"])
                        for graph in completed_graphs
                        for event in cast(list[Mapping[str, object]], graph["events"])
                    }
                )
            )
            pathlight_events = [
                event
                for graph in completed_graphs
                for event in cast(list[Mapping[str, object]], graph["events"])
            ]
            pathlight_control_events = tuple(
                sorted(
                    {
                        str(attributes["control_event_type"])
                        for event in pathlight_events
                        if event.get("status") == "started"
                        and isinstance(attributes := event.get("attributes"), Mapping)
                        and isinstance(attributes.get("control_event_type"), str)
                    }
                )
            )
            for event in pathlight_events:
                attributes = event.get("attributes")
                if (
                    event.get("status") == "started"
                    and isinstance(attributes, Mapping)
                    and "control_event_type" in attributes
                ):
                    journal_position = attributes.get("journal_position")
                    if (
                        isinstance(journal_position, bool)
                        or not isinstance(journal_position, int)
                        or journal_position < 0
                    ):
                        raise AssertionError(
                            f"{scenario_id} Pathlight journal position is invalid"
                        )
            proposed_scope_digests = {
                str(attributes["scope_sha256"])
                for event in pathlight_events
                if event.get("status") == "started"
                and isinstance(attributes := event.get("attributes"), Mapping)
                and attributes.get("control_event_type") == "action.proposed"
                and isinstance(attributes.get("scope_sha256"), str)
            }
            expected_action_kinds = {
                "checkpoint.create"
                if operation == "checkpoint.request"
                else str(operation)
                for operation in cast(list[object], observations["skillOperations"])
            }
            if not {_sha256(kind) for kind in expected_action_kinds}.issubset(
                proposed_scope_digests
            ):
                raise AssertionError(
                    f"{scenario_id} canonical action evidence is incomplete"
                )
            public_events = [
                _plain(entry.record.payload["event"])
                for entry in journal_entries
                if entry.record.kind == "event.accepted"
                and isinstance(entry.record.payload.get("event"), Mapping)
            ]
            gateway_stderr = _read_private_sinks(gateway_stderr_sinks)
            serialized = json.dumps(
                {
                    "scenario_id": scenario_id,
                    "daemon": observations,
                    "daemon_stderr": daemon_stderr,
                    "daemon_stdout": daemon_stdout,
                    "gateway_stderr": gateway_stderr,
                    "host_state": repr(snapshot.state),
                    "exception_strings": tuple(exception_observations),
                    "public_events": public_events,
                    "journal": tuple(
                        {
                            "kind": entry.record.kind,
                            "payload": _plain(entry.record.payload),
                        }
                        for entry in journal_entries
                    ),
                    "pathlight": tuple(_plain(graph) for graph in completed_graphs),
                },
                sort_keys=True,
            )
            return PrimeLoopScenarioResult(
                scenario_id=scenario_id,
                status="PASS",
                outcome=_scenario_outcome(scenario_id, actions),
                evidence_id=f"evidence.phase1.{_sha256(serialized)}",
                provider_operations=_integer_observation(
                    observations["modelProviderOperations"]
                ),
                application_operations=audit.count("implementation.execute"),
                process_counts={
                    key: value
                    for key, value in {
                        "fake_daemon": daemon_starts,
                        "gateway": gateway_starts
                        + len(
                            {
                                sidecar.pid
                                for sidecar in child_sidecars
                                if sidecar.pid is not None
                            }
                        ),
                        "worker": len(set(worker_pids)),
                    }.items()
                    if value
                },
                pathlight_nodes=pathlight_nodes,
                pathlight_control_events=pathlight_control_events,
                pathlight_gaps=tuple(sorted(evidence_gaps)),
                serialized_observations=serialized,
            )
        finally:
            if client is not None:
                try:
                    await client.close()
                except Exception:
                    pass
            await _stop_process(daemon)
            for sink in gateway_stderr_sinks:
                sink.close()


def _merge_daemon_observations(
    values: list[Mapping[str, object]],
) -> Mapping[str, object]:
    if not values:
        raise AssertionError("daemon observations are unavailable")
    merged = dict(values[-1])
    merged["connectionCount"] = sum(
        _integer_observation(value["connectionCount"]) for value in values
    )
    merged["modelProviderOperations"] = sum(
        _integer_observation(value["modelProviderOperations"]) for value in values
    )
    merged["applicationOperations"] = sum(
        _integer_observation(value["applicationOperations"]) for value in values
    )
    counts: dict[str, int] = {}
    for value in values:
        for key, count in cast(Mapping[str, object], value["commandCounts"]).items():
            counts[key] = counts.get(key, 0) + _integer_observation(count)
    merged["commandCounts"] = counts
    for field in (
        "acknowledgements",
        "clientIds",
        "emittedGoalUpdates",
        "skillFailures",
        "skillDisconnects",
        "skillOperations",
        "skillResponses",
    ):
        merged[field] = [
            item
            for value in values
            for item in cast(list[object], value.get(field, []))
        ]
    return merged


def _scenario_outcome(scenario_id: str, actions: tuple[object, ...]) -> str:
    statuses = tuple(getattr(action, "status", None) for action in actions)
    if scenario_id in {
        "prime-loop-application",
        "prime-loop-child",
        "prime-loop-checkpoint",
        "prime-loop-redaction",
    }:
        expected_count = 2 if scenario_id == "prime-loop-application" else 1
        if statuses != ("succeeded",) * expected_count:
            raise AssertionError(f"{scenario_id} lacks proven successful effects")
        return "proven-effect-succeeded"
    if scenario_id == "prime-loop-detach-attach":
        if statuses:
            raise AssertionError("detach/attach unexpectedly executed an action")
        return "proven-effect-succeeded"
    if scenario_id in {
        "prime-loop-gateway-crash",
        "prime-loop-supervisor-crash",
        "prime-loop-worker-crash",
    }:
        if statuses != ("uncertain",):
            raise AssertionError(f"{scenario_id} did not preserve uncertainty")
        return "unknown-progress-uncertain"
    if scenario_id == "prime-loop-cancel":
        if statuses != ("cancelled",):
            raise AssertionError("cancel scenario did not prove cancellation")
        return "no-effect-cancelled"
    if scenario_id == "prime-loop-budget":
        if statuses != ("rejected",):
            raise AssertionError("budget scenario did not reject before execution")
        return "no-effect-failed"
    raise AssertionError(f"{scenario_id} outcome is unavailable")


async def _run_all_python_prime_scenarios(
    rows: Mapping[str, Mapping[str, object]],
) -> tuple[PrimeLoopScenarioResult, ...]:
    return tuple(
        await asyncio.gather(
            *(
                _run_python_prime_scenario(rows[scenario_id], index)
                for index, scenario_id in enumerate(EXPECTED_IDS, start=1)
            )
        )
    )


def run_prime_loop_scenarios(
    *, fake_prime: bool
) -> tuple[PrimeLoopScenarioResult, ...]:
    if fake_prime is not True:
        raise AssertionError("Task 12 only admits provider-free fake Prime evidence")
    rows = {str(row["scenario_id"]): row for row in _load_scenarios()}
    package_root = (
        Path(__file__).resolve().parents[1] / "packages/typescript/prime-gateway"
    )
    subprocess.run(
        ["npm", "run", "build"],
        cwd=package_root,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return asyncio.run(_run_all_python_prime_scenarios(rows))


class TestPrimeVerifiedLoopChildBoundary(unittest.TestCase):
    def test_hostile_parent_options_are_redacted(self) -> None:
        class HostileOptions(Mapping[str, str]):
            def __getitem__(self, key: str) -> str:
                raise RuntimeError(f"SENTINEL:{key}")

            def __iter__(self):
                raise RuntimeError("SENTINEL")

            def __len__(self) -> int:
                raise RuntimeError("SENTINEL")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError) as raised:
                derive_prime_child_control_options(
                    HostileOptions(),
                    child_root=root,
                    child_session_id="child-session-child-1",
                    child_authority=_child_envelope(authority_id="child:child-1"),
                    generation=1,
                )
            self.assertEqual(
                str(raised.exception), "Prime child control options are invalid"
            )
            self.assertNotIn("SENTINEL", str(raised.exception))

    def test_prime_child_options_are_distinct_narrowed_and_native_rlm_constant_is_zero(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_paths(root)
            parent = make_context(root)
            child_root = root / "children" / "child-1"
            child_root.mkdir(parents=True, mode=0o700)
            child_authority = _child_envelope(
                authority_id="child:child-1",
                budget_limit=BudgetLimit(25, 0, 50, 50, 10),
                max_recursion_depth=0,
                max_action_deadline_ms=500,
            )

            options = derive_prime_child_control_options(
                parent.options,
                child_root=child_root,
                child_session_id="child-session-child-1",
                child_authority=child_authority,
                generation=1,
            )

            self.assertEqual(PRIME_NATIVE_RLM_MAX_DEPTH, 0)
            self.assertEqual(options["session_id"], "child-session-child-1")
            self.assertEqual(options["authority_id"], "child:child-1")
            self.assertEqual(options["generation"], "1")
            self.assertEqual(options["max_controller_tokens"], "25")
            self.assertEqual(options["timeout_ms"], "500")
            self.assertNotEqual(options["session_dir"], parent.options["session_dir"])
            self.assertNotEqual(options["gateway_root"], parent.options["gateway_root"])
            self.assertTrue(options["session_dir"].startswith(str(child_root)))
            self.assertTrue(options["gateway_root"].startswith(str(child_root)))
            self.assertTrue(options["agent_dir"].startswith(str(child_root)))
            self.assertEqual(
                options["prime_socket_path"], parent.options["prime_socket_path"]
            )
            self.assertEqual(options["model"], parent.options["model"])
            self.assertEqual(options["workspace"], parent.options["workspace"])
            self.assertEqual(
                options["prime_source_root"], parent.options["prime_source_root"]
            )
            self.assertEqual(
                options["artifact_lock_path"], parent.options["artifact_lock_path"]
            )

    def test_prime_child_options_reject_zero_caps_that_prime_descriptor_cannot_accept(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_paths(root)
            parent = make_context(root)
            child_root = root / "children" / "child-1"
            child_root.mkdir(parents=True, mode=0o700)

            with self.assertRaises(ValueError):
                derive_prime_child_control_options(
                    parent.options,
                    child_root=child_root,
                    child_session_id="child-session-child-1",
                    child_authority=_child_envelope(
                        authority_id="child:child-1",
                        budget_limit=BudgetLimit(0, 0, 50, 50, 10),
                    ),
                    generation=1,
                )
            with self.assertRaises(ValueError):
                derive_prime_child_control_options(
                    parent.options,
                    child_root=child_root,
                    child_session_id="child-session-child-1",
                    child_authority=_child_envelope(authority_id="child:child-1"),
                    generation=0,
                )


class TestPrimeProviderFreeVerifiedLoop(unittest.TestCase):
    def test_scenario_ledger_is_closed_and_stable(self) -> None:
        scenarios = _load_scenarios()

        self.assertEqual(
            tuple(cast(str, item["scenario_id"]) for item in scenarios),
            EXPECTED_IDS,
        )
        for item in scenarios:
            self.assertEqual(
                set(item),
                {
                    "scenario_id",
                    "boundary",
                    "outcome",
                    "process_counts",
                    "model_provider_operations",
                    "application_operations",
                    "required_pathlight_nodes",
                    "required_pathlight_control_events",
                    "required_pathlight_gaps",
                },
            )
            self.assertEqual(item["model_provider_operations"], 0)

    def test_all_provider_free_prime_loop_scenarios_pass(self) -> None:
        results = run_prime_loop_scenarios(fake_prime=True)

        ledger = {str(row["scenario_id"]): row for row in _load_scenarios()}
        self.assertEqual(
            tuple(result.scenario_id for result in results),
            EXPECTED_IDS,
        )
        self.assertTrue(all(result.status == "PASS" for result in results))
        self.assertEqual(sum(result.provider_operations for result in results), 0)
        for result in results:
            row = ledger[result.scenario_id]
            required_nodes = tuple(
                str(item)
                for item in cast(list[object], row["required_pathlight_nodes"])
            )
            required_gaps = tuple(
                str(item) for item in cast(list[object], row["required_pathlight_gaps"])
            )
            required_control_events = tuple(
                str(item)
                for item in cast(list[object], row["required_pathlight_control_events"])
            )
            self.assertEqual(
                result.provider_operations, row["model_provider_operations"]
            )
            self.assertEqual(
                result.application_operations, row["application_operations"]
            )
            self.assertEqual(result.process_counts, row["process_counts"])
            self.assertEqual(result.outcome, row["outcome"])
            self.assertTrue(set(required_nodes).issubset(result.pathlight_nodes))
            self.assertTrue(
                set(required_control_events).issubset(result.pathlight_control_events)
            )
            self.assertEqual(required_gaps, ())
            self.assertEqual(result.pathlight_gaps, ())
            for sentinel in SENTINELS:
                self.assertNotIn(sentinel, result.serialized_observations)

        parity_fixture = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "prime-parity"
            / "v1"
            / "prime-agent-0.7.1.json"
        )
        parity_ledger = validate_parity_ledger(
            json.loads(parity_fixture.read_text(encoding="utf-8"))
        )
        registry = ParityScenarioRegistry(
            parity_ledger,
            provider_id="asterion.prime-gateway",
        )
        register_proven_phase1_prime_subset(
            registry,
            results,
            provider_factory=lambda: object(),
        )
        parity_report = asyncio.run(
            registry.run(PROVEN_PHASE1_PARITY_SCENARIO_IDS)
        )
        self.assertEqual(
            parity_report.passed_scenario_ids,
            PROVEN_PHASE1_PARITY_SCENARIO_IDS,
        )


if __name__ == "__main__":
    unittest.main()
