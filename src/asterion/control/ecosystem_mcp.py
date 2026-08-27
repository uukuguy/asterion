"""Provider-free owned MCP fixture lifecycle for Prime ecosystem parity tests."""

from __future__ import annotations

import hashlib
import json
import os
import selectors
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from asterion.runtime.host import CancellationSignal


MCP_CHALLENGE_DIGEST = hashlib.sha256(b"asterion-mcp-local-challenge").hexdigest()
MCP_CREDENTIAL = "opaque-mcp-refresh-token"

_OPAQUE = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-")
_TERMINAL = frozenset({"succeeded", "failed", "cancelled"})


class EcosystemMcpError(RuntimeError):
    """Redacted failure for owned MCP fixture startup and protocol errors."""


@dataclass(frozen=True)
class EcosystemMcpDescriptor:
    """Operator-owned executable binding for one exact local MCP server."""

    server_id: str
    version: str
    command: tuple[str, ...]
    credential_lease_id: str
    challenge_digest: str = MCP_CHALLENGE_DIGEST
    deadline_seconds: float = 5.0
    max_output_bytes: int = 8192

    def __post_init__(self) -> None:
        if not _valid_id(self.server_id) or not _valid_id(self.credential_lease_id):
            raise EcosystemMcpError("MCP fixture descriptor is invalid")
        if not self.version or any(char.isspace() for char in self.version):
            raise EcosystemMcpError("MCP fixture descriptor is invalid")
        if not self.command or not Path(self.command[0]).is_absolute():
            raise EcosystemMcpError("MCP fixture descriptor is invalid")
        if self.challenge_digest != MCP_CHALLENGE_DIGEST:
            raise EcosystemMcpError("MCP fixture descriptor is invalid")
        if self.deadline_seconds <= 0 or self.max_output_bytes <= 0:
            raise EcosystemMcpError("MCP fixture descriptor is invalid")


@dataclass(frozen=True)
class EcosystemMcpReceipt:
    status: Literal["succeeded", "failed", "cancelled"]
    server_id: str
    challenge_digest: str
    challenge_count: int
    credential_refresh_count: int
    initialize_count: int
    list_count: int
    replay_refresh_count: int = 0
    shutdown_count: int = 0
    provider_operations: int = 0
    model_credential_reads: int = 0
    owned_process_count_after_close: int = 0
    discovery_digest: str = ""

    def to_public_mapping(self) -> dict[str, object]:
        return {
            "challenge_count": self.challenge_count,
            "challenge_digest": self.challenge_digest,
            "credential_refresh_count": self.credential_refresh_count,
            "discovery_digest": self.discovery_digest,
            "initialize_count": self.initialize_count,
            "list_count": self.list_count,
            "model_credential_reads": self.model_credential_reads,
            "owned_process_count_after_close": self.owned_process_count_after_close,
            "provider_operations": self.provider_operations,
            "replay_refresh_count": self.replay_refresh_count,
            "server_id": self.server_id,
            "shutdown_count": self.shutdown_count,
            "status": self.status,
        }


@dataclass
class EcosystemMcpSession:
    session_id: str
    server_id: str
    discovery_path: Path
    process: subprocess.Popen[bytes] | None = field(repr=False)
    receipt: EcosystemMcpReceipt

    def __repr__(self) -> str:
        return (
            "EcosystemMcpSession("
            f"session_id={self.session_id!r}, server_id={self.server_id!r}, "
            f"status={self.receipt.status!r})"
        )


