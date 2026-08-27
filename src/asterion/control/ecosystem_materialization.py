"""Host-owned exact source storage and sealed ecosystem materialization."""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import secrets
import stat
import sys
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import IO

from asterion.control.ecosystem import (
    EcosystemPortfolio,
    EcosystemPrivateFile,
    EcosystemPrivateResource,
    EcosystemPrivateSourceStore,
)


_ERROR_MESSAGE = "ecosystem source is invalid"
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
_READ_DIRECTORY_FLAGS = os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC
_READ_FILE_FLAGS = os.O_RDONLY | _NOFOLLOW | _CLOEXEC | _NONBLOCK
_WRITE_FILE_FLAGS = (
    os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC
)


class EcosystemMaterializationError(ValueError):
    """Raised when private source materialization cannot remain exact."""


@dataclass(frozen=True, repr=False)
class EcosystemProjection:
    projection_id: str
    portfolio_digest: str
    root: Path
    resource_roots: Mapping[str, Path]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.projection_id, str)
            or not self.projection_id
            or not _is_sha256(self.portfolio_digest)
            or not isinstance(self.root, Path)
            or not self.root.is_absolute()
            or not isinstance(self.resource_roots, Mapping)
            or any(
                not isinstance(key, str)
                or not isinstance(value, Path)
                or not value.is_absolute()
                for key, value in self.resource_roots.items()
            )
        ):
            raise EcosystemMaterializationError(_ERROR_MESSAGE)
        copied = dict(sorted(self.resource_roots.items()))
        object.__setattr__(self, "resource_roots", MappingProxyType(copied))


@dataclass
class _OwnedProjection:
    projection: EcosystemProjection
    root_fd: int | None
    projection_fd: int | None
    identity: tuple[int, int]
    quarantine_name: str
    phase: str = "bound"
    terminal_uncertain: bool = False


class _HeldVerifiedReader:
    def __init__(self, descriptor: int, declaration: EcosystemPrivateFile) -> None:
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_size != declaration.size_bytes
        ):
            raise OSError
        self._descriptor = descriptor
        self._declaration = declaration
        self._remaining = declaration.size_bytes + 1
        self._count = 0
        self._digest = hashlib.sha256()
        self._verified = False

    def fileno(self) -> int:
        return self._descriptor

    def read(self, size: int = -1) -> bytes:
        if self._verified:
            return b""
        if not isinstance(size, int):
            raise TypeError
        requested = self._remaining if size < 0 else min(size, self._remaining)
        if requested == 0:
            self._verify()
            return b""
        value = os.read(self._descriptor, requested)
        self._remaining -= len(value)
        self._count += len(value)
        self._digest.update(value)
        if not value or self._remaining == 0:
            self._verify()
        return value

    def finalize(self) -> None:
        while not self._verified:
            self.read()

    def _verify(self) -> None:
        if (
            self._count != self._declaration.size_bytes
            or self._digest.hexdigest() != self._declaration.sha256
        ):
            raise OSError
        self._verified = True


