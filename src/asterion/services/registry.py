"""Exact selected-only host-service factory discovery and lifetimes."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from importlib import metadata
from types import MappingProxyType
from typing import TypeVar


HOST_SERVICE_ENTRY_POINT_GROUP = "asterion.host_services"
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_OPTION_NAME = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_SEMANTIC_VERSION = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$"
)


class HostServiceRegistryError(ValueError):
    """Raised when exact host-service selection is unavailable or unsafe."""


_Value = TypeVar("_Value")


class _FrozenMapping(Mapping[str, _Value]):
    def __init__(self, values: Mapping[str, _Value]) -> None:
        self._values = MappingProxyType(dict(values))

    def __getitem__(self, key: str) -> _Value:
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Mapping) and dict(self.items()) == dict(other.items())

    def __repr__(self) -> str:
        return "<immutable host-service values>"


@dataclass(frozen=True, repr=False)
class HostServiceFactoryContext:
    provider_id: str
    application_id: str
    application_version: str
    capability_id: str
    options: Mapping[str, str]

    def __post_init__(self) -> None:
        if (
            _IDENTIFIER.fullmatch(self.provider_id) is None
            or _IDENTIFIER.fullmatch(self.application_id) is None
            or _SEMANTIC_VERSION.fullmatch(self.application_version) is None
            or _IDENTIFIER.fullmatch(self.capability_id) is None
        ):
            raise HostServiceRegistryError("host service context is invalid")
        object.__setattr__(self, "options", _FrozenMapping(self.options))

    def __repr__(self) -> str:
        return (
            "HostServiceFactoryContext("
            f"provider_id={self.provider_id!r}, "
            f"application_id={self.application_id!r}, "
            f"application_version={self.application_version!r}, "
            f"capability_id={self.capability_id!r}, options=<redacted>)"
        )


HostServiceFactory = Callable[
    [HostServiceFactoryContext],
    AbstractAsyncContextManager[object],
]


@dataclass(frozen=True)
class HostServiceFactoryBinding:
    capability_id: str
    option_names: tuple[str, ...]
    factory: HostServiceFactory


class _RedactedAsyncContextManager:
    def __init__(
        self,
        manager: AbstractAsyncContextManager[object],
        *,
        message: str,
    ) -> None:
        self._manager = manager
        self._message = message

    async def __aenter__(self) -> object:
        try:
            return await self._manager.__aenter__()
        except Exception:
            raise HostServiceRegistryError(self._message) from None

    async def __aexit__(self, exc_type, exc, traceback):
        try:
            return await self._manager.__aexit__(exc_type, exc, traceback)
        except Exception:
            raise HostServiceRegistryError(self._message) from None


def parse_host_service_options(
    values: Iterable[str],
) -> Mapping[str, Mapping[str, str]]:
    """Parse repeatable opaque ``CAPABILITY:KEY=VALUE`` options."""

    parsed: dict[str, dict[str, str]] = {}
    for raw in values:
        if type(raw) is not str:
            raise HostServiceRegistryError("host service option is invalid")
        capability_id, colon, remainder = raw.partition(":")
        key, equals, value = remainder.partition("=")
        if (
            not colon
            or not equals
            or _IDENTIFIER.fullmatch(capability_id) is None
            or _OPTION_NAME.fullmatch(key) is None
            or not _safe_option_value(value)
            or key in parsed.get(capability_id, {})
        ):
            raise HostServiceRegistryError("host service option is invalid")
        parsed.setdefault(capability_id, {})[key] = value
    return _FrozenMapping(
        {
            capability_id: _FrozenMapping(options)
            for capability_id, options in parsed.items()
        }
    )


class HostServiceFactoryRegistry:
    """Discover and enter only factories required by one selected assembly."""

    def __init__(self, entry_points: Iterable[object] | None = None) -> None:
        if entry_points is None:
            self._entry_points = None
        else:
            self._entry_points = tuple(
                entry
                for entry in entry_points
                if getattr(entry, "group", None) == HOST_SERVICE_ENTRY_POINT_GROUP
            )

    @asynccontextmanager
    async def open(
        self,
        *,
        provider_id: str,
        application_id: str,
        application_version: str,
        capability_ids: tuple[str, ...],
        options: Mapping[str, Mapping[str, str]],
        managed: Mapping[str, AbstractAsyncContextManager[object]] | None = None,
    ):
        """Enter one immutable exact service map for a selected assembly."""

        managed_values = {} if managed is None else dict(managed)
        if (
            tuple(sorted(set(capability_ids))) != capability_ids
            or any(_IDENTIFIER.fullmatch(item) is None for item in capability_ids)
            or set(options) - set(capability_ids)
            or set(managed_values) - set(capability_ids)
        ):
            raise HostServiceRegistryError("host service selection is invalid")
        selected: dict[str, object] = {}
        async with AsyncExitStack() as stack:
            for capability_id in capability_ids:
                if capability_id in managed_values:
                    if options.get(capability_id):
                        raise HostServiceRegistryError(
                            "managed host service options are invalid"
                        )
                    try:
                        selected[capability_id] = await stack.enter_async_context(
                            _RedactedAsyncContextManager(
                                managed_values[capability_id],
                                message="managed host service is unavailable",
                            )
                        )
                    except Exception:
                        raise HostServiceRegistryError(
                            "managed host service is unavailable"
                        ) from None
                    continue
                binding = self._load_binding(capability_id)
                capability_options = options.get(capability_id, {})
                if set(capability_options) - set(binding.option_names):
                    raise HostServiceRegistryError(
                        "host service options are invalid"
                    )
                context = HostServiceFactoryContext(
                    provider_id=provider_id,
                    application_id=application_id,
                    application_version=application_version,
                    capability_id=capability_id,
                    options=capability_options,
                )
                try:
                    manager = binding.factory(context)
                    selected[capability_id] = await stack.enter_async_context(
                        _RedactedAsyncContextManager(
                            manager, message="host service is unavailable"
                        )
                    )
                except Exception:
                    raise HostServiceRegistryError(
                        "host service is unavailable"
                    ) from None
            yield MappingProxyType(selected)

    def _load_binding(self, capability_id: str) -> HostServiceFactoryBinding:
        entries = (
            tuple(
                metadata.entry_points(group=HOST_SERVICE_ENTRY_POINT_GROUP)
            )
            if self._entry_points is None
            else self._entry_points
        )
        matches = [
            entry
            for entry in entries
            if getattr(entry, "name", None) == capability_id
        ]
        if len(matches) != 1:
            raise HostServiceRegistryError("host service factory is unavailable")
        try:
            create_binding = matches[0].load()
            if not callable(create_binding):
                raise TypeError
            binding = create_binding()
        except Exception:
            raise HostServiceRegistryError(
                "host service factory failed to load"
            ) from None
        if (
            not isinstance(binding, HostServiceFactoryBinding)
            or binding.capability_id != capability_id
            or tuple(sorted(set(binding.option_names))) != binding.option_names
            or any(_OPTION_NAME.fullmatch(name) is None for name in binding.option_names)
            or not callable(binding.factory)
        ):
            raise HostServiceRegistryError("host service factory binding is invalid")
        return binding


def _safe_option_value(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and all(
            unicodedata.category(character) not in {"Cc", "Cs"}
            for character in value
        )
    )
