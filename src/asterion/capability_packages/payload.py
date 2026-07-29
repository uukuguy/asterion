"""Descriptor-relative validation for portable capability-package payloads."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import sys
from collections.abc import Callable, Iterable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from asterion.capabilities.catalog import CapabilityRef
from asterion.capabilities.protocol import (
    CapabilityProtocolError,
    validate_capability_manifest,
)
from asterion.capability_packages.model import PortableCapabilityPayload
from asterion.capability_packages.protocol import (
    BenchmarkSuiteProtocolError,
    BenchmarkSuiteManifest,
    BenchmarkSuiteRef,
    CapabilityPackageManifest,
    CapabilityPackageProtocolError,
    validate_benchmark_suite_manifest,
    validate_capability_package_manifest,
)
from asterion.protocol_ordering import is_unicode_scalar_string


class CapabilityPackagePayloadError(ValueError):
    """Raised when a portable capability-package payload is invalid."""


@dataclass(frozen=True, slots=True)
class _PinnedDirectory:
    fd: int
    identity: tuple[int, int]


_PINNED_PAYLOAD_AVAILABLE = (
    sys.platform in {"darwin", "linux"}
    and hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_NOFOLLOW")
    and os.open in os.supports_dir_fd
    and os.listdir in os.supports_fd
    and os.stat in os.supports_dir_fd
    and os.stat in os.supports_follow_symlinks
)

_ROOT_CHILDREN = frozenset(
    {
        "benchmark-suites",
        "capabilities",
        "capability-package.json",
        "conformance",
        "resources",
    }
)
_T = TypeVar("_T")


def open_portable_payload(root: Path) -> PortableCapabilityPayload:
    """Validate one portable payload root and return its immutable identity."""

    manifest, payload_sha256 = _validated_payload(root, expected_manifest=None)
    return PortableCapabilityPayload(
        manifest=manifest,
        payload_sha256=payload_sha256,
        resource_root=Path(root),
    )


def canonical_payload_sha256(root: Path, manifest: CapabilityPackageManifest) -> str:
    """Return the canonical location-independent payload digest for ``root``."""

    _, payload_sha256 = _validated_payload(root, expected_manifest=manifest)
    return payload_sha256


def _validated_payload(
    root: Path,
    *,
    expected_manifest: CapabilityPackageManifest | None,
) -> tuple[CapabilityPackageManifest, str]:
    if not _PINNED_PAYLOAD_AVAILABLE:
        raise CapabilityPackagePayloadError(
            "secure capability payload access is unavailable"
        )

    try:
        with ExitStack() as descriptors:
            pinned_root = _open_root(Path(root), descriptors)
            return _validate_pinned_payload(
                pinned_root,
                expected_manifest=expected_manifest,
                descriptors=descriptors,
            )
    except CapabilityPackagePayloadError:
        raise
    except Exception:
        pass
    raise CapabilityPackagePayloadError("capability package payload is invalid")


def _validate_pinned_payload(
    root: _PinnedDirectory,
    *,
    expected_manifest: CapabilityPackageManifest | None,
    descriptors: ExitStack,
) -> tuple[CapabilityPackageManifest, str]:
    _validate_root_children(root)
    package_bytes = _read_regular_file(root, "capability-package.json")
    package_value = _loads_canonical_json(package_bytes)
    manifest = _validate_package_manifest(package_value)
    if expected_manifest is not None and manifest != _snapshot_manifest(expected_manifest):
        raise CapabilityPackagePayloadError("capability package payload is invalid")

    contents: dict[str, bytes] = {"capability-package.json": package_bytes}

    capability_dir = _open_child_directory(root, "capabilities", descriptors)
    capability_contents = _validate_capability_children(capability_dir, manifest)
    contents.update(
        {
            f"capabilities/{name}": content
            for name, content in capability_contents.items()
        }
    )

    suite_dir = _open_child_directory(root, "benchmark-suites", descriptors)
    suite_contents = _validate_benchmark_suite_children(suite_dir, manifest)
    contents.update(
        {
            f"benchmark-suites/{name}": content
            for name, content in suite_contents.items()
        }
    )

    resource_dir = _open_child_directory(root, "resources", descriptors)
    resource_contents = _validate_resource_children(resource_dir, manifest)
    contents.update(
        {
            f"resources/{name}": content
            for name, content in resource_contents.items()
        }
    )

    conformance_dir = _open_child_directory(root, "conformance", descriptors)
    conformance_contents = _validate_conformance_children(conformance_dir)
    contents.update(
        {
            f"conformance/{name}": content
            for name, content in conformance_contents.items()
        }
    )

    return manifest, _digest_contents(contents)


def _validate_root_children(root: _PinnedDirectory) -> None:
    children = _list_children(root)
    if set(children) != _ROOT_CHILDREN:
        raise CapabilityPackagePayloadError("capability package payload is invalid")


def _validate_capability_children(
    directory: _PinnedDirectory,
    manifest: CapabilityPackageManifest,
) -> Mapping[str, bytes]:
    contents: dict[str, bytes] = {}
    refs: list[CapabilityRef] = []
    for name in _list_children(directory):
        content = _read_json_child(directory, name)
        value = _loads_canonical_json(content)
        parsed = _validate_capability_manifest(value)
        capability_id = parsed["capability_id"]
        version = parsed["version"]
        assert isinstance(capability_id, str) and isinstance(version, str)
        ref = CapabilityRef(capability_id, version)
        if ref in refs:
            raise CapabilityPackagePayloadError("capability package payload is invalid")
        refs.append(ref)
        contents[name] = content
    if tuple(sorted(refs)) != manifest.capabilities:
        raise CapabilityPackagePayloadError("capability package payload is invalid")
    return contents


def _validate_benchmark_suite_children(
    directory: _PinnedDirectory,
    manifest: CapabilityPackageManifest,
) -> Mapping[str, bytes]:
    contents: dict[str, bytes] = {}
    refs: list[BenchmarkSuiteRef] = []
    for name in _list_children(directory):
        content = _read_json_child(directory, name)
        value = _loads_canonical_json(content)
        parsed = _validate_benchmark_suite_manifest(value)
        ref = parsed.suite_ref
        if ref in refs:
            raise CapabilityPackagePayloadError("capability package payload is invalid")
        if parsed.owner_package != manifest.package_ref:
            raise CapabilityPackagePayloadError("capability package payload is invalid")
        refs.append(ref)
        contents[name] = content
    if tuple(sorted(refs)) != manifest.benchmark_suites:
        raise CapabilityPackagePayloadError("capability package payload is invalid")
    return contents


def _validate_resource_children(
    directory: _PinnedDirectory,
    manifest: CapabilityPackageManifest,
) -> Mapping[str, bytes]:
    resources = {resource.resource_id: resource for resource in manifest.resources}
    names = _list_children(directory)
    if set(names) != set(resources):
        raise CapabilityPackagePayloadError("capability package payload is invalid")
    contents: dict[str, bytes] = {}
    for name in names:
        content = _read_regular_file(directory, name)
        resource = resources[name]
        if hashlib.sha256(content).hexdigest() != resource.sha256:
            raise CapabilityPackagePayloadError("capability package payload is invalid")
        contents[name] = content
    return contents


def _validate_conformance_children(directory: _PinnedDirectory) -> Mapping[str, bytes]:
    contents: dict[str, bytes] = {}
    for name in _list_children(directory):
        content = _read_json_child(directory, name)
        _loads_canonical_json(content)
        contents[name] = content
    return contents


def _open_root(root: Path, descriptors: ExitStack) -> _PinnedDirectory:
    if root == Path(""):
        components: tuple[str, ...] = ()
    else:
        components = root.parts[1:] if root.is_absolute() else root.parts
    if ".." in components:
        raise CapabilityPackagePayloadError("capability package payload is invalid")

    anchor = "/" if root.is_absolute() else "."
    current = _open_directory_at(
        anchor,
        parent_fd=None,
        descriptors=descriptors,
    )
    for component in components:
        if component in {"", "."}:
            continue
        current = _open_directory_at(
            component,
            parent_fd=current.fd,
            descriptors=descriptors,
        )
    return current


def _open_child_directory(
    parent: _PinnedDirectory,
    name: str,
    descriptors: ExitStack,
) -> _PinnedDirectory:
    return _open_directory_at(name, parent_fd=parent.fd, descriptors=descriptors)


def _open_directory_at(
    name: str,
    *,
    parent_fd: int | None,
    descriptors: ExitStack,
) -> _PinnedDirectory:
    flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = -1
    try:
        if parent_fd is None:
            descriptor = os.open(name, flags)
        else:
            descriptor = os.open(name, flags, dir_fd=parent_fd)
        details = os.fstat(descriptor)
        if not stat.S_ISDIR(details.st_mode):
            raise OSError(errno.ENOTDIR, "not a directory")
        identity = (details.st_dev, details.st_ino)
    except OSError:
        if descriptor >= 0:
            os.close(descriptor)
        pass
    else:
        descriptors.callback(os.close, descriptor)
        return _PinnedDirectory(fd=descriptor, identity=identity)
    raise CapabilityPackagePayloadError("capability package payload is invalid")


def _list_children(directory: _PinnedDirectory) -> tuple[str, ...]:
    failed = False
    children: list[str] = []
    try:
        children = os.listdir(directory.fd)
    except Exception:
        failed = True
    if failed:
        raise CapabilityPackagePayloadError("capability package payload is invalid")
    if any(
        not isinstance(name, str)
        or name in {"", ".", ".."}
        or "/" in name
        or not is_unicode_scalar_string(name)
        for name in children
    ):
        raise CapabilityPackagePayloadError("capability package payload is invalid")
    return tuple(sorted(children))


def _read_json_child(directory: _PinnedDirectory, name: str) -> bytes:
    if Path(name).suffix != ".json":
        raise CapabilityPackagePayloadError("capability package payload is invalid")
    return _read_regular_file(directory, name)


def _read_regular_file(directory: _PinnedDirectory, name: str) -> bytes:
    initial_identity: tuple[int, int] | None = None
    descriptor = -1
    failed = False
    try:
        initial = os.stat(name, dir_fd=directory.fd, follow_symlinks=False)
        if not stat.S_ISREG(initial.st_mode):
            failed = True
        else:
            initial_identity = (initial.st_dev, initial.st_ino)
            flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
            descriptor = os.open(name, flags, dir_fd=directory.fd)
            opened = os.fstat(descriptor)
            opened_identity = (opened.st_dev, opened.st_ino)
            if not stat.S_ISREG(opened.st_mode) or opened_identity != initial_identity:
                failed = True
    except OSError:
        failed = True
    if failed:
        if descriptor >= 0:
            os.close(descriptor)
        raise CapabilityPackagePayloadError("capability package payload is invalid")

    try:
        content = _read_descriptor_bytes(descriptor)
    finally:
        os.close(descriptor)
    return content


def _read_descriptor_bytes(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    failed = False
    try:
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    except OSError:
        failed = True
    if failed:
        raise CapabilityPackagePayloadError("capability package payload is invalid")
    return b"".join(chunks)


def _loads_canonical_json(content: bytes) -> object:
    parsed: object | None = None
    failed = False
    try:
        raw = content.decode("utf-8")
        parsed = json.loads(raw, object_pairs_hook=_unique_json_object)
        canonical = (
            json.dumps(
                parsed,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        if canonical != content:
            failed = True
    except Exception:
        failed = True
    if failed:
        raise CapabilityPackagePayloadError("capability package payload is invalid")
    return parsed


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _validate_package_manifest(value: object) -> CapabilityPackageManifest:
    return _validate_with_body_free_errors(
        validate_capability_package_manifest,
        value,
        (CapabilityPackageProtocolError,),
    )


def _validate_capability_manifest(value: object) -> Mapping[str, object]:
    return _validate_with_body_free_errors(
        validate_capability_manifest,
        value,
        (CapabilityProtocolError,),
    )


def _validate_benchmark_suite_manifest(value: object) -> BenchmarkSuiteManifest:
    return _validate_with_body_free_errors(
        validate_benchmark_suite_manifest,
        value,
        (BenchmarkSuiteProtocolError,),
    )


def _snapshot_manifest(manifest: CapabilityPackageManifest) -> CapabilityPackageManifest:
    return _validate_package_manifest(
        {
            "protocol": "asterion.capability-package/v1",
            "package_id": manifest.package_ref.package_id,
            "version": manifest.package_ref.version,
            "capabilities": [
                {
                    "capability_id": capability.capability_id,
                    "version": capability.version,
                }
                for capability in manifest.capabilities
            ],
            "benchmark_suites": [
                {"suite_id": suite.suite_id, "version": suite.version}
                for suite in manifest.benchmark_suites
            ],
            "resources": [
                {
                    "resource_id": resource.resource_id,
                    "media_type": resource.media_type,
                    "sha256": resource.sha256,
                }
                for resource in manifest.resources
            ],
        }
    )


def _validate_with_body_free_errors(
    validator: Callable[[object], _T],
    value: object,
    expected_errors: Iterable[type[Exception]],
) -> _T:
    parsed: _T | None = None
    failed = False
    try:
        parsed = validator(value)
    except tuple(expected_errors):
        failed = True
    if failed or parsed is None:
        raise CapabilityPackagePayloadError("capability package payload is invalid")
    return parsed


def _digest_contents(contents: Mapping[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name in sorted(contents):
        encoded_name = name.encode("utf-8")
        content_digest = hashlib.sha256(contents[name]).digest()
        entry = encoded_name + b"\0" + content_digest
        digest.update(len(entry).to_bytes(8, "big"))
        digest.update(entry)
    return digest.hexdigest()


__all__ = (
    "CapabilityPackagePayloadError",
    "canonical_payload_sha256",
    "open_portable_payload",
)
