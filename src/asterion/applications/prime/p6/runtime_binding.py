"""Adapt one operator-owned P6 candidate workflow to the runtime protocol."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from types import MappingProxyType

from asterion.applications.prime.p6.host import P6RuntimeHost
from asterion.applications.prime.p6.oracle import P6Oracle
from asterion.applications.prime.p6.receipt import (
    P6NativeReceipt,
    seal_p6_native_receipt,
)
from asterion.applications.prime.services import CandidateStoreLoop
from asterion.capabilities.prime_continual_improvement_native.provider import (
    P6_INPUT_PRESET,
    P6_ARTIFACT_ID,
    P6_RECEIPT_MEDIA_TYPE,
)
from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryError
from asterion.runtime.host import CancellationSignal, RunEvent, RunRequest
from asterion.runtime.protocol import ProtocolError
from asterion.runtimes.asterion_prime import AsterionPrimeRuntimeClient

P6_HOST_CAPABILITIES = (
    "prime.candidate-store",
    "prime.p6-oracle",
    "prime.pi-extension",
    "prime.private-trace",
    "prime.session-backend",
)
P6_RUNTIME_OPTIONS: Mapping[str, str] = MappingProxyType(
    {
        "aggregate_tokens": "32000",
        "cost_micros": "300000",
        "deadline_ms": "120000",
        "max_callbacks": "4",
        "max_tool_callbacks": "2",
    }
)
_ERROR = "Asterion-prime runtime configuration is invalid"


class _NeverCancelled:
    cancelled = False


class _P6RuntimeSession:
    def __init__(
        self,
        *,
        session_backend: P6RuntimeHost,
        candidate_store: CandidateStoreLoop,
        oracle: P6Oracle,
        private_trace: object | None,
    ) -> None:
        self._session_backend = session_backend
        self._candidate_store = candidate_store
        self._oracle = oracle
        self._private_trace = private_trace
        self._active = False
        self._consumed = False

    def validate_runtime_services(self, services: Mapping[str, object]) -> None:
        if set(services) != set(P6_HOST_CAPABILITIES):
            raise RuntimeFactoryError(_ERROR)

    async def run_candidate(
        self, *, root_run_id: str, signal: CancellationSignal
    ) -> P6NativeReceipt:
        return await self._session_backend.run_candidate(
            root_run_id=root_run_id, signal=signal
        )

    async def run(
        self, request: RunRequest, *, signal: CancellationSignal | None = None
    ) -> AsyncIterator[RunEvent]:
        if type(request) is not RunRequest:
            raise ProtocolError("P6 runtime request is invalid")
        request.to_mapping()
        if self._active or self._consumed:
            raise ProtocolError("P6 runtime session is unavailable")
        if (
            request.input_text != P6_INPUT_PRESET
            or request.requested_capabilities
            or request.deadline_ms != 120_000
        ):
            raise ProtocolError("P6 runtime request is invalid")
        self._active = self._consumed = True
        signal = signal or _NeverCancelled()
        try:
            yield RunEvent(request.run_id, 1, "run.started", {"capabilities": []})
            if signal.cancelled:
                yield RunEvent(
                    request.run_id, 2, "run.completed", {"status": "cancelled"}
                )
                return
            async with asyncio.timeout(request.deadline_ms / 1000):
                receipt = await self.run_candidate(
                    root_run_id=request.run_id, signal=signal
                )
            if signal.cancelled:
                yield RunEvent(
                    request.run_id, 2, "run.completed", {"status": "cancelled"}
                )
                return
            if (
                type(receipt) is not P6NativeReceipt
                or receipt.root_run_id != request.run_id
                or seal_p6_native_receipt(receipt) != receipt
                or receipt.failure_digest is not None
                or receipt.terminal_outcome != "preserved"
                or receipt.rollback_invocation_count != 0
            ):
                raise ProtocolError("P6 candidate did not complete successfully")
            yield RunEvent(
                request.run_id,
                2,
                "artifact.created",
                {
                    "artifact": {
                        "artifact_id": P6_ARTIFACT_ID,
                        "kind": "p6-native",
                        "media_type": P6_RECEIPT_MEDIA_TYPE,
                        "sha256": receipt.receipt_sha256,
                    }
                },
            )
            yield RunEvent(request.run_id, 3, "run.completed", {"status": "completed"})
        except Exception:
            yield RunEvent(
                request.run_id,
                2,
                "run.failed",
                {
                    "code": "prime_p6_failed",
                    "message": "Prime P6 execution failed.",
                },
            )
        finally:
            self._active = False


def build_p6_runtime(context: RuntimeFactoryContext) -> AsterionPrimeRuntimeClient:
    """Bind the exact candidate store, oracle and operator-owned workflow."""

    try:
        if type(context) is not RuntimeFactoryContext:
            raise ValueError
        host_services = context.host_services
        service = host_services.get("prime.session-backend")
        candidate_store_value = host_services.get("prime.candidate-store")
        oracle_value = host_services.get("prime.p6-oracle")
        # ``prime.private-trace`` has no consumer in P6 (no persistent
        # session to trace), so it is allowed to be None. Every other
        # host service must be a real instance.
        required_host_services = tuple(
            name for name in P6_HOST_CAPABILITIES if name != "prime.private-trace"
        )
        if (
            context.provider_id != "prime-applications"
            or context.application_id != "prime.continual-improvement"
            or context.application_version != "1.0.0"
            or context.runtime_id != "asterion.prime"
            or set(host_services) != set(P6_HOST_CAPABILITIES)
            or any(host_services.get(name) is None for name in required_host_services)
            or dict(context.options) != dict(P6_RUNTIME_OPTIONS)
            or not isinstance(service, P6RuntimeHost)
            or not isinstance(oracle_value, P6Oracle)
            or not isinstance(candidate_store_value, CandidateStoreLoop)
        ):
            raise ValueError
        session = _P6RuntimeSession(
            session_backend=service,
            candidate_store=candidate_store_value,
            oracle=oracle_value,
            private_trace=host_services.get("prime.private-trace"),
        )
        # Eagerly validate the 5-tuple so a malformed host-services
        # shape is rejected before the runtime is handed to callers.
        session.validate_runtime_services(host_services)
        service.validate_runtime_services(host_services)
        return AsterionPrimeRuntimeClient(session)
    except Exception:
        raise RuntimeFactoryError(_ERROR) from None
