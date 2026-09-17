"""Runtime-owned native P2 stage machine over narrow host barriers.

P2 is one bounded retrieval/transform round-trip inside a single host.
The runtime owns the call; the operator's injected service owns the
bytes. Bounds are dictated by the task module so the unit test and the
live preset use the same tuple.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from types import MappingProxyType

from asterion.applications.prime.p2.worker import (
    P2ContextServiceWorker,
    P2WorkerCleanupReceipt,
)
from asterion.capabilities.prime_programmatic_long_context_native.host import (
    P2Finalization,
    P2PendingClassification,
    P2RetrievalCall,
    P2RetrievalReceipt,
    P2RuntimeHost,
    P2RuntimeHostError,
)
from asterion.capabilities.prime_programmatic_long_context_native.provider import (
    P2_ARTIFACT_ID,
    P2_INPUT_PRESET,
    P2_RECEIPT_MEDIA_TYPE,
)
from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryError
from asterion.runtime.host import CancellationSignal, RunEvent, RunRequest
from asterion.runtime.protocol import ProtocolError
from asterion.runtimes.asterion_prime import AsterionPrimeRuntimeClient


# P2's host capabilities: the spec lists ``prime.p2-oracle`` as a distinct
# service name (not an alias of ``prime.ipython``), so Phase 6's detach /
# attach can target it independently of the IPython worker. ``prime.pi-extension``
# is the spec's literal name for the Asterion-owned extension lease; P1
# aliases this to ``prime.launch`` in its own assembly but the spec table
# is authoritative.
P2_HOST_CAPABILITIES = (
    "prime.ipython",
    "prime.p2-oracle",
    "prime.pi-extension",
    "prime.private-trace",
    "prime.session-backend",
)
P2_RUNTIME_OPTIONS: Mapping[str, str] = MappingProxyType(
    {
        "aggregate_tokens": "64000",
        "cost_micros": "500000",
        "deadline_ms": "600000",
        "max_callbacks": "8",
        "max_tool_callbacks": "4",
    }
)
_ERROR = "Asterion-prime runtime configuration is invalid"
_BUDGET_MESSAGE = "P2 verification exceeded its fixed budget."
_RECOVERY_MESSAGE = "P2 verification requires operator recovery."
_MAX_AGGREGATE_TOKENS = 64_000


class _P2BudgetExceeded(Exception):
    pass


class P2WorkerOwnerAdapter:
    """Adapt the worker's close without discarding its receipt."""

    __slots__ = ("_cleanup", "_identity_sha256", "_lifecycle", "_worker")

    def __init__(self, worker: P2ContextServiceWorker) -> None:
        try:
            identity_sha256 = getattr(worker, "identity_sha256")
            lifecycle = worker.validate_lifecycle()
            if (
                type(identity_sha256) is not str
                or len(identity_sha256) != 64
                or lifecycle is None
            ):
                raise ValueError
        except Exception:
            raise RuntimeFactoryError(_ERROR) from None
        self._worker = worker
        self._identity_sha256 = identity_sha256
        self._lifecycle = lifecycle
        self._cleanup: P2WorkerCleanupReceipt | None = None

    @property
    def identity_sha256(self) -> str:
        return self._identity_sha256

    @property
    def cleanup_receipt(self) -> P2WorkerCleanupReceipt | None:
        return self._cleanup

    def validate_lifecycle(self) -> object:
        try:
            current = self._worker.validate_lifecycle()
            if (
                current is not self._lifecycle
                or getattr(self._worker, "identity_sha256") != self._identity_sha256
            ):
                raise ValueError
        except Exception:
            raise RuntimeFactoryError(_ERROR) from None
        return self._lifecycle

    async def close(self) -> None:
        if self._cleanup is not None:
            return
        try:
            pre_close_lifecycle = self._worker.validate_lifecycle()
            cleanup = await self._worker.close()
            if (
                type(cleanup) is not P2WorkerCleanupReceipt
                or pre_close_lifecycle is not self._lifecycle
                or cleanup.worker_identity_sha256 != self._identity_sha256
                or not cleanup.reaped
                or not cleanup.pipes_closed
                or not cleanup.root_removed
            ):
                raise ValueError
        except asyncio.CancelledError:
            raise asyncio.CancelledError() from None
        except Exception:
            raise RuntimeFactoryError(_ERROR) from None
        self._cleanup = cleanup


