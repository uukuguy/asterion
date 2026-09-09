"""Provider-owned binding for the source-independent Asterion-prime runtime."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from asterion.agents.prime.session import AsterionPrimeSession
from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.applications.prime.p7.broker import ArcBroker, ArcStatus
from asterion.applications.prime.p7.ipython_host import PersistentIpythonHost
from asterion.runtime.factory import (
    RuntimeFactoryBinding,
    RuntimeFactoryContext,
    RuntimeFactoryError,
)
from asterion.runtime.host import AgentRuntimeClient
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
        trace = context.host_services.get("prime.private-trace")
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
        )
        launch = None
        return AsterionPrimeRuntimeClient(session)
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
