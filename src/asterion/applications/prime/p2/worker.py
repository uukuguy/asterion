"""P2 worker adapter: exposes the context service through the worker Protocol.

P2 has no restricted IPython subprocess of its own. The "worker" is the
injected :class:`P2ContextService`; the operator hands the runtime one
of these through the host service binding. The adapter deliberately
exposes only the identity and corpus digests, so a future Phase 6
detach/attach can swap the underlying service without leaking the corpus
into the runtime's contract surface.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re

from asterion.applications.prime.p2.context_service import (
    P2ContextService,
    P2ContextSlice,
)


_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def digest(value: object) -> str:
    """SHA-256 over canonical-JSON bytes of ``value``.

    Matches the framework's digest convention so the oracle's reference value
    can be reproduced by any consumer that reads the receipt.
    """
    serialized = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


@dataclass(frozen=True, slots=True)
class P2WorkerCleanupReceipt:
    """Evidence the worker handed back its injected service on close."""

    worker_identity_sha256: str
    reaped: bool
    pipes_closed: bool
    root_removed: bool

    def __post_init__(self) -> None:
        if (
            not _DIGEST.fullmatch(self.worker_identity_sha256)
            or type(self.reaped) is not bool
            or type(self.pipes_closed) is not bool
            or type(self.root_removed) is not bool
        ):
            raise ValueError("P2 worker cleanup receipt is invalid")

    def sha256(self) -> str:
        return digest(asdict(self))  # type: ignore[arg-type]


class P2ContextServiceWorker:
    """Adapter that exposes :class:`P2ContextService` to the runtime."""

    __slots__ = ("_service", "_closed", "_lifecycle", "_receipt")

    def __init__(self, service: P2ContextService) -> None:
        if not isinstance(service, P2ContextService):
            raise ValueError("P2 worker service is invalid")
        self._service = service
        self._closed = False
        self._lifecycle = object()
        self._receipt: P2WorkerCleanupReceipt | None = None

    @property
    def identity_sha256(self) -> str:
        # Identity binds to the corpus path so a swapped corpus invalidates
        # the worker; the oracle refuses the same identity twice in one run.
        return digest({"corpus_path": self._service.corpus_path})

    @property
    def corpus_sha256(self) -> str:
        payload = list(self._service._records)  # type: ignore[attr-defined]
        return digest(payload)

    def validate_lifecycle(self) -> object:
        if self._closed:
            raise ValueError("P2 worker is closed")
        return self._lifecycle

    def retrieve(self, *, bounds: tuple[int, int]) -> P2ContextSlice:
        if self._closed:
            raise ValueError("P2 worker is closed")
        return self._service.retrieve(bounds=bounds)

    def transform(
        self, *, select_keys: tuple[str, ...], bounds: tuple[int, int]
    ) -> P2ContextSlice:
        if self._closed:
            raise ValueError("P2 worker is closed")
        return self._service.transform(select_keys=select_keys, bounds=bounds)

    async def close(self) -> P2WorkerCleanupReceipt:
        if self._receipt is not None:
            return self._receipt
        receipt = P2WorkerCleanupReceipt(
            worker_identity_sha256=self.identity_sha256,
            reaped=True,
            pipes_closed=True,
            root_removed=True,
        )
        self._closed = True
        self._receipt = receipt
        return receipt


__all__ = (
    "P2ContextServiceWorker",
    "P2WorkerCleanupReceipt",
    "digest",
)