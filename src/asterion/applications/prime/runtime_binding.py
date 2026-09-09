"""Provider-owned binding for the source-independent Asterion-prime runtime."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass

from asterion.agents.prime.session import AsterionPrimeSession
from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.applications.prime.p7.broker import ArcBroker, ArcStatus
from asterion.applications.prime.p7.ipython_host import PersistentIpythonHost
from asterion.applications.prime.p7.private_trace import (
    P7PrivateTraceReceipt,
    P7PrivateTraceReceiptError,
)
from asterion.runtime.factory import (
    RuntimeFactoryBinding,
    RuntimeFactoryContext,
    RuntimeFactoryError,
)
from asterion.runtime.host import AgentRuntimeClient, RunEvent, RunRequest
from asterion.runtimes.asterion_prime import AsterionPrimeRuntimeClient
from asterion.runtimes.pi_extensions import PiExtensionBinding, PiExtensionLease
from asterion.runtimes.pi_rpc import PiRpcSession
from asterion.immutable import RedactedImmutableMapping


_HOST_CAPABILITIES = frozenset(
    {
        "prime.arc-broker",
        "prime.ipython",
        "prime.pi-extension",
        "prime.private-trace",
    }
)
_RUNTIME_OPTIONS = {
    "deadline_ms": "3600000",
    "max_actions": "500",
    "max_callbacks": "128",
    "model": "deepseek-v4-flash",
    "provider": "deepseek",
}
_ERROR = "Asterion-prime runtime configuration is invalid"
_RECEIPT_ARTIFACT = "prime.p7-solving.receipt"
_RECEIPT_MEDIA_TYPE = "application/vnd.asterion.prime.p7-solving-receipt+json"


def _p7_level_completed(broker: ArcBroker) -> bool:
    try:
        receipt = broker.seal()
    except Exception:
        return False
    return receipt.levels_completed == 1 and receipt.terminal_reason == "level-completed"


@dataclass(frozen=True, repr=False, slots=True)
class PreflightedPrimeLaunch:
    """Exact already-acquired Pi launch material transferred to one session."""

    rpc_session: PiRpcSession
    extension_binding: PiExtensionBinding
    extension_lease: PiExtensionLease
    approved_command: tuple[str, ...]
    approved_environment: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        lease = self.extension_lease
        if (
            type(self.rpc_session) is not PiRpcSession
            or type(self.extension_binding) is not PiExtensionBinding
            or type(lease) is not PiExtensionLease
            or type(self.approved_command) is not tuple
            or not self.approved_command
            or any(type(part) is not str or not part for part in self.approved_command)
            or lease.closed
            or self.extension_binding.extension_id != "prime.ipython"
            or self.extension_binding.capabilities != ("prime.tool.ipython",)
            or self.extension_binding.binding_fingerprint != lease.binding_fingerprint
            or self.rpc_session.process is not None
            or getattr(self.rpc_session, "_run_active", True)
        ):
            if type(lease) is PiExtensionLease:
                lease.close()
            raise RuntimeFactoryError(_ERROR)
        try:
            environment = (
                dict(lease.environment)
                if self.approved_environment is None
                else dict(self.approved_environment)
            )
        except (TypeError, ValueError):
            lease.close()
            raise RuntimeFactoryError(_ERROR) from None
        if dict(self.rpc_session.config.environment) != environment or any(
            environment.get(name) != value for name, value in lease.environment.items()
        ):
            lease.close()
            raise RuntimeFactoryError(_ERROR)
        object.__setattr__(
            self, "approved_environment", RedactedImmutableMapping(environment)
        )

    def __repr__(self) -> str:
        return "<PreflightedPrimeLaunch redacted>"


def asterion_prime_runtime_binding() -> RuntimeFactoryBinding:
    """Publish the native peer runtime only with this selected provider."""

    return RuntimeFactoryBinding(
        runtime_id="asterion.prime",
        capabilities=("prime.tool.ipython",),
        factory=build_asterion_prime_runtime,
    )


class _P7SolveEventProjector:
    """Project native tool traffic into the fixed P7 receipt-only stream."""

    __slots__ = ("_trace",)

    def __init__(self, trace: P7PrivateTraceReceipt) -> None:
        self._trace = trace

    async def __call__(
        self, request: RunRequest, events: AsyncIterator[RunEvent]
    ) -> AsyncIterator[RunEvent]:
        sequence = 0
        async for event in events:
            if event.type == "run.started":
                sequence += 1
                yield RunEvent(
                    request.run_id, sequence, event.type, event.to_mapping()["payload"]
                )
                continue
            if event.type == "run.failed":
                sequence += 1
                yield RunEvent(
                    request.run_id,
                    sequence,
                    event.type,
                    event.to_mapping()["payload"],
                )
                continue
            if event.type == "usage.reported":
                try:
                    self._trace.record_usage(
                        input_tokens=event.payload["input_tokens"],
                        output_tokens=event.payload["output_tokens"],
                    )
                except (KeyError, P7PrivateTraceReceiptError):
                    sequence += 1
                    yield RunEvent(
                        request.run_id,
                        sequence,
                        "run.failed",
                        {
                            "code": "p7_usage_invalid",
                            "message": "P7 usage evidence is invalid.",
                        },
                    )
                    return
                continue
            if event.type != "run.completed":
                continue
            if event.payload != {"status": "completed"}:
                sequence += 1
                yield RunEvent(
                    request.run_id, sequence, event.type, event.to_mapping()["payload"]
                )
                continue
            try:
                receipt_sha256 = self._trace.expected_receipt_sha256(
                    run_id=request.run_id
                )
            except P7PrivateTraceReceiptError:
                sequence += 1
                yield RunEvent(
                    request.run_id,
                    sequence,
                    "run.failed",
                    {
                        "code": "p7_level_not_completed",
                        "message": "P7 level was not completed.",
                    },
                )
                continue
            sequence += 1
            yield RunEvent(
                request.run_id,
                sequence,
                "artifact.created",
                {
                    "artifact": {
                        "artifact_id": _RECEIPT_ARTIFACT,
                        "kind": "p7-solving",
                        "media_type": _RECEIPT_MEDIA_TYPE,
                        "sha256": receipt_sha256.removeprefix("sha256:"),
                    }
                },
            )
            sequence += 1
            yield RunEvent(
                request.run_id, sequence, event.type, event.to_mapping()["payload"]
            )


def build_asterion_prime_runtime(
    context: RuntimeFactoryContext,
) -> AgentRuntimeClient:
    """Assemble one runtime from exact host-preflighted resources."""

    if type(context) is not RuntimeFactoryContext:
        raise RuntimeFactoryError(_ERROR)
    launch_value = context.host_services.get("prime.pi-extension")
    launch = launch_value if type(launch_value) is PreflightedPrimeLaunch else None
    try:
        ipython = context.host_services.get("prime.ipython")
        broker = context.host_services.get("prime.arc-broker")
        trace_service = context.host_services.get("prime.private-trace")
        trace_adapter = (
            trace_service if type(trace_service) is P7PrivateTraceReceipt else None
        )
        trace = None if trace_adapter is None else trace_adapter.runtime_recorder
        if (
            context.provider_id != "prime-applications"
            or context.application_id != "prime.arc-agi-3-solving"
            or context.application_version != "1.0.0"
            or context.runtime_id != "asterion.prime"
            or set(context.host_services) != _HOST_CAPABILITIES
            or dict(context.options) != _RUNTIME_OPTIONS
            or launch is None
            or type(ipython) is not PersistentIpythonHost
            or getattr(ipython, "_closed", True)
            or getattr(ipython, "_lost", True)
            or type(broker) is not ArcBroker
            or broker.status() != ArcStatus(0, 0, 500, "active")
            or trace_adapter is None
            or trace is None
            or not trace_adapter.matches_runtime_broker(broker)
            or type(trace) is not PrimeTraceRecorder
            or trace._seal is not None
            or trace._trace_fd is None
        ):
            raise RuntimeFactoryError(_ERROR)
        session = AsterionPrimeSession(
            rpc_session=launch.rpc_session,
            extension_binding=launch.extension_binding,
            extension_lease=launch.extension_lease,
            approved_command=launch.approved_command,
            approved_environment=launch.approved_environment,
            completion_predicate=lambda: _p7_level_completed(broker),
        )
        launch = None
        return AsterionPrimeRuntimeClient(
            session, event_projector=_P7SolveEventProjector(trace_adapter)
        )
    except RuntimeFactoryError:
        raise
    except Exception:
        raise RuntimeFactoryError(_ERROR) from None
    finally:
        if launch is not None:
            launch.extension_lease.close()


__all__ = (
    "PreflightedPrimeLaunch",
    "asterion_prime_runtime_binding",
    "build_asterion_prime_runtime",
)
