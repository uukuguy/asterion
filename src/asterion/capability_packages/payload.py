"""Descriptor-relative validation for canonical portable payloads."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import sys
from collections import Counter
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from asterion.capabilities.catalog import CapabilityRef
from asterion.capabilities.protocol import (
    CapabilityProtocolError,
    validate_capability_manifest,
)
from asterion.capability_packages.model import PortableCapabilityPayload
from asterion.capability_packages.protocol import (
    BenchmarkSuiteProtocolError,
    CapabilityPackageManifest,
    CapabilityPackageProtocolError,
    validate_benchmark_suite_manifest,
    validate_capability_package_manifest,
)
from asterion.protocol_ordering import is_unicode_scalar_string


class CapabilityPackagePayloadError(ValueError):
    """Raised when a portable payload is not a closed canonical snapshot."""


_DESCRIPTOR = "capability-package.json"
_CAPABILITIES = "capabilities"
_BENCHMARK_SUITES = "benchmark-suites"
_RESOURCES = "resources"
_CONFORMANCE = "conformance"
_KNOWN_ROOT_MEMBERS = frozenset(
    {
        _DESCRIPTOR,
        _CAPABILITIES,
        _BENCHMARK_SUITES,
        _RESOURCES,
        _CONFORMANCE,
    }
)
_SECURE_PAYLOAD_READS_AVAILABLE = (
    sys.platform in {"darwin", "linux"}
    and hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_NOFOLLOW")
    and os.open in os.supports_dir_fd
    and os.listdir in os.supports_fd
    and os.stat in os.supports_dir_fd
    and os.stat in os.supports_follow_symlinks
)


@dataclass(frozen=True, slots=True)
class _PinnedDirectory:
    fd: int
    fingerprint: tuple[int, int, int, int]
    members: tuple[str, ...]


def open_portable_payload(root: Path) -> PortableCapabilityPayload:
    """Validate and open one exact portable payload closure."""

    manifest, digest = _validated_payload(root, expected_manifest=None)
    return PortableCapabilityPayload(
        manifest=manifest,
        payload_sha256=digest,
        resource_root=Path(root),
    )


def canonical_payload_sha256(
    root: Path,
    manifest: CapabilityPackageManifest,
) -> str:
    """Return the location-independent digest of one validated payload."""

    _, digest = _validated_payload(root, expected_manifest=manifest)
    return digest


def _validated_payload(
    root: Path,
    *,
    expected_manifest: CapabilityPackageManifest | None,
) -> tuple[CapabilityPackageManifest, str]:
    if not _SECURE_PAYLOAD_READS_AVAILABLE:
        raise CapabilityPackagePayloadError(
            "secure portable payload validation is unavailable"
        )

    with ExitStack() as descriptors:
        root_fd = _open_root(Path(root), descriptors)
        root_directory = _pin_directory(root_fd)
        pinned_directories = [root_directory]
        root_members = root_directory.members
        if (
            set(root_members) - _KNOWN_ROOT_MEMBERS
            or _DESCRIPTOR not in root_members
        ):
            _invalid()

        descriptor = _read_regular(root_fd, _DESCRIPTOR)
        descriptor_value = _canonical_json_value(descriptor)
        try:
            manifest = validate_capability_package_manifest(
                descriptor_value
            )
        except CapabilityPackageProtocolError as error:
            raise CapabilityPackagePayloadError(
                "portable capability payload is invalid"
            ) from error
        if expected_manifest is not None and manifest != expected_manifest:
            _invalid()

        content_by_name: dict[str, bytes] = {
            _DESCRIPTOR: descriptor,
        }
        capability_documents = _read_json_directory(
            root_fd,
            root_members,
            _CAPABILITIES,
            required=True,
            descriptors=descriptors,
            pinned_directories=pinned_directories,
        )
        capability_refs: list[CapabilityRef] = []
        for relative_name, raw in capability_documents:
            try:
                value = validate_capability_manifest(
                    _canonical_json_value(raw)
                )
            except CapabilityProtocolError as error:
                raise CapabilityPackagePayloadError(
                    "portable capability payload is invalid"
                ) from error
            capability_id = value["capability_id"]
            version = value["version"]
            assert isinstance(capability_id, str)
            assert isinstance(version, str)
            capability_refs.append(CapabilityRef(capability_id, version))
            content_by_name[relative_name] = raw
        if (
            len(capability_refs) != len(set(capability_refs))
            or tuple(sorted(capability_refs)) != manifest.capabilities
        ):
            _invalid()

        suite_documents = _read_json_directory(
            root_fd,
            root_members,
            _BENCHMARK_SUITES,
            required=bool(manifest.benchmark_suites),
            descriptors=descriptors,
            pinned_directories=pinned_directories,
        )
        suite_refs = []
        for relative_name, raw in suite_documents:
            try:
                suite = validate_benchmark_suite_manifest(
                    _canonical_json_value(raw)
                )
            except BenchmarkSuiteProtocolError as error:
                raise CapabilityPackagePayloadError(
                    "portable capability payload is invalid"
                ) from error
            if suite.owner_package != manifest.package_ref:
                _invalid()
            suite_refs.append(suite.suite_ref)
            content_by_name[relative_name] = raw
        if (
            len(suite_refs) != len(set(suite_refs))
            or tuple(sorted(suite_refs)) != manifest.benchmark_suites
        ):
            _invalid()

        resource_documents = _read_directory(
            root_fd,
            root_members,
            _RESOURCES,
            required=bool(manifest.resources),
            descriptors=descriptors,
            pinned_directories=pinned_directories,
        )
        declared_resource_digests = Counter(
            resource.sha256 for resource in manifest.resources
        )
        observed_resource_digests: Counter[str] = Counter()
        json_resource_digests = {
            resource.sha256
            for resource in manifest.resources
            if resource.media_type == "application/json"
            or resource.media_type.endswith("+json")
        }
        for relative_name, raw in resource_documents:
            content_digest = hashlib.sha256(raw).hexdigest()
            observed_resource_digests[content_digest] += 1
            if content_digest in json_resource_digests:
                _canonical_json_value(raw)
            content_by_name[relative_name] = raw
        if observed_resource_digests != declared_resource_digests:
            _invalid()

        conformance_documents = _read_json_directory(
            root_fd,
            root_members,
            _CONFORMANCE,
            required=True,
            descriptors=descriptors,
            pinned_directories=pinned_directories,
        )
        if not conformance_documents:
            _invalid()
        for relative_name, raw in conformance_documents:
            _canonical_json_value(raw)
            content_by_name[relative_name] = raw

        payload_sha256 = _digest_content_map(content_by_name)
        for directory in reversed(pinned_directories):
            _verify_pinned_directory(directory)
        return manifest, payload_sha256


def _open_root(root: Path, descriptors: ExitStack) -> int:
    components = root.parts[1:] if root.is_absolute() else root.parts
    if ".." in components:
        _invalid()

    flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    anchor = "/" if root.is_absolute() else "."
    current = _open_directory(
        anchor,
        parent_fd=None,
        flags=flags,
        descriptors=descriptors,
    )
    for component in components:
        if component in {"", "."}:
            continue
        current = _open_directory(
            component,
            parent_fd=current,
            flags=flags,
            descriptors=descriptors,
        )
    return current


def _open_directory(
    name: str,
    *,
    parent_fd: int | None,
    flags: int,
    descriptors: ExitStack,
) -> int:
    try:
        if parent_fd is None:
            descriptor = os.open(name, flags)
        else:
            descriptor = os.open(name, flags, dir_fd=parent_fd)
    except OSError as error:
        raise CapabilityPackagePayloadError(
            "portable capability payload is invalid"
        ) from error
    descriptors.callback(os.close, descriptor)
    return descriptor


def _read_json_directory(
    root_fd: int,
    root_members: tuple[str, ...],
    directory_name: str,
    *,
    required: bool,
    descriptors: ExitStack,
    pinned_directories: list[_PinnedDirectory],
) -> tuple[tuple[str, bytes], ...]:
    documents = _read_directory(
        root_fd,
        root_members,
        directory_name,
        required=required,
        descriptors=descriptors,
        pinned_directories=pinned_directories,
    )
    if any(Path(relative_name).suffix != ".json" for relative_name, _ in documents):
        _invalid()
    return documents


def _read_directory(
    root_fd: int,
    root_members: tuple[str, ...],
    directory_name: str,
    *,
    required: bool,
    descriptors: ExitStack,
    pinned_directories: list[_PinnedDirectory],
) -> tuple[tuple[str, bytes], ...]:
    present = directory_name in root_members
    if present != required:
        _invalid()
    if not present:
        return ()

    flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    directory_fd = _open_directory(
        directory_name,
        parent_fd=root_fd,
        flags=flags,
        descriptors=descriptors,
    )
    directory = _pin_directory(directory_fd)
    pinned_directories.append(directory)
    return tuple(
        (
            f"{directory_name}/{child}",
            _read_regular(directory_fd, child),
        )
        for child in directory.members
    )


def _pin_directory(directory_fd: int) -> _PinnedDirectory:
    before = _directory_fingerprint(directory_fd)
    members = _list_direct_names(directory_fd)
    after = _directory_fingerprint(directory_fd)
    if before != after:
        _invalid()
    return _PinnedDirectory(directory_fd, after, members)


def _verify_pinned_directory(directory: _PinnedDirectory) -> None:
    before = _directory_fingerprint(directory.fd)
    members = _list_direct_names(directory.fd)
    after = _directory_fingerprint(directory.fd)
    if (
        before != directory.fingerprint
        or members != directory.members
        or after != directory.fingerprint
    ):
        _invalid()


def _directory_fingerprint(
    directory_fd: int,
) -> tuple[int, int, int, int]:
    try:
        details = os.fstat(directory_fd)
    except OSError as error:
        raise CapabilityPackagePayloadError(
            "portable capability payload is invalid"
        ) from error
    if not stat.S_ISDIR(details.st_mode):
        _invalid()
    return (
        details.st_dev,
        details.st_ino,
        details.st_mtime_ns,
        details.st_ctime_ns,
    )


def _list_direct_names(directory_fd: int) -> tuple[str, ...]:
    try:
        names = tuple(os.listdir(directory_fd))
    except OSError as error:
        raise CapabilityPackagePayloadError(
            "portable capability payload is invalid"
        ) from error
    if any(not _safe_direct_name(name) for name in names):
        _invalid()
    return tuple(sorted(names))


def _safe_direct_name(name: str) -> bool:
    return (
        bool(name)
        and name not in {".", ".."}
        and "/" not in name
        and (os.altsep is None or os.altsep not in name)
        and is_unicode_scalar_string(name)
    )


def _read_regular(parent_fd: int, name: str) -> bytes:
    try:
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as error:
        raise CapabilityPackagePayloadError(
            "portable capability payload is invalid"
        ) from error
    if not stat.S_ISREG(before.st_mode):
        _invalid()

    flags = (
        os.O_RDONLY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = -1
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (before.st_dev, before.st_ino)
            != (opened.st_dev, opened.st_ino)
        ):
            _invalid()
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (
            (opened.st_dev, opened.st_ino, opened.st_size)
            != (after.st_dev, after.st_ino, after.st_size)
            or opened.st_mtime_ns != after.st_mtime_ns
            or opened.st_ctime_ns != after.st_ctime_ns
        ):
            _invalid()
        return b"".join(chunks)
    except CapabilityPackagePayloadError:
        raise
    except OSError as error:
        if error.errno == errno.ELOOP:
            _invalid()
        raise CapabilityPackagePayloadError(
            "portable capability payload is invalid"
        ) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _canonical_json_value(raw: bytes) -> object:
    def unique_object(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON member")
            value[key] = item
        return value

    def reject_constant(_: str) -> object:
        raise ValueError("non-finite JSON number")

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
        canonical = (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (UnicodeError, ValueError, TypeError) as error:
        raise CapabilityPackagePayloadError(
            "portable capability payload is invalid"
        ) from error
    if raw != canonical:
        _invalid()
    return value


def _digest_content_map(content_by_name: dict[str, bytes]) -> str:
    payload_digest = hashlib.sha256()
    for relative_name in sorted(content_by_name):
        entry = (
            relative_name.encode("utf-8")
            + b"\0"
            + hashlib.sha256(content_by_name[relative_name]).digest()
        )
        payload_digest.update(len(entry).to_bytes(8, "big"))
        payload_digest.update(entry)
    return payload_digest.hexdigest()


def _invalid() -> None:
    raise CapabilityPackagePayloadError(
        "portable capability payload is invalid"
    )
