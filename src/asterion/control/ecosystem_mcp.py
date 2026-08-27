"""Provider-free owned MCP fixture lifecycle for Prime ecosystem parity tests."""

from __future__ import annotations

import hashlib
import json
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
    credential_refresh_count: int
    initialize_count: int
    list_count: int
    provider_operations: int = 0
    model_credential_reads: int = 0
    owned_process_count_after_close: int = 0
    discovery_digest: str = ""

    def to_public_mapping(self) -> dict[str, object]:
        return {
            "challenge_digest": self.challenge_digest,
            "credential_refresh_count": self.credential_refresh_count,
            "discovery_digest": self.discovery_digest,
            "initialize_count": self.initialize_count,
            "list_count": self.list_count,
            "model_credential_reads": self.model_credential_reads,
            "owned_process_count_after_close": self.owned_process_count_after_close,
            "provider_operations": self.provider_operations,
            "server_id": self.server_id,
            "status": self.status,
        }


@dataclass
class EcosystemMcpSession:
    session_id: str
    server_id: str
    discovery_path: Path
    process: subprocess.Popen[str] | None = field(repr=False)
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

    def start(
        self,
        descriptor: EcosystemMcpDescriptor,
        cancellation: CancellationSignal | None = None,
    ) -> EcosystemMcpSession:
        if _cancelled(cancellation):
            return self._closed_session(descriptor, status="cancelled")
        discovery_path = self._write_discovery(descriptor)
        process: subprocess.Popen[str] | None = None
        initialize_count = 0
        list_count = 0
        credential_refresh_count = 0
        try:
            process = subprocess.Popen(
                descriptor.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                cwd=str(self._private_root),
                env={},
                shell=False,
            )
            if process.stdin is None or process.stdout is None:
                raise EcosystemMcpError("MCP fixture failed")
            deadline = time.monotonic() + descriptor.deadline_seconds
            _send(
                process,
                {
                    "type": "initialize",
                    "server_id": descriptor.server_id,
                    "version": descriptor.version,
                    "lease_id": descriptor.credential_lease_id,
                    "discovery_digest": _sha256(discovery_path.read_bytes()),
                },
            )
            initialize_count += 1
            challenge = _read(process, deadline, descriptor.max_output_bytes)
            if (
                challenge.get("type") != "auth_challenge"
                or challenge.get("server_id") != descriptor.server_id
                or challenge.get("challenge_digest") != descriptor.challenge_digest
            ):
                raise EcosystemMcpError("MCP fixture failed")
            if _cancelled(cancellation):
                self._kill(process)
                process = None
                receipt = self._receipt(
                    descriptor,
                    "cancelled",
                    discovery_path,
                    credential_refresh_count,
                    initialize_count,
                    list_count,
                )
                return EcosystemMcpSession("mcp-session:cancelled", descriptor.server_id, discovery_path, None, receipt)
            refresh_key = (descriptor.credential_lease_id, descriptor.challenge_digest)
            self._bound_refreshes.add(refresh_key)
            credential = self.refresh(descriptor.credential_lease_id, descriptor.challenge_digest)
            self._bound_refreshes.discard(refresh_key)
            credential_refresh_count += 1
            _send(
                process,
                {
                    "type": "initialize",
                    "server_id": descriptor.server_id,
                    "version": descriptor.version,
                    "credential": credential,
                },
            )
            initialize_count += 1
            initialized = _read(process, deadline, descriptor.max_output_bytes)
            if initialized.get("type") != "initialized" or initialized.get("server_id") != descriptor.server_id:
                raise EcosystemMcpError("MCP fixture failed")
            _send(process, {"type": "list"})
            listed = _read(process, deadline, descriptor.max_output_bytes)
            list_count += 1
            if listed.get("type") != "list_result" or listed.get("tool_count") != 1:
                raise EcosystemMcpError("MCP fixture failed")
            receipt = self._receipt(
                descriptor,
                "succeeded",
                discovery_path,
                credential_refresh_count,
                initialize_count,
                list_count,
            )
            return EcosystemMcpSession("mcp-session:local", descriptor.server_id, discovery_path, process, receipt)
        except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError, BrokenPipeError, TimeoutError, EcosystemMcpError):
            if process is not None:
                self._kill(process)
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
            credential_refresh_count=session.receipt.credential_refresh_count,
            initialize_count=session.receipt.initialize_count,
            list_count=session.receipt.list_count,
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
            credential_refresh_count=credential_refresh_count,
            initialize_count=initialize_count,
            list_count=list_count,
            discovery_digest=_sha256(discovery_path.read_bytes()),
        )

    def _kill(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        _close_streams(process)


def _send(process: subprocess.Popen[str], value: Mapping[str, object]) -> None:
    if process.stdin is None:
        raise EcosystemMcpError("MCP fixture failed")
    process.stdin.write(json.dumps(dict(value), sort_keys=True, separators=(",", ":")) + "\n")
    process.stdin.flush()


def _read(
    process: subprocess.Popen[str],
    deadline: float,
    max_output_bytes: int,
) -> dict[str, object]:
    if process.stdout is None:
        raise EcosystemMcpError("MCP fixture failed")
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not selector.select(remaining):
            raise TimeoutError
        line = process.stdout.readline()
    finally:
        selector.close()
    if len(line.encode("utf-8")) > max_output_bytes:
        raise EcosystemMcpError("MCP fixture failed")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise EcosystemMcpError("MCP fixture failed")
    return value


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _valid_id(value: str) -> bool:
    return bool(value) and all(char in _OPAQUE for char in value)


def _cancelled(cancellation: CancellationSignal | None) -> bool:
    return bool(cancellation is not None and cancellation.cancelled)


def _close_streams(process: subprocess.Popen[str]) -> None:
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            stream.close()
