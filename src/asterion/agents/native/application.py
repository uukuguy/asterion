"""One prepare and run door for every Native application."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from asterion.applications.first_party_packages import builtin_capability_registrations
from asterion.applications.native.provider import create_provider
from asterion.applications.provider import (
    ApplicationProviderError,
    InstalledApplication,
    InstalledApplicationProvider,
)
from asterion.applications.selection import (
    parse_application_selector,
    select_installed_application,
)
from asterion.applications.provider import resolve_installed_provider
from asterion.capability_packages.preparation import (
    load_prepared_capability_source,
    prepare_capability_source,
)
from asterion.capability_packages.protocol import CapabilityPackageRef
from asterion.capability_packages.sources.builtin import BuiltinCapabilitySource
from asterion.runner.application import ApplicationRunResult
from asterion.runner.composed import run_composed_application
from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryRegistry
from asterion.runtime.host import CancellationSignal
from asterion.services.registry import HostServiceFactoryRegistry


class NativeApplicationError(ValueError):
    """Raised when Native preparation or a run contract fails."""


@dataclass(frozen=True)
class NativeApplicationSpec:
    application_id: str
    application_version: str


@dataclass(frozen=True)
class NativeOperatorContext:
    runtime_factories: RuntimeFactoryRegistry
    runtime_options: Mapping[str, str]
    host_service_options: Mapping[str, Mapping[str, str]]
    managed_host_services: Mapping[str, AbstractAsyncContextManager[object]]


class NativeApplication:
    def __init__(
        self,
        application: InstalledApplication,
        operator: NativeOperatorContext,
    ) -> None:
        self._application = application
        self._operator = operator
        self._consumed = False

    @property
    def capability_packages(self) -> tuple[CapabilityPackageRef, ...]:
        return self._application.capability_packages

    async def run(
        self,
        input_text: str,
        *,
        run_id: str,
        signal: CancellationSignal | None = None,
    ) -> ApplicationRunResult:
        if self._consumed:
            raise NativeApplicationError("native application run is already consumed")
        self._consumed = True
        if signal is not None and signal.cancelled:
            raise NativeApplicationError("native application run was cancelled")
        assembly = self._application.assemblies[0]
        plan = assembly.plan
        async with HostServiceFactoryRegistry().open(
            provider_id="native",
            application_id=self._application.application_id,
            application_version=self._application.version,
            capability_ids=tuple(plan.host_capabilities),
            options=self._operator.host_service_options,
            managed=self._operator.managed_host_services,
        ) as host_services:
            binding = self._operator.runtime_factories.select(assembly.runtime_id)
            runtime = binding.factory(
                RuntimeFactoryContext(
                    provider_id="native",
                    application_id=self._application.application_id,
                    application_version=self._application.version,
                    runtime_id=assembly.runtime_id,
                    assembly_path=assembly.path,
                    options=self._operator.runtime_options,
                    host_services={},
                )
            )
            return await run_composed_application(
                plan,
                implementations=self._application.implementations,
                runtime=runtime,
                run_id=run_id,
                input_text=input_text,
                host_services=host_services,
                signal=signal,
            )


def prepare_native_application(
    spec: NativeApplicationSpec,
    operator: NativeOperatorContext,
) -> NativeApplication:
    """Validate one Native application without starting a runtime."""

    try:
        provider = create_provider()
        resolved = resolve_installed_provider(
            provider,
            runtime_factories=operator.runtime_factories,
            installed_packages=_installed_packages(provider),
        )
        selected = select_installed_application(
            resolved,
            parse_application_selector(
                f"{spec.application_id}@{spec.application_version}"
            ),
        )
    except ApplicationProviderError:
        raise NativeApplicationError("native application is unavailable") from None
    if len(selected.assemblies) != 1:
        raise NativeApplicationError("native application assembly is unavailable")
    host_ids = set(selected.assemblies[0].plan.host_capabilities)
    option_keys = set(operator.host_service_options)
    managed_keys = set(operator.managed_host_services)
    if option_keys & managed_keys or option_keys | managed_keys != host_ids:
        raise NativeApplicationError(
            "native application host services do not match"
        )
    return NativeApplication(selected, operator)


def _installed_packages(provider: InstalledApplicationProvider):
    refs: list[CapabilityPackageRef] = []
    for application in provider.applications:
        for ref in application.capability_packages:
            if ref not in refs:
                refs.append(ref)
    source = BuiltinCapabilitySource(builtin_capability_registrations())
    return tuple(
        load_prepared_capability_source(
            prepare_capability_source(ref, (source,), None)
        )
        for ref in refs
    )
