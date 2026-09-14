"""Operator-owned fixed model selection for the native P7 application."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import socket
import sys
import threading
from types import MappingProxyType
from typing import cast

from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.applications.prime import create_provider
from asterion.applications.prime.p7.broker import ArcBroker, ArcRunReceipt
from asterion.applications.prime.p7.diagnostics import analyze_trace
from asterion.applications.prime.p7.ipython_host import (
    PersistentIpythonHost,
    RestrictedPersistentIpythonWorker,
    p7_client_facade,
)
from asterion.applications.prime.p7 import live
from asterion.applications.prime.p7.private_trace import (
    P7PrivateTraceReceipt,
    P7_TRACE_IDENTITIES,
)
from asterion.applications.prime.p7.prompt import P7_SOLVE_PROMPT
from asterion.applications.prime.runtime_binding import PrimeLaunch
from asterion.applications.provider import resolve_installed_provider
from asterion.capabilities.prime_arc_agi_3_solver.provider import (
    CAPABILITY_REF,
    PACKAGE_REF,
    create_prime_arc_agi_3_solver_package,
)
from asterion.capabilities.prime_ipython_coding_native.provider import (
    create_prime_ipython_coding_native_package,
)
from asterion.runner.composed import run_composed_application
from asterion.runtime.defaults import default_runtime_factory_registry
from asterion.runtime.factory import RuntimeFactoryContext
from asterion.runtime.pinned_extension import ExtensionBinding, ExtensionLease


_RUNTIME_ID = "asterion.prime"
_PROVIDER = "deepseek"
_MODEL = "deepseek-v4-flash"
_MAX_ACTIONS = 500
_MAX_CALLBACKS = 128
_DEADLINE_MS = 3_600_000
_BRIDGE_PROTOCOL = "asterion.prime-ipython/v1"
_BRIDGE_JOIN_SECONDS = 1.0
class P7OperatorError(RuntimeError):
    """The fixed P7 model host is unavailable."""


class _BridgeSignal:
    @property
    def cancelled(self) -> bool:
        return False


class _IpythonBridgeServer:
    """Operator-owned duplex adapter between the Pi extension and host."""

    def __init__(self, channel: socket.socket, host: PersistentIpythonHost) -> None:
        self._channel = channel
        self._host = host
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._started = False

    def __repr__(self) -> str:
        return "<_IpythonBridgeServer redacted>"

    def start(self) -> None:
        self._thread.start()
        self._started = True

    def close(self) -> None:
        self._stop.set()
        try:
            self._channel.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._channel.close()
        if self._started:
            self._thread.join(_BRIDGE_JOIN_SECONDS)

    def _serve(self) -> None:
        pending = bytearray()
        while not self._stop.is_set():
            try:
                chunk = self._channel.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            pending.extend(chunk)
            while b"\n" in pending:
                raw, _, trailing = pending.partition(b"\n")
                pending = bytearray(trailing)
                response = self._dispatch(bytes(raw))
                try:
                    self._channel.sendall(response + b"\n")
                except OSError:
                    return

    def _dispatch(self, raw: bytes) -> bytes:
        request_id = "invalid"
        try:
            value = json.loads(raw.decode("utf-8", "strict"))
            if (
                type(value) is not dict
                or set(value) != {"code", "protocol", "request_id", "type"}
                or value["protocol"] != _BRIDGE_PROTOCOL
                or value["type"] != "execute"
                or type(value["request_id"]) is not str
                or not value["request_id"]
                or type(value["code"]) is not str
                or not value["code"]
            ):
                raise ValueError
            request_id = value["request_id"]
            result = asyncio.run(
                self._host.execute(request_id, value["code"], _BridgeSignal())
            )
            output = ""
            if result.status == "ok" and result.content:
                candidate = result.content[0].get("text")
                if type(candidate) is str:
                    output = candidate
            response = {
                "output": output,
                "protocol": _BRIDGE_PROTOCOL,
                "request_id": request_id,
                "status": result.status,
                "type": "result",
            }
        except BaseException:
            response = {
                "output": "",
                "protocol": _BRIDGE_PROTOCOL,
                "request_id": request_id,
                "status": "error",
                "type": "result",
            }
        return json.dumps(response, separators=(",", ":"), sort_keys=True).encode()


class _P7BrokerClient:
    """Worker-facing mapping adapter over the native ARC broker."""

    __slots__ = ("_broker", "_recorder")

    def __init__(self, broker: ArcBroker, recorder: PrimeTraceRecorder) -> None:
        self._broker = broker
        self._recorder = recorder

    def observe(self) -> Mapping[str, object]:
        observation = self._broker.observe()
        return {
            "available_actions": list(observation.available_actions),
            "frame": observation.frame,
            "levels_completed": observation.levels_completed,
            "state": observation.state,
            "win_levels": observation.win_levels,
        }

    def status(self) -> Mapping[str, object]:
        status = self._broker.status()
        return {
            "actions_remaining": status.actions_remaining,
            "levels_completed": status.levels_completed,
            "primitive_actions": status.primitive_actions,
            "terminal_reason": status.terminal_reason,
        }

    def act(self, actions: object) -> Mapping[str, object]:
        if (
            type(actions) is not list
            or not actions
            or any(
                type(action) is not dict
                or set(action) != {"data", "name"}
                or action.get("data") != {}
                or type(action.get("name")) is not str
                for action in actions
            )
        ):
            raise P7OperatorError("P7 host services are unavailable")
        result = self._broker.act(tuple(str(action["name"]) for action in actions))
        for transition in result.transitions:
            self._recorder.append(
                "arc.action",
                P7_TRACE_IDENTITIES,
                {
                    "action": transition.action,
                    "after_sha256": transition.after_sha256,
                    "before_sha256": transition.before_sha256,
                    "levels_completed": transition.levels_completed,
                    "sequence": transition.sequence,
                },
            )
        return {
            "applied_count": result.applied_count,
            "levels_completed": result.levels_completed,
            "terminal": self.status(),
            "transitions": [
                {
                    "action": transition.action,
                    "after_sha256": transition.after_sha256,
                    "before_sha256": transition.before_sha256,
                    "levels_completed": transition.levels_completed,
                    "sequence": transition.sequence,
                }
                for transition in result.transitions
            ],
        }


@dataclass(frozen=True, slots=True)
class P7RuntimeSelection:
    runtime_id: str
    provider: str
    model: str
    max_actions: int
    max_callbacks: int
    deadline_ms: int

    def __post_init__(self) -> None:
        if self != P7RuntimeSelection.fixed():
            raise P7OperatorError("P7 runtime selection is invalid")

    @classmethod
    def fixed(cls) -> P7RuntimeSelection:
        value = object.__new__(cls)
        object.__setattr__(value, "runtime_id", _RUNTIME_ID)
        object.__setattr__(value, "provider", _PROVIDER)
        object.__setattr__(value, "model", _MODEL)
        object.__setattr__(value, "max_actions", _MAX_ACTIONS)
        object.__setattr__(value, "max_callbacks", _MAX_CALLBACKS)
        object.__setattr__(value, "deadline_ms", _DEADLINE_MS)
        return value


@dataclass(frozen=True, repr=False, slots=True)
class P7OperatorResources:
    """Concrete preflighted resources owned by one operator invocation."""

    host_services: Mapping[str, object]
    runtime_options: Mapping[str, str]
    _bridge: _IpythonBridgeServer

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "host_services", MappingProxyType(dict(self.host_services))
        )
        object.__setattr__(
            self, "runtime_options", MappingProxyType(dict(self.runtime_options))
        )

    def __repr__(self) -> str:
        return "<P7OperatorResources redacted>"

    async def close(self) -> None:
        """Boundedly release all resources retained by the operator."""

        self._bridge.close()
        ipython = cast(PersistentIpythonHost, self.host_services["prime.ipython"])
        await ipython.close()
        trace = cast(P7PrivateTraceReceipt, self.host_services["prime.private-trace"])
        trace.close()
        launch = cast(PrimeLaunch, self.host_services["prime.launch"])
        launch.extension_lease.close()


def resolve_pi_provider(environment: Mapping[str, str], *, model: str) -> str:
    """Resolve only the fixed DeepSeek host from passed operator environment."""

    try:
        available = (
            isinstance(environment, Mapping)
            and model == _MODEL
            and bool(environment.get("DEEPSEEK_API_KEY", "").strip())
        )
    except Exception:
        available = False
    if not available:
        raise P7OperatorError("P7 model host is unavailable") from None
    return _PROVIDER


def resolve_p7_runtime(environment: Mapping[str, str]) -> P7RuntimeSelection:
    """Resolve the one fixed model/runtime preset without exposing tuning knobs."""

    provider = resolve_pi_provider(environment, model=_MODEL)
    return P7RuntimeSelection(
        runtime_id=_RUNTIME_ID,
        provider=provider,
        model=_MODEL,
        max_actions=_MAX_ACTIONS,
        max_callbacks=_MAX_CALLBACKS,
        deadline_ms=_DEADLINE_MS,
    )


def p7_runtime_options(selection: P7RuntimeSelection) -> Mapping[str, str]:
    """Return immutable private factory options for the fixed selection."""

    if (
        type(selection) is not P7RuntimeSelection
        or selection != P7RuntimeSelection.fixed()
    ):
        raise P7OperatorError("P7 runtime selection is invalid")
    return MappingProxyType(
        {
            "deadline_ms": str(selection.deadline_ms),
            "max_actions": str(selection.max_actions),
            "max_callbacks": str(selection.max_callbacks),
            "model": selection.model,
            "provider": selection.provider,
        }
    )


def build_p7_operator_resources(
    *,
    environment: Mapping[str, str],
    pi_base_command: tuple[str, ...],
    extension_path: Path,
    working_directory: Path,
    worker: RestrictedPersistentIpythonWorker,
    engine: object,
    private_trace_root: Path,
) -> P7OperatorResources:
    """Preflight the exact native P7 host-service closure from injected edges."""

    lease: ExtensionLease | None = None
    parent: socket.socket | None = None
    child: socket.socket | None = None
    trace: PrimeTraceRecorder | None = None
    bridge: _IpythonBridgeServer | None = None
    try:
        selection = resolve_p7_runtime(environment)
        provider_environment = dict(environment)
        if (
            type(pi_base_command) is not tuple
            or not pi_base_command
            or any(
                type(part) is not str or not part or "\x00" in part
                for part in pi_base_command
            )
            or any(
                option in pi_base_command
                for option in ("--extension", "--model", "--provider")
            )
            or not isinstance(extension_path, Path)
            or extension_path.resolve(strict=True) != extension_path
            or not isinstance(working_directory, Path)
            or working_directory.resolve(strict=True) != working_directory
            or not working_directory.is_dir()
            or not isinstance(private_trace_root, Path)
            or private_trace_root.resolve(strict=True) != private_trace_root
            or not private_trace_root.is_dir()
            or any(
                type(name) is not str
                or not name
                or "\x00" in name
                or type(value) is not str
                or "\x00" in value
                for name, value in provider_environment.items()
            )
        ):
            raise ValueError
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        descriptor = child.fileno()
        binding = ExtensionBinding(
            extension_id="prime.ipython",
            path=extension_path,
            capabilities=("prime.tool.ipython",),
            inherited_fds=(descriptor,),
            environment={"ASTERION_PRIME_IPYTHON_FD": str(descriptor)},
        )
        lease = binding.preflight()
        child.close()
        child = None
        if set(provider_environment).intersection(lease.environment):
            raise ValueError
        approved_environment = {**provider_environment, **dict(lease.environment)}
        command = (
            *pi_base_command,
            "--provider",
            selection.provider,
            "--model",
            selection.model,
            *lease.command_args(),
        )
        launch = PrimeLaunch(
            approved_command=command,
            working_directory=working_directory,
            extension_id=binding.extension_id,
            extension_path=extension_path,
            extension_capabilities=binding.capabilities,
            binding_inherited_fds=binding.inherited_fds,
            binding_environment=dict(binding.environment),
            extension_lease=lease,
            deadline_seconds=selection.deadline_ms / 1000,
            compact_events=True,
            approved_environment=approved_environment,
        )
        trace = PrimeTraceRecorder(private_trace_root)
        broker = ArcBroker(engine=engine)
        ipython = PersistentIpythonHost(
            worker=worker, p7_client=p7_client_facade(_P7BrokerClient(broker, trace))
        )
        private_trace = P7PrivateTraceReceipt(broker, trace)
        bridge = _IpythonBridgeServer(parent, ipython)
        bridge.start()
        parent = None
        return P7OperatorResources(
            host_services={
                "prime.arc-broker": broker,
                "prime.ipython": ipython,
                "prime.launch": launch,
                "prime.private-trace": private_trace,
            },
            runtime_options=p7_runtime_options(selection),
            _bridge=bridge,
        )
    except Exception:
        if bridge is not None:
            bridge.close()
        if trace is not None:
            trace.close()
        if child is not None:
            child.close()
        if parent is not None:
            parent.close()
        if lease is not None:
            lease.close()
        raise P7OperatorError("P7 host services are unavailable") from None


@dataclass(frozen=True, slots=True)
class P7Invocation:
    """Every operator-owned value one preset invocation resolves to."""

    operator_root: Path
    environment: Mapping[str, str]
    arc_root: Path
    pi_base_command: tuple[str, ...]
    extension_path: Path


def _preflight(environment: Mapping[str, str]) -> P7Invocation:
    """Refuse source execution, then resolve every operator-owned input.

    Mirrors the P1 operator contract: the operator root is the mounted
    checkout, and the running distribution must be installed outside it so a
    source tree can never be executed in its place. The ARC root, node
    executable and Pi entry are operator-owned values the preset exports, so
    nothing here derives a path from a sibling checkout layout.
    """

    import asterion

    root = Path(environment[live.OPERATOR_ROOT_ENV]).resolve(strict=True)
    package = Path(str(asterion.__file__)).resolve(strict=True)
    if package.is_relative_to(root) or "site-packages" not in package.parts:
        raise P7OperatorError("P7 operator root is invalid")
    if not root.is_dir():
        raise P7OperatorError("P7 operator root is invalid")
    try:
        resolved = live.load_operator_environment(root)
        return P7Invocation(
            operator_root=root,
            environment=resolved,
            arc_root=live.resolve_arc_root(resolved),
            pi_base_command=live.pi_base_command(
                node=live.resolve_node(resolved),
                pi_entry=live.resolve_pi_entry(resolved),
            ),
            extension_path=live.extension_path(),
        )
    except live.P7LiveSolveError as error:
        raise P7OperatorError(str(error)) from None


async def run_live(invocation: P7Invocation, run_id: str) -> live.P7LiveExecution:
    """Run the one fixed solve and seal its private evidence.

    Recovered from the removed driver's live body, with the orchestration order
    unchanged: preflight every host service, run the composed application, seal
    and replay the broker, verify the sealed trace, then compare, and always
    release. Only the value sources differ; see
    :mod:`asterion.applications.prime.p7.live`.
    """

    root = invocation.operator_root
    private = live.private_root(root, run_id)
    trace_root = private / "trace"
    trace_root.mkdir(mode=0o700)
    worker = live.SubprocessPythonWorker(root=private)
    engine = live.ArcadeEngine(
        arc_root=invocation.arc_root, recordings_dir=private / "recordings"
    )
    print("[asterion-prime-p7] preflight", file=sys.stderr, flush=True)
    resources_ = build_p7_operator_resources(
        environment=invocation.environment,
        pi_base_command=invocation.pi_base_command,
        extension_path=invocation.extension_path,
        working_directory=root,
        worker=worker,
        engine=engine,
        private_trace_root=trace_root,
    )
    receipt: Mapping[str, object] = {}
    broker_receipt: ArcRunReceipt | None = None
    replay_verified = False
    sealed_trace = False
    cleanup_complete = False
    comparison_report: Path | None = None
    reason: str | None = None
    failure: BaseException | None = None
    diagnostics: dict[str, object] = {}
    try:
        print("[asterion-prime-p7] live-run", file=sys.stderr, flush=True)
        provider = resolve_installed_provider(
            create_provider(),
            runtime_factories=default_runtime_factory_registry(),
            # The provider publishes every installed Prime application, and the
            # composition closure is resolved for all of them, so the P1
            # package must be present even though this run executes P7 only.
            installed_packages=(
                create_prime_arc_agi_3_solver_package(),
                create_prime_ipython_coding_native_package(),
            ),
        )
        application = provider.applications[0]
        assembly = application.assemblies[0]
        runtime = assembly.runtime_binding.factory(
            RuntimeFactoryContext(
                provider_id="prime-applications",
                application_id="prime.arc-agi-3-solving",
                application_version="1.0.0",
                runtime_id="asterion.prime",
                assembly_path=assembly.path,
                options=resources_.runtime_options,
                host_services=resources_.host_services,
            )
        )
        result = await run_composed_application(
            assembly.plan,
            implementations=application.implementations,
            runtime=runtime,
            run_id=run_id,
            input_text=P7_SOLVE_PROMPT,
            host_services=resources_.host_services,
            implementation_packages={CAPABILITY_REF: PACKAGE_REF},
            signal=live.NeverCancelled(),
        )
        receipt = live.receipt_value(result.artifacts)
        broker = resources_.host_services["prime.arc-broker"]
        if not isinstance(broker, ArcBroker):
            raise live.P7LiveSolveError("P7 broker is unavailable")
        broker_receipt = broker.seal()
        broker.replay(
            lambda: live.ArcadeEngine(
                arc_root=invocation.arc_root,
                recordings_dir=private / "replay-recordings",
            )
        )
        replay_verified = True
        analyze_trace(live.read_trace_entries(trace_root))
        sealed_trace = True
        comparison_report = live.compare_if_available(root, trace_root, private)
    except Exception as error:
        failure = error
        reason = (
            str(error)
            if isinstance(error, live.P7LiveSolveError)
            else "P7 live solve unsuccessful"
        )
        raise
    finally:
        try:
            broker_value = resources_.host_services.get("prime.arc-broker")
            if isinstance(broker_value, ArcBroker):
                try:
                    status = broker_value.status()
                    diagnostics["broker_status"] = {
                        "actions_remaining": status.actions_remaining,
                        "levels_completed": status.levels_completed,
                        "primitive_actions": status.primitive_actions,
                        "terminal_reason": status.terminal_reason,
                    }
                except Exception:
                    pass
            # The launch seam carries plain data only, so there is no live Pi
            # session object left to read a failure or an stderr tail from.
            diagnostics["worker_cell_count"] = live.worker_cell_count(private)
            await resources_.close()
            engine.close()
            cleanup_complete = worker.closed
        finally:
            live.write_summary(
                root,
                private,
                run_id=run_id,
                receipt=receipt,
                broker_receipt=broker_receipt,
                replay_verified=replay_verified,
                sealed_trace=sealed_trace,
                cleanup_complete=cleanup_complete,
                comparison_report=comparison_report,
                reason=reason,
                failure=failure,
                diagnostics=diagnostics,
            )
    return live.P7LiveExecution(
        run_id=run_id,
        completed_level_count=int(receipt.get("completed_level_count", 0)),
        primitive_action_count=int(receipt.get("primitive_action_count", 0)),
        replay_verified=replay_verified,
        sealed_trace=sealed_trace,
        cleanup_complete=cleanup_complete,
        trace_root=trace_root,
        receipt=receipt,
        comparison_report=comparison_report,
    )


def classify_live_result(result: live.P7LiveExecution) -> Mapping[str, object]:
    """Project one completed solve into the public receipt, or fail closed."""

    if result.completed_level_count != 1:
        raise live.P7LiveSolveError("authoritative level transition was not observed")
    if not 1 <= result.primitive_action_count <= _MAX_ACTIONS:
        raise live.P7LiveSolveError("primitive action count is invalid")
    if not result.replay_verified:
        raise live.P7LiveSolveError("replay verification did not pass")
    if not result.sealed_trace:
        raise live.P7LiveSolveError("sealed trace was not verified")
    if not result.cleanup_complete:
        raise live.P7LiveSolveError("cleanup did not complete")
    return _public_receipt(
        "PASS",
        result.run_id,
        receipt=result.receipt,
        completed_level_count=result.completed_level_count,
        primitive_action_count=result.primitive_action_count,
        replay_verified=result.replay_verified,
        sealed_trace=result.sealed_trace,
        cleanup_complete=result.cleanup_complete,
        comparison_report=result.comparison_report,
    )


def _public_receipt(
    status: str,
    run_id: str,
    *,
    receipt: Mapping[str, object] | None = None,
    completed_level_count: int = 0,
    primitive_action_count: int = 0,
    replay_verified: bool = False,
    sealed_trace: bool = False,
    cleanup_complete: bool = False,
    comparison_report: Path | None = None,
    reason: str | None = None,
) -> Mapping[str, object]:
    """Build the one public receipt; private evidence never crosses this line."""

    source = {} if receipt is None else receipt
    safe: dict[str, object] = {
        "schema": "asterion.prime.p7-live-receipt/v1",
        "application_id": "prime.arc-agi-3-solving",
        "runtime_id": "asterion.prime",
        "provider": _PROVIDER,
        "model": _MODEL,
        "game_id": live.GAME_ID,
        "seed": live.SEED,
        "status": status,
        "run_id": run_id,
        "completed_level_count": completed_level_count,
        "primitive_action_count": primitive_action_count,
        "replay_verified": replay_verified,
        "sealed_trace": sealed_trace,
        "cleanup_complete": cleanup_complete,
    }
    for name in ("partial_game_score", "receipt_sha256", "promotion", "scope"):
        if name in source:
            safe[name] = source[name]
    if comparison_report is not None:
        safe["comparison_report"] = "available"
    if reason is not None:
        safe["reason"] = reason
    return safe


def _reject() -> int:
    print('{"status":"preflight-rejected"}')
    return 2


def main(argv: list[str] | None = None) -> int:
    """The only external input is the literal Make preset invocation."""

    invocation: P7Invocation | None = None
    try:
        if sys.argv[1:] if argv is None else argv:
            raise P7OperatorError("P7 operator arguments are rejected")
        invocation = _preflight(os.environ)
    except BaseException:
        pass
    if invocation is None:
        return _reject()
    run_id = live.safe_run_id()
    try:
        result = classify_live_result(asyncio.run(run_live(invocation, run_id)))
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        reason = (
            str(error)
            if isinstance(error, live.P7LiveSolveError)
            else "P7 live solve unsuccessful"
        )
        print(
            json.dumps(
                _public_receipt("unsuccessful", run_id, reason=reason),
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        print("[asterion-prime-p7] unsuccessful", file=sys.stderr, flush=True)
        return 1
    print(
        json.dumps(
            result, allow_nan=False, separators=(",", ":"), sort_keys=True
        )
    )
    print("[asterion-prime-p7] PASS", file=sys.stderr, flush=True)
    return 0


def _entrypoint() -> None:
    status = main()
    sys.stdout.flush()
    sys.stderr.flush()
    if status == 1:
        # Python joins default-executor threads again during interpreter exit.
        # A failed owner cannot regain an unbounded wait after public failure.
        os._exit(status)
    raise SystemExit(status)


if __name__ == "__main__":
    _entrypoint()


__all__ = (
    "P7OperatorError",
    "P7OperatorResources",
    "P7RuntimeSelection",
    "P7Invocation",
    "build_p7_operator_resources",
    "classify_live_result",
    "main",
    "p7_runtime_options",
    "resolve_p7_runtime",
    "resolve_pi_provider",
    "run_live",
)