class FileEcosystemPrivateSourceStore:
    """Open only explicitly declared files below exact host-owned roots."""

    def __init__(
        self,
        *,
        roots: Mapping[str, Path],
        resources: tuple[EcosystemPrivateResource, ...],
    ) -> None:
        failed = False
        root_values: dict[str, Path] = {}
        resource_values: dict[str, EcosystemPrivateResource] = {}
        try:
            if not isinstance(roots, Mapping) or not isinstance(resources, tuple):
                raise TypeError
            for source_id, root in roots.items():
                if (
                    not _is_opaque_id(source_id)
                    or not isinstance(root, Path)
                    or not root.is_absolute()
                    or any(part in {".", ".."} for part in root.parts)
                    or source_id in root_values
                ):
                    raise ValueError
                root_values[source_id] = root
            for resource in resources:
                if (
                    type(resource) is not EcosystemPrivateResource
                    or resource.resource_id in resource_values
                ):
                    raise ValueError
                resource_values[resource.resource_id] = resource
            if {item.source_id for item in resource_values.values()} != set(root_values):
                raise ValueError
        except BaseException:
            failed = True
        if failed:
            raise EcosystemMaterializationError(_ERROR_MESSAGE)
        self._roots = MappingProxyType(dict(sorted(root_values.items())))
        self._resources = MappingProxyType(dict(sorted(resource_values.items())))

    def private_resource(self, resource_id: str) -> EcosystemPrivateResource:
        value = self._resources.get(resource_id)
        if value is None:
            raise EcosystemMaterializationError(_ERROR_MESSAGE)
        return value

    @contextmanager
    def open_file(
        self,
        resource_id: str,
        relative_path: str,
    ) -> Iterator[IO[bytes]]:
        descriptor: int | None = None
        stream: _HeldVerifiedReader | None = None
        failed = False
        try:
            resource = self._resources.get(resource_id)
            if resource is None:
                raise ValueError
            declarations = tuple(
                item for item in resource.files if item.relative_path == relative_path
            )
            if len(declarations) != 1:
                raise ValueError
            declaration = declarations[0]
            root = self._roots.get(resource.source_id)
            if root is None:
                raise ValueError
            descriptor = _open_regular_file(root, declaration.relative_path)
            stream = _HeldVerifiedReader(descriptor, declaration)
        except BaseException:
            failed = True
        if failed or descriptor is None or stream is None:
            _close_quietly(descriptor)
            raise EcosystemMaterializationError(_ERROR_MESSAGE)

        consumer_failed = False
        try:
            yield stream
        except BaseException:
            consumer_failed = True
            raise
        finally:
            validation_failed = False
            if not consumer_failed:
                try:
                    stream.finalize()
                except BaseException:
                    validation_failed = True
            close_failed = not _close_quietly(descriptor)
            if (validation_failed or close_failed) and not consumer_failed:
                raise EcosystemMaterializationError(_ERROR_MESSAGE)


