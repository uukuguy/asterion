"""Runtime-owned native P4 cross-generation session.

P4 owns one bounded commit-or-recover round per invocation. The runtime
drives the call against the injected host; the host owns the cross-process
state. The P2 adapter pattern is reused for the worker lease: a small
``P4WorkerOwnerAdapter`` adapts the worker's close without discarding its
receipt.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from types import MappingProxyType

from asterion.applications.prime.p4.host import (
    P4CommitCall,
    P4CommitReceipt,
    P4Finalization,
    P4PendingClassification,
    P4RuntimeHost,
    P4RuntimeHostError,
)
from asterion.applications.prime.services import ContinuityStoreHostService
from asterion.applications.prime.p4.worker import (
    P4DeterministicWorker,
    P4WorkerCleanupReceipt,
)
from asterion.capabilities.prime_long_session_continuity_native.provider import (
    P4_ARTIFACT_ID,
    P4_INPUT_PRESET,
    P4_RECEIPT_MEDIA_TYPE,
)
from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryError
from asterion.runtime.host import CancellationSignal, RunEvent, RunRequest
from asterion.runtime.protocol import ProtocolError
from asterion.runtimes.asterion_prime import AsterionPrimeRuntimeClient


# P4's host capabilities: per spec L115 the application depends on
# ``prime.continuity-store`` (new for Phase 6), ``prime.p4-oracle``, and
# the same Asterion-owned substrate P2 already consumes.
P4_HOST_CAPABILITIES = (
    "prime.continuity-store",
    "prime.p4-oracle",
    "prime.pi-extension",
    "prime.private-trace",
    "prime.session-backend",
)
P4_RUNTIME_OPTIONS: Mapping[str, str] = MappingProxyType(
    {
        "aggregate_tokens": "32000",
        "cost_micros": "300000",
        "deadline_ms": "120000",
        "max_callbacks": "4",
        "max_tool_callbacks": "2",
    }
)
_ERROR = "Asterion-prime runtime configuration is invalid"
_BUDGET_MESSAGE = "P4 continuity exceeded its fixed budget."
_RECOVERY_MESSAGE = "P4 continuity requires operator recovery."
_MAX_AGGREGATE_TOKENS = 32_000


class _P4BudgetExceeded(Exception):
    pass


class P4WorkerOwnerAdapter:
    """Adapt the deterministic worker's close without discarding its receipt."""

    __slots__ = ("_cleanup", "_identity_sha256", "_lifecycle", "_worker")

    def __init__(self, worker: P4DeterministicWorker) -> None:
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
        self._cleanup: P4WorkerCleanupReceipt | None = None

    @property
    def identity_sha256(self) -> str:
        return self._identity_sha256

    @property
    def cleanup_receipt(self) -> P4WorkerCleanupReceipt | None:
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
                type(cleanup) is not P4WorkerCleanupReceipt
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


