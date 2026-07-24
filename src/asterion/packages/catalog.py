"""Deterministic discovery for portable local framework packages."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from asterion.packages.protocol import PackageProtocolError, validate_package_manifest


class PackageCatalogError(ValueError):
    """Raised when local package discovery or selection is ambiguous or invalid."""


@dataclass(frozen=True, order=True)
class PackageRef:
    package_id: str
    version: str


@dataclass(frozen=True)
class CatalogEntry:
    ref: PackageRef
    source: Path
    manifest: Mapping[str, object]


@dataclass(frozen=True)
class PackageCatalog:
    entries: tuple[CatalogEntry, ...]

    def select(
        self, refs: Iterable[PackageRef]
    ) -> tuple[Mapping[str, object], ...]:
        """Return fresh manifests for exact package identities in stable order."""

        requested = list(refs)
        if len(requested) != len(set(requested)):
            raise PackageCatalogError("duplicate package selection")
        entries = {entry.ref: entry for entry in self.entries}
        missing = next((ref for ref in requested if ref not in entries), None)
        if missing is not None:
            raise PackageCatalogError(
                f"unknown package identity: {missing.package_id}@{missing.version}"
            )
        return tuple(
            deepcopy(dict(entries[ref].manifest)) for ref in sorted(requested)
        )


def discover_packages(roots: Iterable[Path]) -> PackageCatalog:
    """Discover validated direct JSON children under explicit local roots."""

    canonical_roots = _canonicalize_roots(roots)
    entries: list[CatalogEntry] = []
    identities: set[PackageRef] = set()
    for root in canonical_roots:
        try:
            children = sorted(root.iterdir())
        except OSError as error:
            raise PackageCatalogError(f"catalog root is invalid: {root}") from error
        for source in children:
            if source.suffix != ".json":
                continue
            if source.is_symlink():
                raise PackageCatalogError(f"package document is a symlink: {source}")
            if not source.is_file():
                continue
            try:
                manifest = json.loads(source.read_text())
            except (OSError, json.JSONDecodeError) as error:
                raise PackageCatalogError(
                    f"package document is invalid: {source}"
                ) from error
            if not isinstance(manifest, dict):
                raise PackageCatalogError(f"package document is invalid: {source}")
            try:
                validate_package_manifest(manifest)
            except PackageProtocolError as error:
                raise PackageCatalogError(
                    f"package document is invalid: {source}"
                ) from error
            package_id = manifest["package_id"]
            version = manifest["version"]
            assert isinstance(package_id, str) and isinstance(version, str)
            ref = PackageRef(package_id, version)
            if ref in identities:
                raise PackageCatalogError(
                    f"duplicate package identity: {package_id}@{version}"
                )
            identities.add(ref)
            entries.append(
                CatalogEntry(
                    ref=ref,
                    source=source.resolve(strict=True),
                    manifest=manifest,
                )
            )
    return PackageCatalog(
        entries=tuple(sorted(entries, key=lambda entry: (entry.ref, str(entry.source))))
    )


def _canonicalize_roots(roots: Iterable[Path]) -> list[Path]:
    canonical: list[Path] = []
    seen: set[Path] = set()
    for value in roots:
        root = Path(value)
        if root.is_symlink():
            raise PackageCatalogError(f"catalog root is a symlink: {root}")
        try:
            resolved = root.resolve(strict=True)
        except OSError as error:
            raise PackageCatalogError(f"catalog root is invalid: {root}") from error
        if not resolved.is_dir():
            raise PackageCatalogError(f"catalog root is invalid: {root}")
        if resolved in seen:
            raise PackageCatalogError(f"duplicate catalog root: {resolved}")
        seen.add(resolved)
        canonical.append(resolved)
    return sorted(canonical)