class SealedEcosystemMaterializer:
    """Copy a portfolio into one atomically published private projection."""

    def __init__(self, private_root: Path) -> None:
        if (
            not isinstance(private_root, Path)
            or not private_root.is_absolute()
            or private_root == private_root.parent
            or any(part in {".", ".."} for part in private_root.parts)
        ):
            raise EcosystemMaterializationError(_ERROR_MESSAGE)
        self._private_root = private_root
        self._owned: dict[int, _OwnedProjection] = {}
        self._lock = threading.Lock()

    def materialize(
        self,
        portfolio: EcosystemPortfolio,
        store: EcosystemPrivateSourceStore,
    ) -> EcosystemProjection:
        root_fd: int | None = None
        staging_fd: int | None = None
        owned_name: str | None = None
        owned_identity: tuple[int, int] | None = None
        quarantine_name: str | None = None
        projection: EcosystemProjection | None = None
        failed = False
        try:
            if type(portfolio) is not EcosystemPortfolio:
                raise TypeError
            declarations = _validated_declarations(portfolio, store)
            root_fd = _open_or_create_private_root(self._private_root)
            staging_name = f".staging-{secrets.token_hex(16)}"
            quarantine_name = f".cleanup-{secrets.token_hex(16)}"
            os.mkdir(staging_name, 0o700, dir_fd=root_fd)
            owned_name = staging_name
            created_details = os.stat(
                staging_name, dir_fd=root_fd, follow_symlinks=False
            )
            if not stat.S_ISDIR(created_details.st_mode):
                raise OSError
            owned_identity = _identity(created_details)
            staging_fd = os.open(staging_name, _READ_DIRECTORY_FLAGS, dir_fd=root_fd)
            staging_details = os.fstat(staging_fd)
            if (
                not stat.S_ISDIR(staging_details.st_mode)
                or _identity(staging_details) != owned_identity
                or stat.S_IMODE(staging_details.st_mode) != 0o700
                or staging_details.st_uid != os.getuid()
            ):
                raise OSError
            os.fsync(root_fd)

            resource_paths: dict[str, Path] = {}
            for resource, declaration in declarations:
                resource_fd = _create_owned_directory_at(
                    staging_fd, declaration.resource_id
                )
                try:
                    for private_file in declaration.files:
                        with store.open_file(
                            declaration.resource_id, private_file.relative_path
                        ) as source:
                            _copy_declared_file(resource_fd, private_file, source)
                    os.fsync(resource_fd)
                finally:
                    os.close(resource_fd)
                resource_paths[resource.resource_id] = (
                    self._private_root / portfolio.digest / resource.resource_id
                )

            os.fsync(staging_fd)
            projection = EcosystemProjection(
                projection_id=portfolio.digest,
                portfolio_digest=portfolio.digest,
                root=self._private_root / portfolio.digest,
                resource_roots=resource_paths,
            )
            _atomic_publish(root_fd, staging_name, projection.projection_id)
            owned_name = projection.projection_id
            os.fsync(root_fd)
        except BaseException:
            failed = True

        if failed or root_fd is None or staging_fd is None or projection is None:
            if (
                root_fd is not None
                and owned_name is not None
                and owned_identity is not None
            ):
                try:
                    _remove_owned_tree(
                        root_fd,
                        owned_name,
                        owned_identity,
                        staging_fd,
                        quarantine_name,
                    )
                    os.fsync(root_fd)
                except BaseException:
                    pass
            _close_quietly(staging_fd)
            _close_quietly(root_fd)
            raise EcosystemMaterializationError(_ERROR_MESSAGE)

        assert owned_identity is not None
        owned = _OwnedProjection(
            projection=projection,
            root_fd=root_fd,
            projection_fd=staging_fd,
            identity=owned_identity,
            quarantine_name=quarantine_name,
        )
        with self._lock:
            if id(projection) in self._owned:
                failed = True
            else:
                self._owned[id(projection)] = owned
        if failed:
            try:
                _remove_owned_tree(
                    root_fd,
                    projection.projection_id,
                    owned_identity,
                    staging_fd,
                    quarantine_name,
                )
            except BaseException:
                pass
            _close_quietly(staging_fd)
            _close_quietly(root_fd)
            raise EcosystemMaterializationError(_ERROR_MESSAGE)
        return projection

    def close(self, projection: EcosystemProjection) -> None:
        with self._lock:
            owned = self._owned.get(id(projection))
            if owned is None:
                return
            if owned.projection is not projection:
                raise EcosystemMaterializationError(_ERROR_MESSAGE)
            failed = False
            if owned.terminal_uncertain:
                failed = True
            elif owned.phase == "bound":
                try:
                    if owned.root_fd is None:
                        raise OSError
                    _remove_owned_tree(
                        owned.root_fd,
                        owned.projection.projection_id,
                        owned.identity,
                        owned.projection_fd,
                        owned.quarantine_name,
                    )
                    owned.phase = "tree-removed-pending-fsync"
                except BaseException:
                    failed = True
            if not failed and owned.phase == "tree-removed-pending-fsync":
                try:
                    if owned.root_fd is None:
                        raise OSError
                    os.fsync(owned.root_fd)
                except BaseException:
                    failed = True
                else:
                    close_failed = _close_owned_descriptors(owned)
                    if close_failed:
                        owned.terminal_uncertain = True
                        failed = True
                    else:
                        owned.phase = "closed"
                        del self._owned[id(projection)]
        if failed:
            raise EcosystemMaterializationError(_ERROR_MESSAGE)


def _validated_declarations(
    portfolio: EcosystemPortfolio,
    store: EcosystemPrivateSourceStore,
) -> tuple[tuple[object, EcosystemPrivateResource], ...]:
    values: list[tuple[object, EcosystemPrivateResource]] = []
    for resource in portfolio.resources:
        declaration = store.private_resource(resource.resource_id)
        if (
            type(declaration) is not EcosystemPrivateResource
            or declaration.resource_id != resource.resource_id
            or declaration.source_id != resource.source.source_id
            or _resource_digest(declaration.files) != resource.content_sha256
        ):
            raise EcosystemMaterializationError(_ERROR_MESSAGE)
        values.append((resource, declaration))
    return tuple(values)


