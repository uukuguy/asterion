"""Host-owned exact control-provider factory registry."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
import re
from types import MappingProxyType

from asterion.control.authority import AuthorityEnvelope
from asterion.control.host import ControlPlaneClient, ControlPlaneManifest
from asterion.control.protocol import IDENTIFIER, SEMANTIC_VERSION
from asterion.control.session_context import (
    SESSION_CONTEXT_CAPABILITY,
    SessionContextClient,
)
from asterion.immutable import RedactedImmutableMapping


class ControlPlaneFactoryError(ValueError):
    """Raised when exact provider construction is invalid or unavailable."""


CONTEXT_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")


@dataclass(frozen=True, repr=False)
class ControlPlaneFactoryContext:
    system_id: str
    system_version: str
    control_plane_id: str
    control_plane_version: str
    private_root: Path
    options: Mapping[str, str]
    authority: AuthorityEnvelope | None = None
    host_services: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            any(
                IDENTIFIER.fullmatch(value) is None
                for value in (self.system_id, self.control_plane_id)
            )
            or any(
                SEMANTIC_VERSION.fullmatch(value) is None
                for value in (self.system_version, self.control_plane_version)
            )
            or not isinstance(self.private_root, Path)
            or not isinstance(self.options, Mapping)
            or (
                self.authority is not None
                and not isinstance(self.authority, AuthorityEnvelope)
            )
            or any(
                not isinstance(key, str)
                or CONTEXT_KEY.fullmatch(key) is None
                or not isinstance(value, str)
                for key, value in self.options.items()
            )
            or not isinstance(self.host_services, Mapping)
            or any(
                not isinstance(key, str) or IDENTIFIER.fullmatch(key) is None
                for key in self.host_services
            )
        ):
            raise ControlPlaneFactoryError("control plane factory context is invalid")
        try:
            private_root = self.private_root.resolve(strict=True)
        except (OSError, RuntimeError):
            raise ControlPlaneFactoryError(
                "control plane private root is invalid"
            ) from None
        if not private_root.is_dir():
            raise ControlPlaneFactoryError("control plane private root is invalid")
        object.__setattr__(self, "private_root", private_root)
        object.__setattr__(self, "options", RedactedImmutableMapping(self.options))
        object.__setattr__(
            self,
            "host_services",
            RedactedImmutableMapping(self.host_services),
        )

    def __repr__(self) -> str:
        return (
            "ControlPlaneFactoryContext("
            f"system_id={self.system_id!r}, "
            f"system_version={self.system_version!r}, "
            f"control_plane_id={self.control_plane_id!r}, "
            f"control_plane_version={self.control_plane_version!r}, "
            "private_root=<redacted>, options=<redacted>, authority=<redacted>, "
            "host_services=<redacted>)"
        )


ControlPlaneFactory = Callable[[ControlPlaneFactoryContext], ControlPlaneClient]


@dataclass(frozen=True)
class ControlPlaneFactoryBinding:
    control_plane_id: str
    version: str
    commands: tuple[str, ...]
    events: tuple[str, ...]
    capabilities: tuple[str, ...]
    continuation_media_type: str
    checkpoint_version: str
    compatibility_ids: tuple[str, ...]
    factory: ControlPlaneFactory

    @property
    def manifest(self) -> ControlPlaneManifest:
        return ControlPlaneManifest(
            control_plane_id=self.control_plane_id,
            version=self.version,
            commands=self.commands,
            events=self.events,
            capabilities=self.capabilities,
            continuation_media_type=self.continuation_media_type,
            checkpoint_version=self.checkpoint_version,
            compatibility_ids=self.compatibility_ids,
        )


class ControlPlaneFactoryRegistry:
    def __init__(self, bindings: Iterable[ControlPlaneFactoryBinding]) -> None:
        values: dict[tuple[str, str], ControlPlaneFactoryBinding] = {}
        try:
            candidates = tuple(bindings)
        except TypeError:
            raise ControlPlaneFactoryError(
                "control plane factory bindings are invalid"
            ) from None
        for binding in candidates:
            if not isinstance(binding, ControlPlaneFactoryBinding):
                raise ControlPlaneFactoryError(
                    "control plane factory binding is invalid"
                )
            identity = (binding.control_plane_id, binding.version)
            if identity in values or not callable(binding.factory):
                raise ControlPlaneFactoryError(
                    "control plane factory binding is invalid"
                )
            try:
                binding.manifest.to_mapping()
            except (TypeError, ValueError):
                raise ControlPlaneFactoryError(
                    "control plane factory binding is invalid"
                ) from None
            values[identity] = binding
        self._bindings = MappingProxyType(values)

    def select(
        self, control_plane_id: str, version: str
    ) -> ControlPlaneFactoryBinding:
        try:
            return self._bindings[(control_plane_id, version)]
        except (KeyError, TypeError):
            raise ControlPlaneFactoryError(
                "control plane factory is unavailable"
            ) from None


def bind_selected_session_context_client(
    client: object,
) -> SessionContextClient | None:
    """Return one explicitly selected extension when declaration and shape agree."""

    manifest = getattr(client, "manifest", None)
    if not isinstance(manifest, ControlPlaneManifest):
        raise ControlPlaneFactoryError("control plane client manifest is invalid")
    declared = SESSION_CONTEXT_CAPABILITY in manifest.capabilities
    implemented = isinstance(client, SessionContextClient)
    if declared != implemented:
        raise ControlPlaneFactoryError(
            "session context provider binding is invalid"
        )
    return client if implemented else None