class _P4RuntimeSession:
    """Own one bounded commit-or-recover round and project cleanup-gated terminal events."""

    __slots__ = ("_active", "_consumed", "_host", "_mode")

    def __init__(self, host: P4RuntimeHost, mode: str) -> None:
        self._host = host
        self._active = False
        self._consumed = False
        self._mode = mode

    async def run(
        self,
        request: RunRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> AsyncIterator[RunEvent]:
        if type(request) is not RunRequest:
            raise ProtocolError("P4 runtime request is invalid")
        request.to_mapping()
        if self._active or self._consumed:
            raise ProtocolError("P4 runtime session is unavailable")
        if (
            request.input_text != P4_INPUT_PRESET
            or request.requested_capabilities != ("prime.tool.ipython",)
            or request.deadline_ms not in {None, 120_000}
            or self._mode not in {"commit", "recover"}
        ):
            raise ProtocolError("P4 runtime request is invalid")
        self._active = self._consumed = True
        public: list[RunEvent] = [
            RunEvent(
                request.run_id,
                1,
                "run.started",
                {"capabilities": ["prime.tool.ipython"], "mode": self._mode},
            )
        ]
        pending: P4PendingClassification = "completed"
        aggregate_tokens = 0
        try:
            if signal is not None and signal.cancelled:
                pending = "cancelled"
            else:
                if self._mode == "commit":
                    call = P4CommitCall(
                        call_id="p4-commit-1",
                        prior_checkpoint_sha256=None,
                        continuation_id="<injected>",
                        generation=1,
                    )
                else:
                    recovered = await self._host.wait_recovery(
                        run_id=request.run_id, signal=signal
                    )
                    call = P4CommitCall(
                        call_id="p4-commit-1",
                        prior_checkpoint_sha256=(
                            None
                            if recovered is None
                            else recovered.prior_checkpoint_sha256
                        ),
                        continuation_id="<injected>",
                        generation=(
                            (recovered.prior_generation + 1)
                            if recovered is not None
                            else 2
                        ),
                    )
                receipt = await self._host.commit_checkpoint(
                    run_id=request.run_id, call=call, signal=signal
                )
                if type(receipt) is not P4CommitReceipt:
                    raise ValueError
                aggregate_tokens += receipt.bytes_returned
                if aggregate_tokens > _MAX_AGGREGATE_TOKENS:
                    raise _P4BudgetExceeded
        except _P4BudgetExceeded:
            pending = "budget-limited"
        except P4RuntimeHostError as error:
            pending = error.classification
        except asyncio.CancelledError:
            pending = "cancelled"
        except Exception:
            pending = "recovery-required"

        try:
            await self._host.report_recovery_stopped(
                run_id=request.run_id, pending_classification=pending
            )
            candidate = await self._host.wait_finalization(
                run_id=request.run_id, signal=signal
            )
            if type(candidate) is not P4Finalization:
                raise ValueError
            if pending != "completed" and candidate.classification != pending:
                raise ValueError
            finalization = candidate
        except asyncio.CancelledError:
            raise asyncio.CancelledError() from None
        except Exception:
            raise ProtocolError("P4 runtime finalization failed") from None
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
                            "artifact_id": P4_ARTIFACT_ID,
                            "kind": "p4-native",
                            "media_type": P4_RECEIPT_MEDIA_TYPE,
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
                ("p4_budget_limited", _BUDGET_MESSAGE)
                if classification == "budget-limited"
                else ("p4_recovery_required", _RECOVERY_MESSAGE)
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


def build_p4_runtime(context: RuntimeFactoryContext) -> AsterionPrimeRuntimeClient:
    """Bind exact preflighted P4 services without constructing the coordinator."""

    try:
        if type(context) is not RuntimeFactoryContext:
            raise ValueError
        host_services = context.host_services
        service = host_services.get("prime.session-backend")
        continuity_store = host_services.get("prime.continuity-store")
        required_host_services = tuple(
            name
            for name in P4_HOST_CAPABILITIES
            if name not in {"prime.private-trace", "prime.continuity-store"}
        )
        if (
            context.provider_id != "prime-applications"
            or context.application_id != "prime.long-session-continuity"
            or context.application_version != "1.0.0"
            or context.runtime_id != "asterion.prime"
            or set(host_services) != set(P4_HOST_CAPABILITIES)
            or any(
                host_services.get(name) is None
                for name in required_host_services
            )
            or continuity_store is None
            or not isinstance(continuity_store, ContinuityStoreHostService)
            or dict(context.options) != dict(P4_RUNTIME_OPTIONS)
            or not isinstance(service, P4RuntimeHost)
        ):
            raise ValueError
        mode = context.options.get("mode", "commit")
        validated = service.validate_runtime_services(  # type: ignore[attr-defined]
            continuity_store=continuity_store,
            oracle=host_services["prime.p4-oracle"],
            extension=host_services["prime.pi-extension"],
            private_trace=host_services.get("prime.private-trace"),
            session_backend=host_services["prime.session-backend"],
        )
        if validated is not None:
            raise ValueError
        return AsterionPrimeRuntimeClient(_P4RuntimeSession(service, mode))
    except Exception:
        raise RuntimeFactoryError(_ERROR) from None


__all__ = (
    "P4_HOST_CAPABILITIES",
    "P4_RUNTIME_OPTIONS",
    "P4WorkerOwnerAdapter",
    "build_p4_runtime",
)