def _resource_digest(files: tuple[EcosystemPrivateFile, ...]) -> str:
    encoded = json.dumps(
        [
            {
                "relative_path": item.relative_path,
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
            }
            for item in files
        ],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _open_regular_file(root: Path, relative_path: str) -> int:
    directory_fd = _open_absolute_directory(root)
    try:
        parts = relative_path.split("/")
        for component in parts[:-1]:
            next_fd, _ = _open_directory_at(directory_fd, component)
            os.close(directory_fd)
            directory_fd = next_fd
        descriptor = os.open(parts[-1], _READ_FILE_FLAGS, dir_fd=directory_fd)
        try:
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode):
                raise OSError
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor
    finally:
        os.close(directory_fd)


def _open_absolute_directory(path: Path) -> int:
    if _NOFOLLOW == 0 or not path.is_absolute():
        raise OSError
    descriptor = os.open(path.anchor, _READ_DIRECTORY_FLAGS)
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISDIR(details.st_mode):
            raise OSError
        for component in path.parts[1:]:
            next_fd, _ = _open_directory_at(descriptor, component)
            os.close(descriptor)
            descriptor = next_fd
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_or_create_private_root(path: Path) -> int:
    parent_fd = _open_absolute_directory(path.parent)
    created = False
    try:
        try:
            os.mkdir(path.name, 0o700, dir_fd=parent_fd)
            created = True
            os.fsync(parent_fd)
        except FileExistsError:
            pass
        descriptor, details = _open_directory_at(parent_fd, path.name)
        try:
            if (
                stat.S_IMODE(details.st_mode) != 0o700
                or details.st_uid != os.getuid()
            ):
                raise OSError
            if created:
                os.fsync(descriptor)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise
    finally:
        os.close(parent_fd)


def _create_owned_directory_at(parent_fd: int, name: str) -> int:
    os.mkdir(name, 0o700, dir_fd=parent_fd)
    os.fsync(parent_fd)
    descriptor, details = _open_directory_at(parent_fd, name)
    try:
        if (
            stat.S_IMODE(details.st_mode) != 0o700
            or details.st_uid != os.getuid()
        ):
            raise OSError
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_or_create_owned_directory_at(parent_fd: int, name: str) -> int:
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
        os.fsync(parent_fd)
    except FileExistsError:
        pass
    descriptor, details = _open_directory_at(parent_fd, name)
    try:
        if (
            stat.S_IMODE(details.st_mode) != 0o700
            or details.st_uid != os.getuid()
        ):
            raise OSError
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _copy_declared_file(
    resource_fd: int,
    declaration: EcosystemPrivateFile,
    source: IO[bytes],
) -> None:
    parent_fd = os.dup(resource_fd)
    try:
        parts = declaration.relative_path.split("/")
        for component in parts[:-1]:
            next_fd = _open_or_create_owned_directory_at(parent_fd, component)
            os.close(parent_fd)
            parent_fd = next_fd
        descriptor = os.open(
            parts[-1],
            _WRITE_FILE_FLAGS,
            0o600,
            dir_fd=parent_fd,
        )
        try:
            os.fchmod(descriptor, 0o600)
            digest = hashlib.sha256()
            copied = 0
            remaining = declaration.size_bytes + 1
            while remaining:
                chunk = source.read(min(64 * 1024, remaining))
                if not isinstance(chunk, bytes):
                    raise OSError
                if not chunk:
                    break
                remaining -= len(chunk)
                copied += len(chunk)
                digest.update(chunk)
                view = memoryview(chunk)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise OSError
                    view = view[written:]
            if copied != declaration.size_bytes or digest.hexdigest() != declaration.sha256:
                raise OSError
            details = os.fstat(descriptor)
            if (
                not stat.S_ISREG(details.st_mode)
                or details.st_size != declaration.size_bytes
                or stat.S_IMODE(details.st_mode) != 0o600
            ):
                raise OSError
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def _atomic_publish(parent_fd: int, source: str, target: str) -> None:
    _atomic_move_no_replace(parent_fd, source, parent_fd, target)


