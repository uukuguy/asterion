"""DCI-owned private artifact payloads and public projections."""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import PurePath
from types import MappingProxyType


class DciArtifactPayloadError(ValueError):
    """Raised when DCI private artifact payloads are malformed."""


class DciInProcessArtifactPayload:
    """Deeply immutable DCI stage data with one explicit public projection."""

    __slots__ = ("_private_value", "_public_projection")

    def __init__(
        self,
        *,
        private_value: Mapping[str, object],
        public_projection: Mapping[str, object],
    ) -> None:
        if not isinstance(private_value, Mapping) or not isinstance(
            public_projection, Mapping
        ):
            raise DciArtifactPayloadError("dci private artifact payload is invalid")
        failed = False
        frozen_private: Mapping[str, object] | None = None
        frozen_public: Mapping[str, object] | None = None
        try:
            frozen_private = _freeze_private_mapping(private_value)
            projected = project_dci_public_value(public_projection)
            if not isinstance(projected, dict):
                failed = True
            else:
                frozen_public = _freeze_mapping(projected)
        except Exception:
            failed = True
        if failed or frozen_private is None or frozen_public is None:
            raise DciArtifactPayloadError("dci private artifact payload is invalid")
        object.__setattr__(self, "_private_value", frozen_private)
        object.__setattr__(self, "_public_projection", frozen_public)

    @property
    def private_value(self) -> Mapping[str, object]:
        return self._private_value

    @property
    def public_projection(self) -> Mapping[str, object]:
        return self._public_projection

    def __repr__(self) -> str:
        return "<dci in-process private artifact payload>"

    __str__ = __repr__

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("dci private artifact payload is immutable")


def project_dci_public_value(value: object) -> object:
    """Return DCI's explicit JSON-safe public projection."""

    if isinstance(value, DciInProcessArtifactPayload):
        return project_dci_public_value(value.public_projection)
    if isinstance(value, Mapping):
        projected: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise DciArtifactPayloadError("dci artifact public projection is invalid")
            projected[key] = project_dci_public_value(item)
        return projected
    if isinstance(value, (tuple, list)):
        return [project_dci_public_value(item) for item in value]
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise DciArtifactPayloadError("dci artifact public projection is invalid")


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({key: _freeze(item) for key, item in value.items()})


def _freeze(value: object) -> object:
    if isinstance(value, DciInProcessArtifactPayload):
        return value
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


def _freeze_private_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    if not all(type(key) is str for key in value):
        raise TypeError
    return MappingProxyType(
        {key: _freeze_private(item) for key, item in value.items()}
    )


def _freeze_private(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_private_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_private(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_private(item) for item in value)
    if value is None or type(value) in {str, bool, int, float, bytes}:
        return value
    if isinstance(value, PurePath):
        return value
    raise TypeError


__all__ = ("DciInProcessArtifactPayload", "project_dci_public_value")
