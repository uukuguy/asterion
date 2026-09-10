"""Immutable private state contracts for one Asterion Prime backend."""

from __future__ import annotations

from dataclasses import dataclass, fields
import hashlib
import json
import re
from collections.abc import Mapping
from typing import Literal


_ERROR = "invalid Prime backend state"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_MAX_INTEGER = (1 << 53) - 1
_PHASES = frozenset(
    {"created", "open", "effect-active", "suspended", "terminal", "recovery-required"}
)


class PrimeStateError(ValueError):
    """Raised when private backend state does not satisfy its closed shape."""

    def __init__(self) -> None:
        super().__init__(_ERROR)


def _identifier(value: object) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise PrimeStateError
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise PrimeStateError from None
    return value


def _version(value: object) -> str:
    if type(value) is not str or _VERSION.fullmatch(value) is None:
        raise PrimeStateError
    return value


def _digest(value: object) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise PrimeStateError
    return value


def _positive_integer(value: object) -> int:
    if type(value) is not int or not 1 <= value <= _MAX_INTEGER:
        raise PrimeStateError
    return value


def _nonnegative_integer(value: object) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_INTEGER:
        raise PrimeStateError
    return value


def _optional_identifier(value: object) -> str | None:
    return None if value is None else _identifier(value)


def _optional_digest(value: object) -> str | None:
    return None if value is None else _digest(value)


@dataclass(frozen=True, slots=True, repr=False)
class PrimeBackendIdentity:
    """Exact immutable identity of one live backend generation."""

    session_id: str
    generation: int
    provider_id: str
    application_id: str
    application_version: str
    runtime_id: Literal["asterion.prime"]
    pi_command_sha256: str
    extension_binding_fingerprint: str
    worker_identity_sha256: str
    continuation_id: str
    private_root_identity: str
    ceilings_sha256: str

    def __post_init__(self) -> None:
        _identifier(self.session_id)
        _positive_integer(self.generation)
        _identifier(self.provider_id)
        _identifier(self.application_id)
        _version(self.application_version)
        if self.runtime_id != "asterion.prime":
            raise PrimeStateError
        _digest(self.pi_command_sha256)
        _digest(self.extension_binding_fingerprint)
        _digest(self.worker_identity_sha256)
        _identifier(self.continuation_id)
        _digest(self.private_root_identity)
        _digest(self.ceilings_sha256)

    def to_mapping(self) -> dict[str, object]:
        return {field.name: getattr(self, field.name) for field in fields(self)}

    @classmethod
    def from_mapping(cls, value: object) -> PrimeBackendIdentity:
        if not isinstance(value, Mapping) or set(value) != {
            field.name for field in fields(cls)
        }:
            raise PrimeStateError
        try:
            return cls(**dict(value))
        except (TypeError, ValueError):
            raise PrimeStateError from None

    @property
    def digest(self) -> str:
        return _mapping_digest(self.to_mapping())

    def __repr__(self) -> str:
        return (
            "PrimeBackendIdentity("
            f"session_id={self.session_id!r}, generation={self.generation!r}, "
            f"digest={self.digest!r})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class PrimeBackendSnapshot:
    """Public-safe immutable state projection of a live backend."""

    identity: PrimeBackendIdentity
    cursor: int
    phase: Literal[
        "created", "open", "effect-active", "suspended", "terminal", "recovery-required"
    ]
    outstanding_effect: str | None
    authority_revision: int

    def __post_init__(self) -> None:
        if type(self.identity) is not PrimeBackendIdentity:
            raise PrimeStateError
        _nonnegative_integer(self.cursor)
        if self.phase not in _PHASES:
            raise PrimeStateError
        _optional_identifier(self.outstanding_effect)
        _nonnegative_integer(self.authority_revision)

    def __repr__(self) -> str:
        return (
            "PrimeBackendSnapshot("
            f"identity_digest={self.identity.digest!r}, cursor={self.cursor!r}, "
            f"phase={self.phase!r}, authority_revision={self.authority_revision!r})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class PrimeCheckpoint:
    """Digest-bound private recovery checkpoint."""

    checkpoint_id: str
    generation: int
    public_event_cursor: int
    private_transcript_sha256: str
    summary_sha256: str | None
    covered_leaf_id: str | None
    worker_identity_sha256: str
    continuation_id: str
    usage_sha256: str
    outstanding_effect: str | None
    prior_checkpoint_sha256: str | None

    def __post_init__(self) -> None:
        _identifier(self.checkpoint_id)
        _positive_integer(self.generation)
        _nonnegative_integer(self.public_event_cursor)
        _digest(self.private_transcript_sha256)
        _optional_digest(self.summary_sha256)
        _optional_identifier(self.covered_leaf_id)
        if (self.summary_sha256 is None) != (self.covered_leaf_id is None):
            raise PrimeStateError
        _digest(self.worker_identity_sha256)
        _identifier(self.continuation_id)
        _digest(self.usage_sha256)
        _optional_identifier(self.outstanding_effect)
        _optional_digest(self.prior_checkpoint_sha256)

    def to_mapping(self) -> dict[str, object]:
        return {field.name: getattr(self, field.name) for field in fields(self)}

    @classmethod
    def from_mapping(cls, value: object) -> PrimeCheckpoint:
        if not isinstance(value, Mapping) or set(value) != {
            field.name for field in fields(cls)
        }:
            raise PrimeStateError
        try:
            return cls(**dict(value))
        except (TypeError, ValueError):
            raise PrimeStateError from None

    @property
    def digest(self) -> str:
        return _mapping_digest(self.to_mapping())

    def __repr__(self) -> str:
        return (
            "PrimeCheckpoint("
            f"checkpoint_id={self.checkpoint_id!r}, generation={self.generation!r}, "
            f"public_event_cursor={self.public_event_cursor!r}, digest={self.digest!r})"
        )


def _mapping_digest(value: dict[str, object]) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "PrimeBackendIdentity",
    "PrimeBackendSnapshot",
    "PrimeCheckpoint",
    "PrimeStateError",
]