def _atomic_move_no_replace(
    source_fd: int,
    source: str,
    target_fd: int,
    target: str,
) -> None:
    source_bytes = os.fsencode(source)
    target_bytes = os.fsencode(target)
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        function = getattr(library, "renameatx_np", None)
        if function is None:
            raise OSError(errno.ENOSYS, "atomic publish unavailable")
        function.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        function.restype = ctypes.c_int
        result = function(source_fd, source_bytes, target_fd, target_bytes, 0x00000004)
    else:
        function = getattr(library, "renameat2", None)
        if function is None:
            raise OSError(errno.ENOSYS, "atomic publish unavailable")
        function.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        function.restype = ctypes.c_int
        result = function(source_fd, source_bytes, target_fd, target_bytes, 1)
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))


def _remove_owned_tree(
    parent_fd: int,
    name: str,
    expected_identity: tuple[int, int],
    owned_fd: int | None,
    quarantine_name: str | None,
) -> None:
    if quarantine_name is None:
        raise OSError
    if owned_fd is not None:
        held_details = os.fstat(owned_fd)
        if (
            not stat.S_ISDIR(held_details.st_mode)
            or _identity(held_details) != expected_identity
        ):
            raise OSError

    descriptor: int | None = None
    try:
        descriptor, details = _open_directory_at(parent_fd, quarantine_name)
    except FileNotFoundError:
        try:
            _atomic_move_no_replace(parent_fd, name, parent_fd, quarantine_name)
        except FileNotFoundError:
            raise OSError
        moved = os.stat(quarantine_name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISDIR(moved.st_mode) or _identity(moved) != expected_identity:
            try:
                _atomic_move_no_replace(parent_fd, quarantine_name, parent_fd, name)
            except BaseException:
                raise OSError
            raise OSError
        descriptor, details = _open_directory_at(parent_fd, quarantine_name)
    if _identity(details) != expected_identity:
        os.close(descriptor)
        raise OSError
    try:
        _remove_directory_contents(owned_fd if owned_fd is not None else descriptor)
        os.rmdir(quarantine_name, dir_fd=parent_fd)
    finally:
        os.close(descriptor)


def _open_directory_at(
    parent_fd: int,
    name: str,
) -> tuple[int, os.stat_result]:
    descriptor = os.open(name, _READ_DIRECTORY_FLAGS, dir_fd=parent_fd)
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISDIR(details.st_mode):
            raise OSError
        return descriptor, details
    except BaseException:
        os.close(descriptor)
        raise


def _remove_directory_contents(directory_fd: int) -> None:
    for name in os.listdir(directory_fd):
        details = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISDIR(details.st_mode):
            child_fd = os.open(name, _READ_DIRECTORY_FLAGS, dir_fd=directory_fd)
            try:
                child_details = os.fstat(child_fd)
                if _identity(details) != _identity(child_details):
                    raise OSError
                _remove_directory_contents(child_fd)
            finally:
                os.close(child_fd)
            current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if _identity(current) != _identity(details):
                raise OSError
            os.rmdir(name, dir_fd=directory_fd)
        else:
            current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if _identity(current) != _identity(details):
                raise OSError
            os.unlink(name, dir_fd=directory_fd)
    os.fsync(directory_fd)


def _identity(details: os.stat_result) -> tuple[int, int]:
    return details.st_dev, details.st_ino


def _close_quietly(descriptor: int | None) -> bool:
    if descriptor is None:
        return True
    try:
        os.close(descriptor)
    except OSError:
        return False
    return True


def _close_owned_descriptors(owned: _OwnedProjection) -> bool:
    failed = False
    for attribute in ("projection_fd", "root_fd"):
        descriptor = getattr(owned, attribute)
        setattr(owned, attribute, None)
        if descriptor is None:
            continue
        try:
            os.close(descriptor)
        except BaseException:
            failed = True
    return failed


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_opaque_id(value: object) -> bool:
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        return False
    return value[0].isalnum() and all(
        character.isalnum() or character in "._:-" for character in value
    )
