"""Explicit local-directory capability-package source adapter."""

from __future__ import annotations

import hashlib
import importlib.util
import stat
import sys
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from asterion.capability_packages.model import (
    CapabilityPackageCandidate,
    InstalledCapabilityPackage,
    PortableCapabilityPayload,
)
from asterion.capability_packages.payload import open_portable_payload
from asterion.capability_packages.protocol import CapabilitySourceDeclaration


SOURCE_KIND = "local-directory"
_LOCATOR_FIELDS = frozenset(
    {"root", "payload_root", "module_path", "factory_name"}
)
_ERROR_MESSAGE = "local capability source is invalid"
_MODULE_PREFIX = "_asterion_local_capability_"
_MISSING = object()


class LocalDirectoryCapabilitySourceError(ValueError):
    """Raised when explicit local-directory source handling fails closed."""


@dataclass(frozen=True, slots=True)
class _LocalRecord:
    declaration: CapabilitySourceDeclaration
    root: Path
    payload_root: Path
    module_path: Path
    factory_name: str
    payload: PortableCapabilityPayload


class LocalDirectoryCapabilityPackageSource:
    """Load capability packages from explicit operator-selected local roots."""

    def __init__(
        self,
        declarations: Sequence[CapabilitySourceDeclaration],
    ) -> None:
        self._declarations = tuple(declarations)

    def discover_metadata(self) -> tuple[CapabilityPackageCandidate, ...]:
        failed = False
        try:
            return tuple(_candidate(record) for record in self._validated_records())
        except LocalDirectoryCapabilitySourceError:
            raise
        except Exception:
            failed = True
        if failed:
            raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
        raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)

    def open_payload(
        self,
        candidate: CapabilityPackageCandidate,
    ) -> PortableCapabilityPayload:
        failed = False
        try:
            record = self._record_for(candidate)
            self.validate_source_identity(candidate, record.payload)
            return record.payload
        except LocalDirectoryCapabilitySourceError:
            raise
        except Exception:
            failed = True
        if failed:
            raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
        raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)

    def validate_source_identity(
        self,
        candidate: CapabilityPackageCandidate,
        payload: PortableCapabilityPayload,
    ) -> None:
        failed = False
        try:
            if (
                type(candidate) is not CapabilityPackageCandidate
                or type(payload) is not PortableCapabilityPayload
                or candidate.source_kind != SOURCE_KIND
                or payload.manifest.package_ref != candidate.package_ref
                or candidate.payload_sha256 != payload.payload_sha256
            ):
                raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
            records = tuple(
                record
                for record in self._validated_records()
                if record.declaration.package_ref == candidate.package_ref
                and record.declaration.source_id == candidate.source_id
                and record.payload.payload_sha256 == candidate.payload_sha256
            )
            if len(records) != 1:
                raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
        except LocalDirectoryCapabilitySourceError:
            raise
        except Exception:
            failed = True
        if failed:
            raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)

    def load_provider(
        self,
        candidate: CapabilityPackageCandidate,
    ) -> InstalledCapabilityPackage:
        failed = False
        try:
            record = self._record_for(candidate)
            self.validate_source_identity(candidate, record.payload)
            factory = _load_factory(record)
            if not callable(factory):
                raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
            installed = factory()
            if (
                type(installed) is not InstalledCapabilityPackage
                or installed.package_ref != candidate.package_ref
                or installed.payload_sha256 != record.payload.payload_sha256
                or installed.source_id != candidate.source_id
                or installed.source_kind != candidate.source_kind
            ):
                raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
            return installed
        except LocalDirectoryCapabilitySourceError:
            raise
        except Exception:
            failed = True
        if failed:
            raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
        raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)

    def _record_for(
        self,
        candidate: CapabilityPackageCandidate,
    ) -> _LocalRecord:
        if type(candidate) is not CapabilityPackageCandidate:
            raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
        matches = tuple(
            record
            for record in self._validated_records()
            if record.declaration.package_ref == candidate.package_ref
            and record.declaration.source_id == candidate.source_id
        )
        if len(matches) != 1 or candidate.source_kind != SOURCE_KIND:
            raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
        record = matches[0]
        if candidate.payload_sha256 != record.payload.payload_sha256:
            raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
        return record

    def _validated_records(self) -> tuple[_LocalRecord, ...]:
        declarations = self._validated_declarations()
        records = tuple(_record_for_declaration(declaration) for declaration in declarations)
        seen: set[tuple[object, str]] = set()
        for record in records:
            identity = (record.declaration.package_ref, record.declaration.source_id)
            if identity in seen:
                raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
            seen.add(identity)
        return records

    def _validated_declarations(self) -> tuple[CapabilitySourceDeclaration, ...]:
        if not self._declarations:
            raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
        declarations = self._declarations
        for declaration in declarations:
            if (
                type(declaration) is not CapabilitySourceDeclaration
                or declaration.kind != SOURCE_KIND
                or declaration.payload_sha256 is None
            ):
                raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
        identities = tuple(
            (declaration.package_ref, declaration.source_id)
            for declaration in declarations
        )
        if len(set(identities)) != len(identities):
            raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
        return declarations


