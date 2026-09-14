"""Runtime-owned native P1 stage machine over narrow host barriers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
import re
from types import MappingProxyType

from asterion.applications.prime.p1.worker import (
    P1Worker,
    P1WorkerCleanupReceipt,
)
from asterion.capabilities.prime_ipython_coding_native.host import (
    P1Finalization,
    P1PendingClassification,
    P1RuntimeHost,
    P1RuntimeHostError,
    P1StageMilestone,
    P1StageTwoRelease,
)
from asterion.capabilities.prime_ipython_coding_native.provider import (
    P1_ARTIFACT_ID,
    P1_INPUT_PRESET,
    P1_RECEIPT_MEDIA_TYPE,
)
from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryError
from asterion.runtime.host import CancellationSignal, RunEvent, RunRequest
from asterion.runtime.protocol import ProtocolError
from asterion.runtimes.asterion_prime import AsterionPrimeRuntimeClient


P1_HOST_CAPABILITIES = (
    "prime.ipython",
    "prime.launch",
    "prime.p1-oracle",
    "prime.private-trace",
    "prime.session-backend",
)
P1_RUNTIME_OPTIONS: Mapping[str, str] = MappingProxyType(
    {
        "aggregate_tokens": "64000",
        "cost_micros": "500000",
        "deadline_ms": "600000",
        "max_callbacks": "8",
        "max_tool_callbacks": "4",
    }
)
_ERROR = "Asterion-prime runtime configuration is invalid"
_BUDGET_MESSAGE = "P1 verification exceeded its fixed budget."
_RECOVERY_MESSAGE = "P1 verification requires operator recovery."
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_AGGREGATE_TOKENS = 64_000
_MAX_COMPACT_RESERVED_TOKENS = 16_000


class _P1BudgetExceeded(Exception):
    pass


class P1WorkerOwnerAdapter:
    """Adapt Task 6's receipt-returning close without discarding its receipt."""

    __slots__ = ("_cleanup", "_identity_sha256", "_lifecycle", "_worker")

    def __init__(self, worker: P1Worker) -> None:
        try:
            identity_sha256 = getattr(worker, "identity_sha256")
            lifecycle = worker.validate_lifecycle()
            if (
                type(identity_sha256) is not str
                or _DIGEST.fullmatch(identity_sha256) is None
                or lifecycle is None
            ):
                raise ValueError
        except Exception:
            raise RuntimeFactoryError(_ERROR) from None
        self._worker = worker
        self._identity_sha256 = identity_sha256
        self._lifecycle = lifecycle
        self._cleanup: P1WorkerCleanupReceipt | None = None

    @property
    def identity_sha256(self) -> str:
        return self._identity_sha256

    @property
    def cleanup_receipt(self) -> P1WorkerCleanupReceipt | None:
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
            cleanup = await self._worker.close()
            if (
                type(cleanup) is not P1WorkerCleanupReceipt
                or self._worker.cleanup_receipt is not cleanup
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


class _P1RuntimeSession:
    """Own exact P1 sequencing and cleanup-gated public terminal projection."""

    __slots__ = ("_active", "_consumed", "_host")

    def __init__(self, host: P1RuntimeHost) -> None:
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
            raise ProtocolError("P1 runtime request is invalid")
        request.to_mapping()
        if self._active or self._consumed:
            raise ProtocolError("P1 runtime session is unavailable")
        if (
            request.input_text != P1_INPUT_PRESET
            or request.requested_capabilities != ("prime.tool.ipython",)
            or request.deadline_ms not in {None, 600_000}
        ):
            raise ProtocolError("P1 runtime request is invalid")
        self._active = self._consumed = True
        public = [
            RunEvent(
                request.run_id,
                1,
                "run.started",
                {"capabilities": ["prime.tool.ipython"]},
            )
        ]
        pending: P1PendingClassification = "completed"
        milestones: list[P1StageMilestone] = []
        aggregate_tokens = 0
        try:
            if signal is not None and signal.cancelled:
                pending = "cancelled"
            else:
                stage_one = await self._host.execute_stage_one(
                    run_id=request.run_id, signal=signal
                )
                self._validate_milestone(stage_one, stage="stage-one")
                await self._host.publish_milestone(
                    run_id=request.run_id, milestone=stage_one
                )
                milestones.append(stage_one)
                aggregate_tokens += stage_one.input_tokens + stage_one.output_tokens
                self._validate_aggregate_tokens(aggregate_tokens)
                release = await self._host.wait_stage_two_release(
                    run_id=request.run_id, stage_one=stage_one, signal=signal
                )
                if type(release) is not P1StageTwoRelease:
                    raise ValueError
                if release.compact_reserved_tokens > _MAX_COMPACT_RESERVED_TOKENS:
                    raise _P1BudgetExceeded
                aggregate_tokens += release.compact_reserved_tokens
                self._validate_aggregate_tokens(aggregate_tokens)
                if signal is not None and signal.cancelled:
                    raise asyncio.CancelledError()
                stage_two = await self._host.execute_stage_two(
                    run_id=request.run_id, release=release, signal=signal
                )
                self._validate_milestone(stage_two, stage="stage-two")
                await self._host.publish_milestone(
                    run_id=request.run_id, milestone=stage_two
                )
                milestones.append(stage_two)
                aggregate_tokens += stage_two.input_tokens + stage_two.output_tokens
                self._validate_aggregate_tokens(aggregate_tokens)
        except _P1BudgetExceeded:
            pending = "budget-limited"
        except P1RuntimeHostError as error:
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
            if type(candidate) is not P1Finalization:
                raise ValueError
            if pending != "completed" and candidate.classification != pending:
                raise ValueError
            finalization = candidate
        except asyncio.CancelledError:
            raise asyncio.CancelledError() from None
        except Exception:
            raise ProtocolError("P1 runtime finalization failed") from None
        finally:
            self._active = False

        classification = finalization.classification
        for milestone in milestones:
            public.append(
                RunEvent(
                    request.run_id,
                    len(public) + 1,
                    "usage.reported",
                    {
                        "input_tokens": milestone.input_tokens,
                        "output_tokens": milestone.output_tokens,
                    },
                )
            )
        if classification == "completed":
            assert finalization.receipt_sha256 is not None
            public.append(
                RunEvent(
                    request.run_id,
                    len(public) + 1,
                    "artifact.created",
                    {
                        "artifact": {
                            "artifact_id": P1_ARTIFACT_ID,
                            "kind": "p1-native",
                            "media_type": P1_RECEIPT_MEDIA_TYPE,
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
                ("p1_budget_limited", _BUDGET_MESSAGE)
                if classification == "budget-limited"
                else ("p1_recovery_required", _RECOVERY_MESSAGE)
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

    @staticmethod
    def _validate_milestone(milestone: object, *, stage: str) -> P1StageMilestone:
        if type(milestone) is not P1StageMilestone or milestone.stage != stage:
            raise ValueError
        return milestone

    @staticmethod
    def _validate_aggregate_tokens(aggregate_tokens: int) -> None:
        if aggregate_tokens > _MAX_AGGREGATE_TOKENS:
            raise _P1BudgetExceeded


def build_p1_runtime(context: RuntimeFactoryContext) -> AsterionPrimeRuntimeClient:
    """Bind exact preflighted P1 services without constructing the coordinator."""

    try:
        if type(context) is not RuntimeFactoryContext:
            raise ValueError
        host_services = context.host_services
        service = host_services.get("prime.session-backend")
        if (
            context.provider_id != "prime-applications"
            or context.application_id != "prime.ipython-coding"
            or context.application_version != "1.0.0"
            or context.runtime_id != "asterion.prime"
            or set(host_services) != set(P1_HOST_CAPABILITIES)
            or any(host_services.get(name) is None for name in P1_HOST_CAPABILITIES)
            or dict(context.options) != dict(P1_RUNTIME_OPTIONS)
            or not isinstance(service, P1RuntimeHost)
        ):
            raise ValueError
        validated = service.validate_runtime_services(
            ipython=host_services["prime.ipython"],
            oracle=host_services["prime.p1-oracle"],
            pi_extension=host_services["prime.launch"],
            private_trace=host_services["prime.private-trace"],
        )
        if validated is not None:
            raise ValueError
        return AsterionPrimeRuntimeClient(_P1RuntimeSession(service))
    except Exception:
        raise RuntimeFactoryError(_ERROR) from None


__all__ = (
    "P1_HOST_CAPABILITIES",
    "P1_RUNTIME_OPTIONS",
    "P1WorkerOwnerAdapter",
    "build_p1_runtime",
)
