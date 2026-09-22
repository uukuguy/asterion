"""Runtime-owned native P3 recursive-workflow session.

P3 owns one bounded root-or-refused round per invocation. The runtime
drives the call against the injected host; the host owns the
cross-process state. There is no continuity store, no checkpoint seal,
and no recovery semantics on this path — those belong to P4 and are not
part of P3's contract. The session adapter carries the five
host-service references through to the ``P3RuntimeHost`` Protocol
surface that the operator exercises against a built runtime.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from types import MappingProxyType

from asterion.applications.prime.p3.host import (
    P3AdmissionRefused,
    P3ChildRequest,
    P3Finalization,
    P3RootCall,
    P3RootResult,
    P3RuntimeHost,
)
from asterion.applications.prime.p3.oracle import P3Oracle
from asterion.applications.prime.p3.receipt import seal as seal_receipt
from asterion.applications.prime.services import ChildRunnerHostService
from asterion.capabilities.prime_recursive_workflow_native.provider import (
    P3_ARTIFACT_ID,
    P3_INPUT_PRESET,
    P3_RECEIPT_MEDIA_TYPE,
)
from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryError
from asterion.runtime.host import CancellationSignal, RunEvent, RunRequest
from asterion.runtime.protocol import ProtocolError
from asterion.runtimes.asterion_prime import AsterionPrimeRuntimeClient


# P3's host capabilities: per the application assembly JSON
# (``src/asterion/applications/prime/assemblies/prime-recursive-workflow.json``)
# P3 depends on these five injected host services. The spec lists
# ``prime.child-runner`` as the new Phase 7 service and the other four as
# the same Asterion-owned substrate P1 / P2 / P4 already consume. P3 has
# no continuity store — that surface belongs to P4 only.
P3_HOST_CAPABILITIES: tuple[str, ...] = (
    "prime.child-runner",
    "prime.p3-oracle",
    "prime.pi-extension",
    "prime.private-trace",
    "prime.session-backend",
)
P3_RUNTIME_OPTIONS: Mapping[str, str] = MappingProxyType(
    {
        "aggregate_tokens": "16000",
        "cost_micros": "100000",
        "deadline_ms": "60000",
        "max_callbacks": "4",
        "max_tool_callbacks": "2",
    }
)
_ERROR = "Asterion-prime runtime configuration is invalid"


class _NeverCancelled:
    @property
    def cancelled(self) -> bool:
        return False


class _P3RuntimeSession:
    """Own one bounded root-or-refused round and adapt to P3RuntimeHost.

    Implements the four-method ``P3RuntimeHost`` Protocol
    (``validate_runtime_services`` / ``run_root`` /
    ``report_admission_refused`` / ``wait_finalization``) over the
    five injected host services, and exposes the runtime-client
    ``run`` iterator that drives one round per ``RunRequest``.
    """

    __slots__ = (
        "_active",
        "_child_runner",
        "_consumed",
        "_oracle",
        "_private_trace",
        "_session_backend",
    )

    def __init__(
        self,
        *,
        session_backend: P3RuntimeHost,
        child_runner: ChildRunnerHostService,
        oracle: P3Oracle,
        private_trace: object | None,
    ) -> None:
        self._session_backend = session_backend
        self._child_runner = child_runner
        self._oracle = oracle
        self._private_trace = private_trace
        self._active = False
        self._consumed = False

    # ------------------------------------------------------------------
    # P3RuntimeHost Protocol surface
    # ------------------------------------------------------------------

    def validate_runtime_services(
        self, services: Mapping[str, object]
    ) -> None:
        """Reject unknown or missing host services — fail closed.

        ``services`` must equal ``P3_HOST_CAPABILITIES`` exactly (set
        equality; ordering is the spec's contract).
        """

        if set(services) != set(P3_HOST_CAPABILITIES):
            raise RuntimeFactoryError(_ERROR)

    async def run_root(
        self,
        *,
        parent_run_id: str,
        child_request: P3ChildRequest | None,
        signal: CancellationSignal,
    ) -> P3RootResult:
        """Drive session_backend → child_runner → oracle and return the join."""

        call = P3RootCall(
            parent_run_id=parent_run_id,
            child_request=child_request,
        )
        return await self._session_backend.run_root(
            parent_run_id=call.parent_run_id,
            child_request=call.child_request,
            signal=signal,
        )

    def report_admission_refused(
        self,
        *,
        refusal: P3AdmissionRefused,
    ) -> None:
        """Forward a closed-enum refusal to the host's observability surface."""

        self._session_backend.report_admission_refused(refusal=refusal)

    async def wait_finalization(
        self, *, signal: CancellationSignal
    ) -> P3Finalization:
        """Block until the host transfers terminal status."""

        return await self._session_backend.wait_finalization(signal=signal)

    # ------------------------------------------------------------------
    # Runtime-client session interface
    # ------------------------------------------------------------------

    async def run(
        self,
        request: RunRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> AsyncIterator[RunEvent]:
        if type(request) is not RunRequest:
            raise ProtocolError("P3 runtime request is invalid")
        request.to_mapping()
        if self._active or self._consumed:
            raise ProtocolError("P3 runtime session is unavailable")
        if (
            request.input_text != P3_INPUT_PRESET
            or request.requested_capabilities != ()
            or request.deadline_ms not in {None, 60_000}
        ):
            raise ProtocolError("P3 runtime request is invalid")
        self._active = self._consumed = True
        try:
            yield RunEvent(request.run_id, 1, "run.started", {"capabilities": []})
            if signal is not None and signal.cancelled:
                yield RunEvent(
                    request.run_id, 2, "run.completed", {"status": "cancelled"}
                )
                return
            active_signal = signal if signal is not None else _NeverCancelled()
            root = await self.run_root(
                parent_run_id=request.run_id,
                child_request=None,
                signal=active_signal,
            )
            final = await self.wait_finalization(signal=active_signal)
            if (
                type(root) is not P3RootResult
                or root.root_run_id != request.run_id
                or root.depth_reached != 2
                or root.refusal_reason is not None
                or type(final) is not P3Finalization
                or final.terminal_status != "completed"
            ):
                raise ProtocolError("P3 runtime result is invalid")
            self._oracle.check(
                root_run_id=root.root_run_id,
                root_generation=root.root_generation,
                child_run_id=root.child_run_id,
                child_generation=root.child_generation,
                child_result_sha256=root.child_result_sha256,
                joined_result_sha256=root.joined_result_sha256,
                depth_reached=root.depth_reached,
                refusal_reason=root.refusal_reason,
            )
            receipt = seal_receipt(
                root_run_id=root.root_run_id,
                root_generation=root.root_generation,
                child_run_id=root.child_run_id,
                child_generation=root.child_generation,
                child_result_sha256=root.child_result_sha256,
                joined_result_sha256=root.joined_result_sha256,
                depth_reached=root.depth_reached,
                refusal_reason=root.refusal_reason,
            )
            if final.receipt_sha256 != receipt.sha256():
                raise ProtocolError("P3 runtime receipt mismatches finalization")
            yield RunEvent(
                request.run_id, 2, "artifact.created",
                {"artifact": {
                    "artifact_id": P3_ARTIFACT_ID,
                    "kind": "p3-native",
                    "media_type": P3_RECEIPT_MEDIA_TYPE,
                    "sha256": receipt.sha256(),
                }},
            )
            yield RunEvent(request.run_id, 3, "run.completed", {"status": "completed"})
        except asyncio.CancelledError:
            raise
        finally:
            self._active = False


def build_p3_runtime(context: RuntimeFactoryContext) -> AsterionPrimeRuntimeClient:
    """Bind exact preflighted P3 services without constructing the coordinator."""

    try:
        if type(context) is not RuntimeFactoryContext:
            raise ValueError
        host_services = context.host_services
        service = host_services.get("prime.session-backend")
        child_runner_value = host_services.get("prime.child-runner")
        oracle_value = host_services.get("prime.p3-oracle")
        # prime.private-trace has no consumer in P3 (no persistent
        # session to trace), so it is allowed to be None. Every other
        # host service must be a real instance.
        required_host_services = tuple(
            name
            for name in P3_HOST_CAPABILITIES
            if name != "prime.private-trace"
        )
        if (
            context.provider_id != "prime-applications"
            or context.application_id != "prime.recursive-workflow"
            or context.application_version != "1.0.0"
            or context.runtime_id != "asterion.prime"
            or set(host_services) != set(P3_HOST_CAPABILITIES)
            or any(
                host_services.get(name) is None
                for name in required_host_services
            )
            or dict(context.options) != dict(P3_RUNTIME_OPTIONS)
            or not isinstance(service, P3RuntimeHost)
            or not isinstance(child_runner_value, ChildRunnerHostService)
            or not isinstance(oracle_value, P3Oracle)
        ):
            raise ValueError
        session = _P3RuntimeSession(
            session_backend=service,
            child_runner=child_runner_value,
            oracle=oracle_value,
            private_trace=host_services.get("prime.private-trace"),
        )
        # Eagerly validate the 5-tuple so a malformed host-services
        # shape is rejected before the runtime is handed to callers.
        session.validate_runtime_services(host_services)
        return AsterionPrimeRuntimeClient(session)
    except Exception:
        raise RuntimeFactoryError(_ERROR) from None


__all__ = (
    "P3_HOST_CAPABILITIES",
    "P3_RUNTIME_OPTIONS",
    "build_p3_runtime",
)
