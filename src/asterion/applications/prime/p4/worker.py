"""Deterministic fake-worker for native P4 long-session-continuity.

Mirrors the P2 ``P2ContextServiceWorker`` shape exactly so the existing
runtime-binding harness compiles without changes. The worker holds no Pi
subprocess; it returns a deterministic payload whose SHA differs between
commit and recover modes so the no-replay witness is meaningful by
construction.
"""

from __future__ import annotations

import hashlib
from types import MappingProxyType
from typing import Mapping

from asterion.applications.prime.p4.host import P4PendingClassification


class P4WorkerCleanupReceipt:
    """Frozen cleanup receipt returned by ``close``."""

    __slots__ = (
        "worker_identity_sha256",
        "pipes_closed",
        "reaped",
        "root_removed",
    )

    def __init__(
        self,
        worker_identity_sha256: str,
        pipes_closed: bool,
        reaped: bool,
        root_removed: bool,
    ) -> None:
        object.__setattr__(self, "worker_identity_sha256", worker_identity_sha256)
        object.__setattr__(self, "pipes_closed", pipes_closed)
        object.__setattr__(self, "reaped", reaped)
        object.__setattr__(self, "root_removed", root_removed)
        if (
            type(worker_identity_sha256) is not str
            or len(worker_identity_sha256) != 64
            or pipes_closed is not True
            or reaped is not True
            or root_removed is not True
        ):
            raise ValueError("P4 worker cleanup receipt is invalid")

    def to_mapping(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "worker_identity_sha256": self.worker_identity_sha256,
                "pipes_closed": self.pipes_closed,
                "reaped": self.reaped,
                "root_removed": self.root_removed,
            }
        )

    def __eq__(self, other: object) -> bool:
        return (
            type(other) is P4WorkerCleanupReceipt
            and self.worker_identity_sha256 == other.worker_identity_sha256
            and self.pipes_closed == other.pipes_closed
            and self.reaped == other.reaped
            and self.root_removed == other.root_removed
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.worker_identity_sha256,
                self.pipes_closed,
                self.reaped,
                self.root_removed,
            )
        )

    def __repr__(self) -> str:
        return (
            "P4WorkerCleanupReceipt("
            f"worker_identity_sha256={self.worker_identity_sha256!r}, "
            f"pipes_closed={self.pipes_closed!r}, reaped={self.reaped!r}, "
            f"root_removed={self.root_removed!r})"
        )


_WORKER_MODE_PAYLOADS: Mapping[str, str] = MappingProxyType(
    {
        "commit": "p4-commit-payload",
        "recover": "p4-recover-payload",
    }
)


class P4DeterministicWorker:
    """Deterministic fake-worker that yields a mode-distinguishable payload SHA."""

    __slots__ = ("_closed", "_identity_sha256", "_mode")

    def __init__(self, mode: str) -> None:
        if mode not in {"commit", "recover"}:
            raise ValueError("P4 worker mode is invalid")
        self._mode = mode
        self._closed = False
        self._identity_sha256 = hashlib.sha256(
            f"p4-deterministic-{mode}".encode("utf-8")
        ).hexdigest()

    @property
    def identity_sha256(self) -> str:
        return self._identity_sha256

    @property
    def payload_sha256(self) -> str:
        return hashlib.sha256(
            _WORKER_MODE_PAYLOADS[self._mode].encode("utf-8")
        ).hexdigest()

    @property
    def bytes_returned(self) -> int:
        return len(_WORKER_MODE_PAYLOADS[self._mode].encode("utf-8"))

    def validate_lifecycle(self) -> object:
        # A single sentinel object is enough: the owner adapter compares by
        # identity to detect lifecycle drift between calls.
        return ("open",) if not self._closed else ("closed",)

    async def execute(self) -> dict[str, object]:
        if self._closed:
            raise RuntimeError("P4 worker is closed")
        return {
            "mode": self._mode,
            "payload_sha256": self.payload_sha256,
            "bytes_returned": self.bytes_returned,
        }

    async def close(self) -> P4WorkerCleanupReceipt:
        if self._closed:
            raise RuntimeError("P4 worker is already closed")
        self._closed = True
        return P4WorkerCleanupReceipt(
            worker_identity_sha256=self._identity_sha256,
            pipes_closed=True,
            reaped=True,
            root_removed=True,
        )


__all__ = (
    "P4DeterministicWorker",
    "P4WorkerCleanupReceipt",
    "P4PendingClassification",
)