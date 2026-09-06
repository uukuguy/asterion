"""Built-in capability-package source adapter."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from asterion.capability_packages.model import (
    CapabilityPackageCandidate,
    InstalledCapabilityPackage,
    PortableCapabilityPayload,
)
from asterion.capability_packages.payload import open_portable_payload
from asterion.capability_packages.protocol import (
    CapabilityPackageRef,
    validate_capability_package_manifest,
)


@dataclass(frozen=True, slots=True)
class BuiltinCapabilityRegistration:
    """One explicit, host-owned built-in capability-package binding."""

    package_ref: CapabilityPackageRef
    payload_root: Path = field(repr=False)
    provider_factory: Callable[[], InstalledCapabilityPackage] = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.package_ref) is not CapabilityPackageRef:
            raise ValueError("built-in capability registration is invalid")
        object.__setattr__(self, "payload_root", Path(self.payload_root))
        if not callable(self.provider_factory):
            raise ValueError("built-in capability registration is invalid")


class BuiltinCapabilitySourceError(ValueError):
    """Raised when built-in capability-package source handling fails closed."""


class BuiltinCapabilitySource:
    def __init__(
        self,
        registrations: Iterable[BuiltinCapabilityRegistration],
    ) -> None:
        try:
            self._registrations = tuple(registrations)
        except Exception:
            raise BuiltinCapabilitySourceError(
                "built-in capability source is invalid"
            ) from None

    def discover_metadata(self) -> tuple[CapabilityPackageCandidate, ...]:
        try:
            registrations = self._validated_registrations()
            candidates = []
            for registration in registrations:
                manifest = _read_descriptor_metadata(registration.payload_root)
                if manifest.package_ref != registration.package_ref:
                    raise BuiltinCapabilitySourceError(
                        "built-in capability source is invalid"
                    )
                candidates.append(
                    CapabilityPackageCandidate(
                        package_ref=registration.package_ref,
                        source_id=_source_id(registration.package_ref),
                        source_kind="builtin",
                        payload_sha256=None,
                        metadata={},
                    )
                )
            return tuple(candidates)
        except BuiltinCapabilitySourceError:
            raise
        except Exception:
            raise BuiltinCapabilitySourceError(
                "built-in capability source is invalid"
            ) from None

    def open_payload(
        self,
        candidate: CapabilityPackageCandidate,
    ) -> PortableCapabilityPayload:
        failed = False
        try:
            registration = self._registration_for(candidate)
            payload = open_portable_payload(
                _canonical_payload_root(registration.payload_root)
            )
            self.validate_source_identity(candidate, payload)
            return payload
        except BuiltinCapabilitySourceError:
            raise
        except Exception:
            failed = True
        if failed:
            raise BuiltinCapabilitySourceError("built-in capability source is invalid")
        raise BuiltinCapabilitySourceError("built-in capability source is invalid")

    def validate_source_identity(
        self,
        candidate: CapabilityPackageCandidate,
        payload: PortableCapabilityPayload,
    ) -> None:
        try:
            if (
                candidate.source_kind != "builtin"
                or candidate.source_id != _source_id(candidate.package_ref)
                or payload.manifest.package_ref != candidate.package_ref
                or (
                    candidate.payload_sha256 is not None
                    and candidate.payload_sha256 != payload.payload_sha256
                )
            ):
                raise BuiltinCapabilitySourceError(
                    "built-in capability source is invalid"
                )
        except BuiltinCapabilitySourceError:
            raise
        except Exception:
            raise BuiltinCapabilitySourceError(
                "built-in capability source is invalid"
            ) from None

    def load_provider(
        self,
        candidate: CapabilityPackageCandidate,
    ) -> InstalledCapabilityPackage:
        failed = False
        try:
            payload = self.open_payload(candidate)
            registration = self._registration_for(candidate)
            installed = registration.provider_factory()
            if (
                type(installed) is not InstalledCapabilityPackage
                or installed.package_ref != candidate.package_ref
                or installed.payload_sha256 != payload.payload_sha256
                or installed.source_id != candidate.source_id
                or installed.source_kind != candidate.source_kind
            ):
                raise BuiltinCapabilitySourceError(
                    "built-in capability source is invalid"
                )
            return installed
        except BuiltinCapabilitySourceError:
            raise
        except Exception:
            failed = True
        if failed:
            raise BuiltinCapabilitySourceError("built-in capability source is invalid")
        raise BuiltinCapabilitySourceError("built-in capability source is invalid")

    def _registration_for(
        self, candidate: CapabilityPackageCandidate
    ) -> BuiltinCapabilityRegistration:
        if type(candidate) is not CapabilityPackageCandidate:
            raise BuiltinCapabilitySourceError("built-in capability source is invalid")
        matches = tuple(
            registration
            for registration in self._validated_registrations()
            if registration.package_ref == candidate.package_ref
            and _source_id(registration.package_ref) == candidate.source_id
        )
        if len(matches) != 1:
            raise BuiltinCapabilitySourceError("built-in capability source is invalid")
        if candidate.source_kind != "builtin":
            raise BuiltinCapabilitySourceError("built-in capability source is invalid")
        return matches[0]

    def _validated_registrations(self) -> tuple[BuiltinCapabilityRegistration, ...]:
        try:
            registrations = tuple(self._registrations)
        except Exception:
            raise BuiltinCapabilitySourceError(
                "built-in capability source is invalid"
            ) from None
        seen_refs: set[CapabilityPackageRef] = set()
        seen_sources: set[str] = set()
        for registration in registrations:
            if type(registration) is not BuiltinCapabilityRegistration:
                raise BuiltinCapabilitySourceError(
                    "built-in capability source is invalid"
                )
            source_id = _source_id(registration.package_ref)
            if registration.package_ref in seen_refs or source_id in seen_sources:
                raise BuiltinCapabilitySourceError(
                    "built-in capability source is invalid"
                )
            seen_refs.add(registration.package_ref)
            seen_sources.add(source_id)
            _canonical_payload_root(registration.payload_root)
        return registrations


def _read_descriptor_metadata(root: Path):
    payload_root = _canonical_payload_root(root)
    descriptor = payload_root / "capability-package.json"
    if descriptor.is_symlink():
        raise BuiltinCapabilitySourceError("built-in capability source is invalid")
    resolved = descriptor.resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(payload_root):
        raise BuiltinCapabilitySourceError("built-in capability source is invalid")
    try:
        return validate_capability_package_manifest(json.loads(resolved.read_text()))
    except Exception:
        raise BuiltinCapabilitySourceError(
            "built-in capability source is invalid"
        ) from None


def _canonical_payload_root(root: Path) -> Path:
    path = Path(root)
    if path.is_symlink():
        raise BuiltinCapabilitySourceError("built-in capability source is invalid")
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        raise BuiltinCapabilitySourceError(
            "built-in capability source is invalid"
        ) from None
    if not resolved.is_dir():
        raise BuiltinCapabilitySourceError("built-in capability source is invalid")
    return resolved


def _source_id(package_ref: CapabilityPackageRef) -> str:
    return f"{package_ref.package_id}.builtin"


__all__ = (
    "BuiltinCapabilityRegistration",
    "BuiltinCapabilitySource",
    "BuiltinCapabilitySourceError",
)
