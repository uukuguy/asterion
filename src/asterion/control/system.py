"""Exact immutable resolution of long-running agent systems."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from asterion.applications.provider import (
    APPLICATION_PROVIDER_PROTOCOL,
    ApplicationProviderError,
    InstalledApplication,
    InstalledApplicationProvider,
    InstalledAssembly,
)
from asterion.applications.selection import (
    ApplicationSelector,
    select_installed_application,
)
from asterion.control.factory import (
    ControlPlaneFactoryBinding,
    ControlPlaneFactoryError,
    ControlPlaneFactoryRegistry,
)
from asterion.control.protocol import (
    AGENT_CONTROL_PROTOCOL,
    CONTROL_COMMAND_TYPES,
    CONTROL_EVENT_TYPES,
    IDENTIFIER,
    ControlProtocolError,
    validate_agent_system_manifest,
)
from asterion.protocol_ordering import is_sorted_unique_scalar_strings


class AgentSystemError(ValueError):
    """Raised when an agent system cannot resolve to one exact closure."""


@dataclass(frozen=True, repr=False)
class ApplicationPortfolioEntry:
    """One exact installed application assembly authorized for a session."""

    provider_id: str
    application: InstalledApplication
    assembly: InstalledAssembly

    @property
    def application_id(self) -> str:
        return self.application.application_id

    @property
    def version(self) -> str:
        return self.application.version

    @property
    def runtime_id(self) -> str:
        return self.assembly.runtime_id

    def __repr__(self) -> str:
        return (
            "ApplicationPortfolioEntry("
            f"provider_id={self.provider_id!r}, "
            f"application_id={self.application_id!r}, "
            f"version={self.version!r}, runtime_id={self.runtime_id!r})"
        )


@dataclass(frozen=True, repr=False)
class AgentSystemPlan:
    """Preflight-resolved static authority source for one agent system."""

    system_id: str
    version: str
    control_binding: ControlPlaneFactoryBinding
    portfolio: tuple[ApplicationPortfolioEntry, ...]
    policies: tuple[str, ...]
    host_capabilities: tuple[str, ...]
    control_capabilities: tuple[str, ...]

    @property
    def portfolio_by_identity(
        self,
    ) -> Mapping[tuple[str, str, str, str], ApplicationPortfolioEntry]:
        return MappingProxyType(
            {
                (
                    entry.provider_id,
                    entry.application_id,
                    entry.version,
                    entry.runtime_id,
                ): entry
                for entry in self.portfolio
            }
        )

    def __repr__(self) -> str:
        return (
            "AgentSystemPlan("
            f"system_id={self.system_id!r}, version={self.version!r}, "
            f"control_plane_id={self.control_binding.control_plane_id!r}, "
            f"control_plane_version={self.control_binding.version!r}, "
            f"portfolio={self.portfolio!r}, policies={self.policies!r}, "
            f"host_capabilities={self.host_capabilities!r}, "
            f"control_capabilities={self.control_capabilities!r})"
        )


def resolve_agent_system(
    manifest: Mapping[str, object],
    *,
    application_providers: Iterable[InstalledApplicationProvider],
    control_factories: ControlPlaneFactoryRegistry,
    host_capabilities: Sequence[str],
) -> AgentSystemPlan:
    """Resolve every exact static edge before constructing a control provider."""

    try:
        validated = validate_agent_system_manifest(manifest)
        providers = _index_application_providers(application_providers)
        available_host_capabilities = _validate_host_capabilities(host_capabilities)
        if not isinstance(control_factories, ControlPlaneFactoryRegistry):
            raise AgentSystemError("agent system control registry is invalid")

        required_host_capabilities = _string_tuple(
            validated, "host_capabilities"
        )
        if not set(required_host_capabilities).issubset(available_host_capabilities):
            raise AgentSystemError("agent system host capabilities are unavailable")

        control_ref = validated["control_plane"]
        if not isinstance(control_ref, Mapping):
            raise AgentSystemError("agent system control reference is invalid")
        control_binding = control_factories.select(
            str(control_ref["control_plane_id"]), str(control_ref["version"])
        )
        _validate_control_binding(
            control_binding,
            required_capabilities=_string_tuple(validated, "control_capabilities"),
        )

        raw_applications = validated["applications"]
        if not isinstance(raw_applications, tuple):
            raise AgentSystemError("agent system portfolio is invalid")
        portfolio = tuple(
            _resolve_portfolio_entry(reference, providers=providers)
            for reference in raw_applications
        )
    except AgentSystemError:
        raise
    except (
        ApplicationProviderError,
        ControlPlaneFactoryError,
        ControlProtocolError,
        KeyError,
        TypeError,
        ValueError,
    ):
        raise AgentSystemError("agent system cannot resolve") from None

    return AgentSystemPlan(
        system_id=str(validated["system_id"]),
        version=str(validated["version"]),
        control_binding=control_binding,
        portfolio=portfolio,
        policies=_string_tuple(validated, "policies"),
        host_capabilities=required_host_capabilities,
        control_capabilities=_string_tuple(validated, "control_capabilities"),
    )


def _index_application_providers(
    providers: Iterable[InstalledApplicationProvider],
) -> Mapping[str, InstalledApplicationProvider]:
    try:
        values = tuple(providers)
    except TypeError:
        raise AgentSystemError("agent system application providers are invalid") from None
    index: dict[str, InstalledApplicationProvider] = {}
    for provider in values:
        if (
            not isinstance(provider, InstalledApplicationProvider)
            or provider.protocol != APPLICATION_PROVIDER_PROTOCOL
            or IDENTIFIER.fullmatch(provider.provider_id) is None
            or provider.provider_id in index
            or not isinstance(provider.applications, tuple)
        ):
            raise AgentSystemError("agent system application providers are invalid")
        index[provider.provider_id] = provider
    return MappingProxyType(index)


def _validate_host_capabilities(values: Sequence[str]) -> frozenset[str]:
    if (
        not isinstance(values, (list, tuple))
        or any(
            not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None
            for value in values
        )
        or not is_sorted_unique_scalar_strings(values)
    ):
        raise AgentSystemError("agent system available host capabilities are invalid")
    return frozenset(values)


def _validate_control_binding(
    binding: ControlPlaneFactoryBinding, *, required_capabilities: tuple[str, ...]
) -> None:
    manifest = binding.manifest
    if (
        not set(CONTROL_COMMAND_TYPES).issubset(manifest.commands)
        or not set(CONTROL_EVENT_TYPES).issubset(manifest.events)
        or not set(required_capabilities).issubset(manifest.capabilities)
        or AGENT_CONTROL_PROTOCOL not in manifest.compatibility_ids
    ):
        raise AgentSystemError("agent system control provider is incompatible")


def _resolve_portfolio_entry(
    value: object,
    *,
    providers: Mapping[str, InstalledApplicationProvider],
) -> ApplicationPortfolioEntry:
    if not isinstance(value, Mapping):
        raise AgentSystemError("agent system application reference is invalid")
    provider_id = str(value["provider_id"])
    provider = providers.get(provider_id)
    if provider is None:
        raise AgentSystemError("agent system application provider is unavailable")
    application = select_installed_application(
        provider,
        ApplicationSelector(
            application_id=str(value["application_id"]),
            version=str(value["version"]),
        ),
    )
    runtime_id = str(value["runtime_id"])
    matches = tuple(
        assembly
        for assembly in application.assemblies
        if assembly.runtime_id == runtime_id
        and assembly.plan.application_id == application.application_id
        and assembly.plan.version == application.version
        and assembly.plan.runtime_id == runtime_id
    )
    if len(matches) != 1:
        raise AgentSystemError("agent system application assembly is unavailable")
    return ApplicationPortfolioEntry(
        provider_id=provider_id,
        application=application,
        assembly=matches[0],
    )


def _string_tuple(value: Mapping[str, object], field: str) -> tuple[str, ...]:
    raw = value[field]
    if not isinstance(raw, tuple) or not all(isinstance(item, str) for item in raw):
        raise AgentSystemError(f"agent system {field} is invalid")
    return raw
