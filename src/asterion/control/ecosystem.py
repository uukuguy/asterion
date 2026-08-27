"""Closed provider-neutral ecosystem portfolio contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from collections.abc import Iterable
from typing import ContextManager, IO, Literal, Protocol, Self

from asterion.control.protocol import OPAQUE_ID, SEMANTIC_VERSION


EcosystemResourceKind = Literal[
    "context-file",
    "prompt-template",
    "markdown-skill",
    "python-skill",
    "extension",
    "package",
    "mcp-server",
]
EcosystemRegistrationKind = Literal["command", "tool", "provider-model"]
EcosystemSourceKind = Literal["local-child", "installed-distribution"]
EcosystemScope = Literal["session", "project", "global"]
EcosystemTerminalStatus = Literal["succeeded", "failed", "cancelled", "uncertain"]

_RESOURCE_KINDS = frozenset(
    {
        "context-file",
        "prompt-template",
        "markdown-skill",
        "python-skill",
        "extension",
        "package",
        "mcp-server",
    }
)
_REGISTRATION_KINDS = frozenset({"command", "tool", "provider-model"})
_SOURCE_KINDS = frozenset({"local-child", "installed-distribution"})
_SCOPES = frozenset({"session", "project", "global"})
_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled", "uncertain"})
_COLLISION_REASON = "ecosystem-resource-collision"


class EcosystemError(ValueError):
    """Raised when a public ecosystem contract is invalid."""


@dataclass(frozen=True, repr=False)
class EcosystemSourceRef:
    source_id: str
    kind: EcosystemSourceKind
    version: str
    content_sha256: str

    def __post_init__(self) -> None:
        _require_opaque_id(self.source_id)
        _require_closed_value(self.kind, _SOURCE_KINDS)
        _require_version(self.version)
        _require_sha256(self.content_sha256)


@dataclass(frozen=True, repr=False)
class EcosystemResourceRef:
    resource_id: str
    version: str
    kind: EcosystemResourceKind
    scope: EcosystemScope
    source: EcosystemSourceRef
    content_sha256: str

    def __post_init__(self) -> None:
        _require_opaque_id(self.resource_id)
        _require_version(self.version)
        _require_closed_value(self.kind, _RESOURCE_KINDS)
        _require_closed_value(self.scope, _SCOPES)
        if not isinstance(self.source, EcosystemSourceRef):
            raise EcosystemError("ecosystem resource is invalid")
        _require_sha256(self.content_sha256)


@dataclass(frozen=True)
class EcosystemRegistrationRef:
    registration_id: str
    kind: EcosystemRegistrationKind
    extension_id: str
    version: str

    def __post_init__(self) -> None:
        _require_opaque_id(self.registration_id)
        _require_closed_value(self.kind, _REGISTRATION_KINDS)
        _require_opaque_id(self.extension_id)
        _require_version(self.version)


@dataclass(frozen=True)
class EcosystemCollision:
    kind: str
    logical_id: str
    source_ids: tuple[str, ...]
    reason_code: Literal["ecosystem-resource-collision"]

    def __post_init__(self) -> None:
        _require_closed_value(self.kind, _RESOURCE_KINDS | _REGISTRATION_KINDS)
        _require_opaque_id(self.logical_id)
        _require_sorted_unique_ids(self.source_ids)
        if self.reason_code != _COLLISION_REASON:
            raise EcosystemError("ecosystem collision is invalid")


@dataclass(frozen=True, repr=False)
class EcosystemPortfolio:
    portfolio_id: str
    authority_id: str
    authority_revision: int
    resources: tuple[EcosystemResourceRef, ...]
    registrations: tuple[EcosystemRegistrationRef, ...]
    digest: str = field(init=False)

    def __post_init__(self) -> None:
        _require_opaque_id(self.portfolio_id)
        _require_opaque_id(self.authority_id)
        _require_positive_integer(self.authority_revision)
        _require_resources(self.resources)
        _require_registrations(self.registrations)
        if self.resources != tuple(sorted(self.resources, key=_resource_key)):
            raise EcosystemError("ecosystem resources are not canonical")
        if self.registrations != tuple(sorted(self.registrations, key=_registration_key)):
            raise EcosystemError("ecosystem registrations are not canonical")
        if detect_ecosystem_collisions(self.resources, self.registrations):
            raise EcosystemError("ecosystem portfolio has a collision")
        object.__setattr__(self, "digest", _portfolio_digest(self))


@dataclass(frozen=True, repr=False)
class EcosystemActivationReceipt:
    portfolio_digest: str
    feature_ids: tuple[str, ...]
    status: EcosystemTerminalStatus
    resource_count: int
    registration_count: int
    package_count: int
    mcp_count: int
    lifecycle_count: int
    provider_operations: int
    model_credential_reads: int
    owned_process_count: int

    def __post_init__(self) -> None:
        _require_sha256(self.portfolio_digest)
        _require_sorted_unique_ids(self.feature_ids, allow_empty=True)
        _require_closed_value(self.status, _TERMINAL_STATUSES)
        for value in (
            self.resource_count,
            self.registration_count,
            self.package_count,
            self.mcp_count,
            self.lifecycle_count,
            self.provider_operations,
            self.model_credential_reads,
            self.owned_process_count,
        ):
            _require_nonnegative_integer(value)

    @classmethod
    def succeeded(cls, **values: object) -> Self:
        return cls(status="succeeded", **values)  # type: ignore[arg-type]

    @classmethod
    def failed(cls, **values: object) -> Self:
        return cls(status="failed", **values)  # type: ignore[arg-type]

    @classmethod
    def cancelled(cls, **values: object) -> Self:
        return cls(status="cancelled", **values)  # type: ignore[arg-type]

    @classmethod
    def uncertain(cls, **values: object) -> Self:
        return cls(status="uncertain", **values)  # type: ignore[arg-type]


class EcosystemPrivateSourceStore(Protocol):
    """Private host capability for one already-admitted source child."""

    def open_file(
        self,
        resource_id: str,
        relative_path: str,
    ) -> ContextManager[IO[bytes]]: ...


def detect_ecosystem_collisions(
    resources: Iterable[EcosystemResourceRef],
    registrations: Iterable[EcosystemRegistrationRef],
) -> tuple[EcosystemCollision, ...]:
    """Return canonical resource and registration identity collisions."""

    resource_items = tuple(resources)
    registration_items = tuple(registrations)
    _require_resources(resource_items)
    _require_registrations(registration_items)

    resource_groups: dict[tuple[str, str, str], list[str]] = {}
    for resource in resource_items:
        key = (resource.kind, resource.scope, resource.resource_id)
        resource_groups.setdefault(key, []).append(resource.source.source_id)

    registration_groups: dict[tuple[str, str], list[str]] = {}
    for registration in registration_items:
        key = (registration.kind, registration.registration_id)
        registration_groups.setdefault(key, []).append(registration.extension_id)

    collisions = [
        EcosystemCollision(
            kind=kind,
            logical_id=f"{scope}:{resource_id}",
            source_ids=tuple(sorted(set(source_ids))),
            reason_code=_COLLISION_REASON,
        )
        for (kind, scope, resource_id), source_ids in resource_groups.items()
        if len(source_ids) > 1
    ]
    collisions.extend(
        EcosystemCollision(
            kind=kind,
            logical_id=registration_id,
            source_ids=tuple(sorted(set(extension_ids))),
            reason_code=_COLLISION_REASON,
        )
        for (kind, registration_id), extension_ids in registration_groups.items()
        if len(extension_ids) > 1
    )
    return tuple(
        sorted(
            collisions,
            key=lambda collision: (
                collision.kind,
                collision.logical_id,
                collision.source_ids,
            ),
        )
    )


def build_ecosystem_portfolio(
    *,
    portfolio_id: str,
    authority_id: str,
    authority_revision: int,
    resources: Iterable[EcosystemResourceRef],
    registrations: Iterable[EcosystemRegistrationRef],
) -> EcosystemPortfolio:
    """Build one immutable, deterministic collision-free portfolio."""

    resource_items = tuple(resources)
    registration_items = tuple(registrations)
    _require_resources(resource_items)
    _require_registrations(registration_items)
    if detect_ecosystem_collisions(resource_items, registration_items):
        raise EcosystemError("ecosystem portfolio has a collision")
    return EcosystemPortfolio(
        portfolio_id=portfolio_id,
        authority_id=authority_id,
        authority_revision=authority_revision,
        resources=tuple(sorted(resource_items, key=_resource_key)),
        registrations=tuple(sorted(registration_items, key=_registration_key)),
    )


def _resource_key(resource: EcosystemResourceRef) -> tuple[str, ...]:
    return (
        resource.kind,
        resource.scope,
        resource.resource_id,
        resource.version,
        resource.source.source_id,
        resource.source.kind,
        resource.source.version,
        resource.source.content_sha256,
        resource.content_sha256,
    )


def _registration_key(registration: EcosystemRegistrationRef) -> tuple[str, ...]:
    return (
        registration.kind,
        registration.registration_id,
        registration.extension_id,
        registration.version,
    )


def _portfolio_digest(portfolio: EcosystemPortfolio) -> str:
    value = {
        "authority_id": portfolio.authority_id,
        "authority_revision": portfolio.authority_revision,
        "portfolio_id": portfolio.portfolio_id,
        "registrations": [
            {
                "extension_id": registration.extension_id,
                "kind": registration.kind,
                "registration_id": registration.registration_id,
                "version": registration.version,
            }
            for registration in portfolio.registrations
        ],
        "resources": [
            {
                "content_sha256": resource.content_sha256,
                "kind": resource.kind,
                "resource_id": resource.resource_id,
                "scope": resource.scope,
                "source": {
                    "content_sha256": resource.source.content_sha256,
                    "kind": resource.source.kind,
                    "source_id": resource.source.source_id,
                    "version": resource.source.version,
                },
                "version": resource.version,
            }
            for resource in portfolio.resources
        ],
    }
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_resources(value: object) -> None:
    if not isinstance(value, tuple) or any(
        not isinstance(item, EcosystemResourceRef) for item in value
    ):
        raise EcosystemError("ecosystem resources are invalid")


def _require_registrations(value: object) -> None:
    if not isinstance(value, tuple) or any(
        not isinstance(item, EcosystemRegistrationRef) for item in value
    ):
        raise EcosystemError("ecosystem registrations are invalid")


def _require_opaque_id(value: object) -> None:
    if not isinstance(value, str) or OPAQUE_ID.fullmatch(value) is None:
        raise EcosystemError("ecosystem identity is invalid")


def _require_version(value: object) -> None:
    if not isinstance(value, str) or SEMANTIC_VERSION.fullmatch(value) is None:
        raise EcosystemError("ecosystem version is invalid")


def _require_sha256(value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise EcosystemError("ecosystem digest is invalid")


def _require_closed_value(value: object, allowed: frozenset[str]) -> None:
    if not isinstance(value, str) or value not in allowed:
        raise EcosystemError("ecosystem value is invalid")


def _require_positive_integer(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise EcosystemError("ecosystem count is invalid")


def _require_nonnegative_integer(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EcosystemError("ecosystem count is invalid")


def _require_sorted_unique_ids(value: object, *, allow_empty: bool = False) -> None:
    if (
        not isinstance(value, tuple)
        or (not allow_empty and not value)
        or any(not isinstance(item, str) or OPAQUE_ID.fullmatch(item) is None for item in value)
        or value != tuple(sorted(set(value)))
    ):
        raise EcosystemError("ecosystem identities are invalid")