def _record_for_declaration(declaration: CapabilitySourceDeclaration) -> _LocalRecord:
    locator = _locator(declaration.private_locator)
    root = _canonical_root(locator["root"])
    payload_root = _owned_directory(root, locator["payload_root"])
    module_path = _owned_file(root, locator["module_path"])
    factory_name = _factory_name(locator["factory_name"])
    payload = open_portable_payload(payload_root)
    if (
        payload.manifest.package_ref != declaration.package_ref
        or payload.payload_sha256 != declaration.payload_sha256
    ):
        raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
    return _LocalRecord(
        declaration=declaration,
        root=root,
        payload_root=payload_root,
        module_path=module_path,
        factory_name=factory_name,
        payload=payload,
    )


def _locator(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
    if set(value.keys()) != _LOCATOR_FIELDS:
        raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
    return value


def _canonical_root(value: object) -> Path:
    if not isinstance(value, Path) or not value.is_absolute():
        raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
    root = _canonical_directory(value)
    if value != root:
        raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
    return root


def _canonical_directory(path: Path) -> Path:
    resolved = _resolve_without_symlinks(path)
    if not resolved.is_dir():
        raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
    return resolved


def _owned_directory(root: Path, value: object) -> Path:
    path = _owned_path(root, value)
    if not path.is_dir():
        raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
    return path


def _owned_file(root: Path, value: object) -> Path:
    path = _owned_path(root, value)
    if not path.is_file():
        raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
    return path


def _owned_path(root: Path, value: object) -> Path:
    raw = Path(str(value))
    if not raw.is_absolute() and any(part in {"", ".", ".."} for part in raw.parts):
        raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
    path = _resolve_without_symlinks(raw if raw.is_absolute() else root / raw)
    failed = False
    try:
        path.relative_to(root)
    except ValueError:
        failed = True
    if failed:
        raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
    return path


def _resolve_without_symlinks(path: Path) -> Path:
    absolute = path if path.is_absolute() else Path.cwd() / path
    current = Path(absolute.anchor)
    failed = False
    for part in absolute.parts[1:]:
        if part in {"", "."}:
            continue
        if part == "..":
            raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
        current = current / part
        try:
            mode = current.lstat().st_mode
        except OSError:
            failed = True
            break
        if stat.S_ISLNK(mode):
            failed = True
            break
    if failed:
        raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
    resolved: Path | None = None
    failed = False
    try:
        resolved = absolute.resolve(strict=True)
    except OSError:
        failed = True
    if failed or resolved is None:
        raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
    return resolved


def _factory_name(value: object) -> str:
    if not isinstance(value, str) or not value.isidentifier():
        raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
    return value


def _candidate(record: _LocalRecord) -> CapabilityPackageCandidate:
    declaration = record.declaration
    return CapabilityPackageCandidate(
        package_ref=declaration.package_ref,
        source_id=declaration.source_id,
        source_kind=SOURCE_KIND,
        payload_sha256=record.payload.payload_sha256,
        metadata={},
    )


def _load_factory(record: _LocalRecord) -> object:
    module_name = _scoped_module_name(record)
    module_cache = cast(MutableMapping[str, object], sys.modules)
    had_previous = module_name in module_cache
    previous = module_cache.get(module_name)
    try:
        spec = importlib.util.spec_from_file_location(module_name, record.module_path)
        if spec is None or spec.loader is None:
            raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
        module = importlib.util.module_from_spec(spec)
        module_cache[module_name] = module
        spec.loader.exec_module(module)
        factory = getattr(module, record.factory_name, _MISSING)
        if factory is _MISSING:
            raise LocalDirectoryCapabilitySourceError(_ERROR_MESSAGE)
        return factory
    finally:
        if had_previous:
            module_cache[module_name] = previous
        else:
            module_cache.pop(module_name, None)


def _scoped_module_name(record: _LocalRecord) -> str:
    digest = hashlib.sha256()
    digest.update(record.declaration.source_id.encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(record.module_path).encode("utf-8"))
    return _MODULE_PREFIX + digest.hexdigest()


__all__ = (
    "LocalDirectoryCapabilityPackageSource",
    "LocalDirectoryCapabilitySourceError",
)