class _P2RuntimeSession:
    """Own exact P2 sequencing and cleanup-gated public terminal projection."""

    __slots__ = ("_active", "_consumed", "_host")

    def __init__(self, host: P2RuntimeHost) -> None:
        self._host = host
        self._active = False
        self._consumed = False

    async def run(
        self,
        request: RunRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> AsyncIterator[RunEvent]:
        if type(request) is not RunRequest:
            raise ProtocolError("P2 runtime request is invalid")
        request.to_mapping()
        if self._active or self._consumed:
            raise ProtocolError("P2 runtime session is unavailable")
        if (
            request.input_text != P2_INPUT_PRESET
            or request.requested_capabilities != ("prime.tool.ipython",)
            or request.deadline_ms not in {None, 600_000}
        ):
            raise ProtocolError("P2 runtime request is invalid")
        self._active = self._consumed = True
        public: list[RunEvent] = [
            RunEvent(
                request.run_id,
                1,
                "run.started",
                {"capabilities": ["prime.tool.ipython"]},
            )
        ]
        pending: P2PendingClassification = "completed"
        aggregate_tokens = 0
        try:
            if signal is not None and signal.cancelled:
                pending = "cancelled"
            else:
                call = P2RetrievalCall(
                    call_id="p2-call-1",
                    operation="retrieve",
                    corpus_path="<injected>",
                    query="<injected>",
                    bounds=(0, 1),
                )
                receipt = await self._host.execute_retrieval(
                    run_id=request.run_id, call=call, signal=signal
                )
                if type(receipt) is not P2RetrievalReceipt:
                    raise ValueError
                aggregate_tokens += receipt.input_tokens + receipt.output_tokens
                if aggregate_tokens > _MAX_AGGREGATE_TOKENS:
                    raise _P2BudgetExceeded
        except _P2BudgetExceeded:
            pending = "budget-limited"
        except P2RuntimeHostError as error:
            pending = error.classification
        except asyncio.CancelledError:
            pending = "cancelled"
        except Exception:
            pending = "recovery-required"

        try:
            await self._host.report_execution_stopped(
                run_id=request.run_id, pending_classification=pending
            )
            candidate = await self._host.wait_finalization(
                run_id=request.run_id, signal=signal
            )
            if type(candidate) is not P2Finalization:
                raise ValueError
            if pending != "completed" and candidate.classification != pending:
                raise ValueError
            finalization = candidate
        except asyncio.CancelledError:
            raise asyncio.CancelledError() from None
        except Exception:
            raise ProtocolError("P2 runtime finalization failed") from None
        finally:
            self._active = False

        classification = finalization.classification
        if classification == "completed":
            assert finalization.receipt_sha256 is not None
            public.append(
                RunEvent(
                    request.run_id,
                    len(public) + 1,
                    "usage.reported",
                    {
                        "input_tokens": aggregate_tokens,
                        "output_tokens": 0,
                    },
                )
            )
            public.append(
                RunEvent(
                    request.run_id,
                    len(public) + 1,
                    "artifact.created",
                    {
                        "artifact": {
                            "artifact_id": P2_ARTIFACT_ID,
                            "kind": "p2-native",
                            "media_type": P2_RECEIPT_MEDIA_TYPE,
                            "sha256": finalization.receipt_sha256,
                        }
                    },
                )
            )
            public.append(
                RunEvent(
                    request.run_id,
                    len(public) + 1,
                    "run.completed",
                    {"status": "completed"},
                )
            )
        elif classification == "cancelled":
            public.append(
                RunEvent(
                    request.run_id,
                    len(public) + 1,
                    "run.completed",
                    {"status": "cancelled"},
                )
            )
        else:
            code, message = (
                ("p2_budget_limited", _BUDGET_MESSAGE)
                if classification == "budget-limited"
                else ("p2_recovery_required", _RECOVERY_MESSAGE)
            )
            public.append(
                RunEvent(
                    request.run_id,
                    len(public) + 1,
                    "run.failed",
                    {"code": code, "message": message},
                )
            )
        for event in public:
            yield event


def build_p2_runtime(context: RuntimeFactoryContext) -> AsterionPrimeRuntimeClient:
    """Bind exact preflighted P2 services without constructing the coordinator."""

    try:
        if type(context) is not RuntimeFactoryContext:
            raise ValueError
        host_services = context.host_services
        service = host_services.get("prime.session-backend")
        # prime.private-trace has no consumer in P2 (no persistent session
        # to trace), so it is allowed to be None. Every other host service
        # must be a real instance.
        required_host_services = tuple(
            name for name in P2_HOST_CAPABILITIES if name != "prime.private-trace"
        )
        if (
            context.provider_id != "prime-applications"
            or context.application_id != "prime.programmatic-long-context"
            or context.application_version != "1.0.0"
            or context.runtime_id != "asterion.prime"
            or set(host_services) != set(P2_HOST_CAPABILITIES)
            or any(
                host_services.get(name) is None
                for name in required_host_services
            )
            or dict(context.options) != dict(P2_RUNTIME_OPTIONS)
            or not isinstance(service, P2RuntimeHost)
        ):
            raise ValueError
        validated = service.validate_runtime_services(
            ipython=host_services["prime.ipython"],
            oracle=host_services["prime.p2-oracle"],
            extension=host_services["prime.pi-extension"],
            private_trace=host_services.get("prime.private-trace"),
        )
        if validated is not None:
            raise ValueError
        return AsterionPrimeRuntimeClient(_P2RuntimeSession(service))
    except Exception:
        raise RuntimeFactoryError(_ERROR) from None


__all__ = (
    "P2_HOST_CAPABILITIES",
    "P2_RUNTIME_OPTIONS",
    "P2WorkerOwnerAdapter",
    "build_p2_runtime",
)