class OwnedMcpFixtureService:
    """Launch, refresh, and reap one local MCP fixture over direct stdio."""

    def __init__(self, private_root: str | Path) -> None:
        self._private_root = Path(private_root).resolve()
        self._private_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._bound_refreshes: set[tuple[str, str]] = set()
        self._refreshes: set[tuple[str, str]] = set()

    def open_channel(
        self,
        descriptor: EcosystemMcpDescriptor,
        cancellation: CancellationSignal | None = None,
    ) -> "OwnedMcpFixtureChannel":
        if _cancelled(cancellation):
            raise EcosystemMcpError("MCP fixture cancelled")
        discovery_path = self._write_discovery(descriptor)
        try:
            process = subprocess.Popen(
                descriptor.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self._private_root),
                env={},
                shell=False,
            )
            if (
                process.stdin is None
                or process.stdout is None
                or process.stderr is None
            ):
                raise EcosystemMcpError("MCP fixture failed")
            os.set_blocking(process.stdout.fileno(), False)
            os.set_blocking(process.stderr.fileno(), False)
            return OwnedMcpFixtureChannel(
                service=self,
                descriptor=descriptor,
                discovery_path=discovery_path,
                process=process,
            )
        except (OSError, ValueError, EcosystemMcpError):
            raise EcosystemMcpError("MCP fixture failed") from None

    def start(
        self,
        descriptor: EcosystemMcpDescriptor,
        cancellation: CancellationSignal | None = None,
    ) -> EcosystemMcpSession:
        if _cancelled(cancellation):
            return self._closed_session(descriptor, status="cancelled")
        channel: OwnedMcpFixtureChannel | None = None
        try:
            channel = self.open_channel(descriptor)
            channel.initialize_challenge()
            if _cancelled(cancellation):
                receipt = channel.cancel()
                return EcosystemMcpSession(
                    "mcp-session:cancelled",
                    descriptor.server_id,
                    channel.discovery_path,
                    None,
                    receipt,
                )
            credential = channel.refresh()
            channel.initialize_with_credential(credential)
            channel.list()
            receipt = channel.receipt("succeeded")
            return EcosystemMcpSession(
                "mcp-session:local",
                descriptor.server_id,
                channel.discovery_path,
                channel.process,
                receipt,
            )
        except (
            OSError,
            ValueError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            BrokenPipeError,
            TimeoutError,
            EcosystemMcpError,
        ):
            if channel is not None:
                channel.kill()
            raise EcosystemMcpError("MCP fixture failed") from None

    def refresh(self, lease_id: str, challenge_digest: str) -> str:
        if not _valid_id(lease_id) or challenge_digest != MCP_CHALLENGE_DIGEST:
            raise EcosystemMcpError("MCP fixture credential refresh rejected")
        key = (lease_id, challenge_digest)
        if key not in self._bound_refreshes or key in self._refreshes:
            raise EcosystemMcpError("MCP fixture credential refresh rejected")
        self._refreshes.add(key)
        return MCP_CREDENTIAL

    def replay(self, session: EcosystemMcpSession) -> EcosystemMcpReceipt:
        if session.receipt.status not in _TERMINAL:
            raise EcosystemMcpError("MCP fixture replay rejected")
        return session.receipt

    def close(self, session: EcosystemMcpSession) -> EcosystemMcpReceipt:
        process = session.process
        if process is not None and process.poll() is None:
            try:
                _send(process, {"type": "shutdown"})
                process.wait(timeout=1)
            except (BrokenPipeError, OSError, TimeoutError, subprocess.TimeoutExpired):
                self._kill(process)
        if process is not None:
            _close_streams(process)
        session.process = None
        receipt = EcosystemMcpReceipt(
            status=session.receipt.status,
            server_id=session.receipt.server_id,
            challenge_digest=session.receipt.challenge_digest,
            challenge_count=session.receipt.challenge_count,
            credential_refresh_count=session.receipt.credential_refresh_count,
            initialize_count=session.receipt.initialize_count,
            list_count=session.receipt.list_count,
            replay_refresh_count=session.receipt.replay_refresh_count,
            shutdown_count=session.receipt.shutdown_count
            + (1 if process is not None else 0),
            provider_operations=0,
            model_credential_reads=0,
            owned_process_count_after_close=0 if process is None or process.poll() is not None else 1,
            discovery_digest=session.receipt.discovery_digest,
        )
        session.receipt = receipt
        return receipt

    def _write_discovery(self, descriptor: EcosystemMcpDescriptor) -> Path:
        discovery = {
            "challenge_digest": descriptor.challenge_digest,
            "format": "asterion.ecosystem-mcp-discovery/v1",
            "server_id": descriptor.server_id,
            "version": descriptor.version,
        }
        path = self._private_root / f"{descriptor.server_id}.discovery.json"
        path.write_text(json.dumps(discovery, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        path.chmod(0o600)
        return path

    def _closed_session(
        self,
        descriptor: EcosystemMcpDescriptor,
        *,
        status: Literal["cancelled"],
    ) -> EcosystemMcpSession:
        discovery_path = self._write_discovery(descriptor)
        receipt = self._receipt(descriptor, status, discovery_path, 0, 0, 0)
        return EcosystemMcpSession("mcp-session:cancelled", descriptor.server_id, discovery_path, None, receipt)

    def _receipt(
        self,
        descriptor: EcosystemMcpDescriptor,
        status: Literal["succeeded", "failed", "cancelled"],
        discovery_path: Path,
        credential_refresh_count: int,
        initialize_count: int,
        list_count: int,
    ) -> EcosystemMcpReceipt:
        return EcosystemMcpReceipt(
            status=status,
            server_id=descriptor.server_id,
            challenge_digest=descriptor.challenge_digest,
            challenge_count=0,
            credential_refresh_count=credential_refresh_count,
            initialize_count=initialize_count,
            list_count=list_count,
            discovery_digest=_sha256(discovery_path.read_bytes()),
        )

    def _kill(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        _close_streams(process)


@dataclass
class OwnedMcpFixtureChannel:
    """Operator-owned local MCP stdio channel consumed by the Prime fixture."""

    service: OwnedMcpFixtureService = field(repr=False)
    descriptor: EcosystemMcpDescriptor
    discovery_path: Path
    process: subprocess.Popen[bytes] = field(repr=False)
    challenge_count: int = 0
    credential_refresh_count: int = 0
    initialize_count: int = 0
    list_count: int = 0
    replay_refresh_count: int = 0
    shutdown_count: int = 0
    _terminal: Literal["succeeded", "failed", "cancelled"] | None = field(
        default=None,
        repr=False,
    )

    def initialize_challenge(self) -> dict[str, object]:
        self._ensure_open()
        _send(
            self.process,
            {
                "type": "initialize",
                "server_id": self.descriptor.server_id,
                "version": self.descriptor.version,
                "lease_id": self.descriptor.credential_lease_id,
                "discovery_digest": _sha256(self.discovery_path.read_bytes()),
            },
        )
        self.initialize_count += 1
        challenge = _read(
            self.process,
            time.monotonic() + self.descriptor.deadline_seconds,
            self.descriptor.max_output_bytes,
        )
        if (
            challenge.get("type") != "auth_challenge"
            or challenge.get("server_id") != self.descriptor.server_id
            or challenge.get("challenge_digest") != self.descriptor.challenge_digest
        ):
            raise EcosystemMcpError("MCP fixture failed")
        self.challenge_count += 1
        self.service._bound_refreshes.add(
            (self.descriptor.credential_lease_id, self.descriptor.challenge_digest)
        )
        return {
            "challenge_digest": self.descriptor.challenge_digest,
            "lease_id": self.descriptor.credential_lease_id,
            "server_id": self.descriptor.server_id,
        }

    def refresh(self) -> str:
        self._ensure_open()
        credential = self.service.refresh(
            self.descriptor.credential_lease_id,
            self.descriptor.challenge_digest,
        )
        self.service._bound_refreshes.discard(
            (self.descriptor.credential_lease_id, self.descriptor.challenge_digest)
        )
        self.credential_refresh_count += 1
        return credential

    def initialize_with_credential(self, credential: str) -> dict[str, object]:
        self._ensure_open()
        _send(
            self.process,
            {
                "type": "initialize",
                "server_id": self.descriptor.server_id,
                "version": self.descriptor.version,
                "credential": credential,
            },
        )
        self.initialize_count += 1
        initialized = _read(
            self.process,
            time.monotonic() + self.descriptor.deadline_seconds,
            self.descriptor.max_output_bytes,
        )
        if (
            initialized.get("type") != "initialized"
            or initialized.get("server_id") != self.descriptor.server_id
        ):
            raise EcosystemMcpError("MCP fixture failed")
        return {"server_id": self.descriptor.server_id}

    def list(self) -> dict[str, object]:
        self._ensure_open()
        _send(self.process, {"type": "list"})
        listed = _read(
            self.process,
            time.monotonic() + self.descriptor.deadline_seconds,
            self.descriptor.max_output_bytes,
        )
        self.list_count += 1
        if listed.get("type") != "list_result" or listed.get("tool_count") != 1:
            raise EcosystemMcpError("MCP fixture failed")
        return {"resource_count": listed.get("resource_count", 0), "tool_count": 1}

    def replay(self) -> EcosystemMcpReceipt:
        if self._terminal not in _TERMINAL:
            raise EcosystemMcpError("MCP fixture replay rejected")
        return self.receipt(self._terminal)

    def shutdown(self) -> EcosystemMcpReceipt:
        if self._terminal is None:
            if self.process.poll() is None:
                _send(self.process, {"type": "shutdown"})
                self.shutdown_count += 1
                try:
                    self.process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self.kill()
            _close_streams(self.process)
            self._terminal = "succeeded"
        return self.receipt("succeeded")

    def cancel(self) -> EcosystemMcpReceipt:
        self.kill()
        self._terminal = "cancelled"
        return self.receipt("cancelled")

    def kill(self) -> None:
        self.service._kill(self.process)
        if self._terminal is None:
            self._terminal = "failed"

    def receipt(
        self,
        status: Literal["succeeded", "failed", "cancelled"],
    ) -> EcosystemMcpReceipt:
        return EcosystemMcpReceipt(
            status=status,
            server_id=self.descriptor.server_id,
            challenge_digest=self.descriptor.challenge_digest,
            challenge_count=self.challenge_count,
            credential_refresh_count=self.credential_refresh_count,
            initialize_count=self.initialize_count,
            list_count=self.list_count,
            replay_refresh_count=self.replay_refresh_count,
            shutdown_count=self.shutdown_count,
            provider_operations=0,
            model_credential_reads=0,
            owned_process_count_after_close=(
                0 if self.process.poll() is not None else 1
            ),
            discovery_digest=_sha256(self.discovery_path.read_bytes()),
        )

    def _ensure_open(self) -> None:
        if self._terminal is not None or self.process.poll() is not None:
            raise EcosystemMcpError("MCP fixture failed")


def _send(process: subprocess.Popen[bytes], value: Mapping[str, object]) -> None:
    if process.stdin is None:
        raise EcosystemMcpError("MCP fixture failed")
    process.stdin.write(
        (json.dumps(dict(value), sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
    )
    process.stdin.flush()


def _read(
    process: subprocess.Popen[bytes],
    deadline: float,
    max_output_bytes: int,
) -> dict[str, object]:
    if process.stdout is None or process.stderr is None:
        raise EcosystemMcpError("MCP fixture failed")
    selector = selectors.DefaultSelector()
    stdout_fd = process.stdout.fileno()
    stderr_fd = process.stderr.fileno()
    selector.register(stdout_fd, selectors.EVENT_READ, "stdout")
    selector.register(stderr_fd, selectors.EVENT_READ, "stderr")
    stdout = bytearray()
    total = 0
    try:
        while True:
            if total > max_output_bytes:
                raise EcosystemMcpError("MCP fixture failed")
            newline = stdout.find(b"\n")
            if newline >= 0:
                line = bytes(stdout[:newline])
                if len(line) > max_output_bytes:
                    raise EcosystemMcpError("MCP fixture failed")
                value = json.loads(line.decode("utf-8"))
                if not isinstance(value, dict):
                    raise EcosystemMcpError("MCP fixture failed")
                return value
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            events = selector.select(remaining)
            if not events:
                raise TimeoutError
            for key, _ in events:
                try:
                    chunk = os.read(key.fd, min(4096, max_output_bytes + 1))
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fd)
                    if key.data == "stdout" and not stdout:
                        raise EcosystemMcpError("MCP fixture failed")
                    continue
                total += len(chunk)
                if key.data == "stderr":
                    raise EcosystemMcpError("MCP fixture failed")
                stdout.extend(chunk)
    finally:
        selector.close()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _valid_id(value: str) -> bool:
    return bool(value) and all(char in _OPAQUE for char in value)


def _cancelled(cancellation: CancellationSignal | None) -> bool:
    return bool(cancellation is not None and cancellation.cancelled)


def _close_streams(process: subprocess.Popen[bytes]) -> None:
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
