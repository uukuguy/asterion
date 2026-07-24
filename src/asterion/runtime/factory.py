"""Host-owned exact runtime factory registry."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from asterion.runtime.host import AgentRuntimeClient, RuntimeManifest


class RuntimeFactoryError(ValueError):
    """Raised when runtime construction is unavailable or ambiguous."""


@dataclass(frozen=True)
class RuntimeFactoryContext:
    provider_id: str
    application_id: str
    application_version: str
    runtime_id: str
    assembly_path: Path
    options: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "options", MappingProxyType(dict(self.options)))


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
