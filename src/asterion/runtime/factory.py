"""Host-owned exact runtime factory registry."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from asterion.immutable import RedactedImmutableMapping
from asterion.runtime.host import AgentRuntimeClient, RuntimeManifest


class RuntimeFactoryError(ValueError):
    """Raised when runtime construction is unavailable or ambiguous."""


@dataclass(frozen=True, repr=False)
class RuntimeFactoryContext:
    provider_id: str
    application_id: str
    application_version: str
    runtime_id: str
    assembly_path: Path
    options: Mapping[str, str]
    host_services: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "options", RedactedImmutableMapping(self.options)
        )
        object.__setattr__(
            self,
            "host_services",
            RedactedImmutableMapping(self.host_services),
        )

    def __repr__(self) -> str:
        return (
            "RuntimeFactoryContext("
            f"provider_id={self.provider_id!r}, "
            f"application_id={self.application_id!r}, "
            f"application_version={self.application_version!r}, "
            f"runtime_id={self.runtime_id!r}, "
            "assembly_path=<redacted>, options=<redacted>, "
            "host_services=<redacted>)"
        )


RuntimeFactory = Callable[[RuntimeFactoryContext], AgentRuntimeClient]


@dataclass(frozen=True)
class RuntimeFactoryBinding:
    runtime_id: str
    capabilities: tuple[str, ...]
    factory: RuntimeFactory

    @property
    def manifest(self) -> RuntimeManifest:
        return RuntimeManifest(
            runtime_id=self.runtime_id, capabilities=self.capabilities
        )


class RuntimeFactoryRegistry:
    def __init__(self, bindings: Iterable[RuntimeFactoryBinding]) -> None:
        values: dict[str, RuntimeFactoryBinding] = {}
        for binding in bindings:
            if (
                not isinstance(binding, RuntimeFactoryBinding)
                or binding.runtime_id in values
                or tuple(sorted(set(binding.capabilities))) != binding.capabilities
                or not callable(binding.factory)
            ):
                raise RuntimeFactoryError("runtime factory binding is invalid")
            binding.manifest.to_mapping()
            values[binding.runtime_id] = binding
        self._bindings = MappingProxyType(values)

    def select(self, runtime_id: str) -> RuntimeFactoryBinding:
        try:
            return self._bindings[runtime_id]
        except KeyError:
            raise RuntimeFactoryError("runtime factory is unavailable") from None
