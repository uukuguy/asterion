"""Private immutable values at the P1 worker boundary."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol

CODE_CAP = 16384
OUTPUT_CAP = 65536
WIRE_CAP = 524288
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


class P1WorkerError(RuntimeError):
    """Messages are fixed and carry no upstream exception context."""


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True, repr=False)
class P1CellRequest:
    request_id: str
    turn_id: str
    code: str

    def __post_init__(self) -> None:
        valid = type(self.code) is str
        try:
            valid = valid and 0 < len(self.code.encode("utf-8")) <= CODE_CAP
        except UnicodeError:
            valid = False
        if not valid or any(
            type(item) is not str or _ID.fullmatch(item) is None
            for item in (self.request_id, self.turn_id)
        ):
            raise P1WorkerError("P1 worker request rejected")

    def __repr__(self) -> str:
        return "<P1CellRequest redacted>"


@dataclass(frozen=True, slots=True, repr=False)
class P1WorkerIdentity:
    pid: int
    namespace_nonce: str
    cwd_sha256: str

    def sha256(self) -> str:
        return digest((self.pid, self.namespace_nonce, self.cwd_sha256))


@dataclass(frozen=True, slots=True, repr=False)
class P1CellObservation:
    sequence: int
    request_id: str
    turn_id: str
    code_sha256: str
    status: str
    accumulator_id: int | None
    class_name: str | None
    callable_probe: tuple[int, int] | None
    file_bytes: bytes | None
    file_sha256: str | None
    stage_one_verified: Mapping[str, object] | None
    final_result: int | None
    call_observations: tuple[tuple[int, int, int], ...]
    file_reads: int
    audit_denials: int
    file_read_sha256: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.stage_one_verified is not None:
            object.__setattr__(
                self,
                "stage_one_verified",
                MappingProxyType(dict(self.stage_one_verified)),
            )

    def sha256(self) -> str:
        return digest(
            {
                "sequence": self.sequence,
                "request_id": self.request_id,
                "turn_id": self.turn_id,
                "code_sha256": self.code_sha256,
                "status": self.status,
                "file_sha256": self.file_sha256,
                "state_sha256": digest(
                    (
                        self.accumulator_id,
                        self.class_name,
                        self.callable_probe,
                        dict(self.stage_one_verified)
                        if self.stage_one_verified is not None
                        else None,
                        self.final_result,
                        self.call_observations,
                    )
                ),
                "file_reads": self.file_reads,
                "file_read_sha256": self.file_read_sha256,
                "audit_denials": self.audit_denials,
            }
        )


@dataclass(frozen=True, slots=True)
class P1WorkerCheckpoint:
    worker_identity_sha256: str
    after_sequence: int
    checkpoint_sha256: str
    compact_receipt_sha256: str
    kernel_generation: int
    before_attachment_generation: int
    after_attachment_generation: int
    before_context_tokens: int
    after_context_tokens: int

    def __post_init__(self) -> None:
        hashes = (
            self.worker_identity_sha256,
            self.checkpoint_sha256,
            self.compact_receipt_sha256,
        )
        counters = (
            self.after_sequence,
            self.kernel_generation,
            self.before_attachment_generation,
            self.after_attachment_generation,
            self.before_context_tokens,
            self.after_context_tokens,
        )
        if any(
            type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None
            for value in hashes
        ) or any(type(value) is not int or value < 0 for value in counters):
            raise P1WorkerError("P1 worker checkpoint rejected")
        if (
            self.after_sequence != 2
            or self.kernel_generation < 1
            or self.before_attachment_generation < 1
            or self.after_attachment_generation != self.before_attachment_generation + 1
            or self.after_context_tokens >= self.before_context_tokens
        ):
            raise P1WorkerError("P1 worker checkpoint rejected")


@dataclass(frozen=True, slots=True, repr=False)
class P1InstrumentationSnapshot:
    identity: P1WorkerIdentity
    seeded_symbols: tuple[str, ...]
    cells: tuple[P1CellObservation, ...]
    checkpoint: P1WorkerCheckpoint | None
    authority: object = field(repr=False, compare=False)

    @property
    def pid(self) -> int:
        return self.identity.pid


@dataclass(frozen=True, slots=True, repr=False)
class P1CellReceipt:
    request_id: str
    status: str
    output: str
    effect_sha256: str

    def __repr__(self) -> str:
        return "<P1CellReceipt redacted>"


@dataclass(frozen=True, slots=True)
class P1WorkerCleanupReceipt:
    worker_identity_sha256: str
    last_effect_sha256: str
    reaped: bool
    pipes_closed: bool
    root_removed: bool
    reap_count: int

    def __post_init__(self) -> None:
        if (
            any(
                type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None
                for value in (self.worker_identity_sha256, self.last_effect_sha256)
            )
            or any(
                type(value) is not bool
                for value in (self.reaped, self.pipes_closed, self.root_removed)
            )
            or type(self.reap_count) is not int
            or self.reap_count not in {0, 1}
        ):
            raise P1WorkerError("P1 worker cleanup rejected")

    def sha256(self) -> str:
        return digest(
            (
                self.worker_identity_sha256,
                self.last_effect_sha256,
                self.reaped,
                self.pipes_closed,
                self.root_removed,
                self.reap_count,
            )
        )


class P1Worker(Protocol):
    @property
    def identity(self) -> P1WorkerIdentity: ...

    @property
    def cleanup_receipt(self) -> P1WorkerCleanupReceipt | None: ...

    def validate_lifecycle(self) -> object: ...
    async def start(self) -> None: ...
    async def execute_cell(self, request: P1CellRequest) -> P1CellReceipt: ...
    def snapshot(self) -> P1InstrumentationSnapshot: ...
    async def close(self) -> P1WorkerCleanupReceipt: ...
