"""Operator-owned fixed model selection for the native P7 application."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
import socket
import subprocess
import threading
from types import MappingProxyType
from typing import cast

from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.applications.prime.p7.broker import ArcBroker
from asterion.applications.prime.p7.ipython_host import (
    PersistentIpythonHost,
    RestrictedPersistentIpythonWorker,
    p7_client_facade,
)
from asterion.applications.prime.runtime_binding import PreflightedPrimeLaunch
from asterion.runtimes.pi_extensions import PiExtensionBinding, PiExtensionLease
from asterion.runtimes.pi_rpc import PiRpcConfig, PiRpcSession


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
        trace = cast(PrimeTraceRecorder, self.host_services["prime.private-trace"])
        trace.close()
        launch = cast(PreflightedPrimeLaunch, self.host_services["prime.pi-extension"])
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
    popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
) -> P7OperatorResources:
    """Preflight the exact native P7 host-service closure from injected edges."""

    lease: PiExtensionLease | None = None
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
        binding = PiExtensionBinding(
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
        rpc_session = PiRpcSession(
            PiRpcConfig(
                command=command,
                cwd=working_directory,
                environment=approved_environment,
                deadline_seconds=selection.deadline_ms / 1000,
                inherited_fds=lease.inherited_fds,
            ),
            _popen=popen,
        )
        launch = PreflightedPrimeLaunch(
            rpc_session=rpc_session,
            extension_binding=binding,
            extension_lease=lease,
            approved_command=command,
            approved_environment=approved_environment,
        )
        broker = ArcBroker(engine=engine)
        ipython = PersistentIpythonHost(
            worker=worker, p7_client=p7_client_facade(broker)
        )
        trace = PrimeTraceRecorder(private_trace_root)
        bridge = _IpythonBridgeServer(parent, ipython)
        bridge.start()
        parent = None
        return P7OperatorResources(
            host_services={
                "prime.arc-broker": broker,
                "prime.ipython": ipython,
                "prime.pi-extension": launch,
                "prime.private-trace": trace,
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


__all__ = (
    "P7OperatorError",
    "P7OperatorResources",
    "P7RuntimeSelection",
    "build_p7_operator_resources",
    "p7_runtime_options",
    "resolve_p7_runtime",
    "resolve_pi_provider",
)
