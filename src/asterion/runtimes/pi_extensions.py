"""Exact host-resolved extension bindings and pinned process resources."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from asterion.immutable import RedactedImmutableMapping


_IDENTITY = re.compile(r"[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*")
_SOURCE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.mjs")
_STATIC_IMPORT = re.compile(
    r"\bimport\s+(?:(?:[^\"'\n;]+?)\s+from\s+)?[\"']([^\"']+)[\"']\s*;?"
)
_REEXPORT = re.compile(
    r"\bexport\s*(?:\{.*?\}|\*)(?:\s+as\s+[A-Za-z_$][\w$]*)?"
    r"\s*from\s*[\"']",
    re.DOTALL,
)
_SOURCE_FD = "ASTERION_PI_EXTENSION_SOURCE_FD"
_SOURCE_NAME_ENV = "ASTERION_PI_EXTENSION_SOURCE_NAME"
_SOURCE_SHA256 = "ASTERION_PI_EXTENSION_SOURCE_SHA256"
_RESERVED_ENVIRONMENT_PREFIX = "ASTERION_PI_EXTENSION_"
_LOADER_FILENAME = "asterion_pi_extension_loader.mjs"
_MAX_SOURCE_BYTES = 4 * 1024 * 1024


def pi_extension_loader_path() -> Path:
    """Return the installed Asterion-owned pinned-extension loader path."""

    return Path(__file__).resolve().parent / "resources" / _LOADER_FILENAME


@dataclass(frozen=True, repr=False, slots=True)
class PiExtensionBinding:
    extension_id: str
    path: Path
    capabilities: tuple[str, ...]
    inherited_fds: tuple[int, ...]
    environment: Mapping[str, str]

    def __post_init__(self) -> None:
        if (
            type(self.extension_id) is not str
            or _IDENTITY.fullmatch(self.extension_id) is None
            or not isinstance(self.path, Path)
            or not self.path.is_absolute()
        ):
            raise ValueError("Pi extension binding is invalid")
        try:
            resolved = self.path.resolve(strict=True)
        except OSError:
            raise ValueError("Pi extension binding is invalid") from None
        if resolved != self.path or not self.path.is_file():
            raise ValueError("Pi extension binding is invalid")
        if (
            type(self.capabilities) is not tuple
            or not self.capabilities
            or any(
                type(capability) is not str
                or _IDENTITY.fullmatch(capability) is None
                for capability in self.capabilities
            )
            or tuple(sorted(set(self.capabilities))) != self.capabilities
        ):
            raise ValueError("Pi extension binding is invalid")
        if (
            type(self.inherited_fds) is not tuple
            or any(type(fd) is not int or fd < 3 for fd in self.inherited_fds)
            or tuple(sorted(set(self.inherited_fds))) != self.inherited_fds
        ):
            raise ValueError("Pi extension binding is invalid")
        if not isinstance(self.environment, Mapping):
            raise ValueError("Pi extension binding is invalid")
        environment = dict(self.environment)
        environment_prefix = (
            "ASTERION_" + re.sub(r"[.-]", "_", self.extension_id).upper() + "_"
        )
        if any(
            type(name) is not str
            or not name.startswith(environment_prefix)
            or name.startswith(_RESERVED_ENVIRONMENT_PREFIX)
            or re.fullmatch(r"[A-Z][A-Z0-9_]*", name) is None
            or type(value) is not str
            or "\x00" in value
            for name, value in environment.items()
        ):
            raise ValueError("Pi extension binding is invalid")
        declared_fds: list[int] = []
        for name, value in environment.items():
            if not name.endswith("_FD"):
                continue
            if re.fullmatch(r"[1-9][0-9]*", value) is None:
                raise ValueError("Pi extension binding is invalid")
            declared_fds.append(int(value))
        if tuple(sorted(declared_fds)) != self.inherited_fds:
            raise ValueError("Pi extension binding is invalid")
        object.__setattr__(self, "environment", RedactedImmutableMapping(environment))

    def __repr__(self) -> str:
        return "<PiExtensionBinding redacted>"

    def preflight(self, loader_path: Path | None = None) -> PiExtensionLease:
        """Pin validated source bytes, loader identity, and declared resources."""

        return PiExtensionLease.open(
            self,
            pi_extension_loader_path() if loader_path is None else loader_path,
        )


class PiExtensionLease:
    """One single-run ownership lease for pinned extension resources."""

    __slots__ = (
        "environment",
        "inherited_fds",
        "loader_path",
        "sensitive_values",
        "_closed",
        "_fd_identities",
        "_loader_digest",
        "_loader_fd",
    )

    def __init__(
        self,
        *,
        environment: Mapping[str, str],
        inherited_fds: tuple[int, ...],
        loader_path: Path,
        sensitive_values: tuple[str | int, ...],
        fd_identities: Mapping[int, tuple[int, int, int, int]],
        loader_digest: str,
        loader_fd: int,
    ) -> None:
        self.environment = RedactedImmutableMapping(environment)
        self.inherited_fds = inherited_fds
        self.loader_path = loader_path
        self.sensitive_values = sensitive_values
        self._fd_identities = dict(fd_identities)
        self._loader_digest = loader_digest
        self._loader_fd = loader_fd
        self._closed = False

    @classmethod
    def open(
        cls, binding: PiExtensionBinding, loader_path: Path
    ) -> PiExtensionLease:
        owned: list[int] = []
        try:
            source = _read_exact_source(binding.path)
            _validate_source(binding.path.name, source)
            source_fd = _snapshot_source(source)
            owned.append(source_fd)
            replacements: dict[int, int] = {}
            for descriptor in binding.inherited_fds:
                before = _fd_identity(descriptor)
                duplicate = os.dup(descriptor)
                owned.append(duplicate)
                os.set_inheritable(duplicate, False)
                if (
                    _fd_identity(duplicate) != before
                    or _fd_identity(descriptor) != before
                ):
                    raise OSError
                replacements[descriptor] = duplicate

            exact_loader = loader_path.resolve(strict=True)
            if exact_loader != loader_path or loader_path.name != _LOADER_FILENAME:
                raise OSError
            loader_fd = _open_regular(loader_path)
            owned.append(loader_fd)
            loader = _read_fd(loader_fd, _MAX_SOURCE_BYTES)
            os.lseek(loader_fd, 0, os.SEEK_SET)
            loader_digest = hashlib.sha256(loader).hexdigest()

            environment = {
                name: str(replacements[int(value)]) if name.endswith("_FD") else value
                for name, value in binding.environment.items()
            }
            source_digest = hashlib.sha256(source).hexdigest()
            environment.update(
                {
                    _SOURCE_FD: str(source_fd),
                    _SOURCE_NAME_ENV: binding.path.name,
                    _SOURCE_SHA256: source_digest,
                }
            )
            process_fds = tuple(sorted((source_fd, *replacements.values())))
            identities = {fd: _fd_identity(fd) for fd in process_fds}
            sensitive = tuple(
                sorted(
                    {
                        str(binding.path),
                        str(loader_path),
                        *binding.environment.keys(),
                        *binding.environment.values(),
                        *environment.keys(),
                        *environment.values(),
                    },
                    key=len,
                    reverse=True,
                )
            )
            owned.remove(loader_fd)
            for descriptor in process_fds:
                owned.remove(descriptor)
            return cls(
                environment=environment,
                inherited_fds=process_fds,
                loader_path=loader_path,
                sensitive_values=(
                    *sensitive,
                    *binding.inherited_fds,
                    *process_fds,
                ),
                fd_identities=identities,
                loader_digest=loader_digest,
                loader_fd=loader_fd,
            )
        except (OSError, TypeError, ValueError, UnicodeError):
            for descriptor in reversed(owned):
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            raise ValueError("Pi extension binding is unavailable") from None

    def __repr__(self) -> str:
        return "<PiExtensionLease redacted>"

    @property
    def closed(self) -> bool:
        return self._closed

    def command_args(self) -> tuple[str, str]:
        return ("--extension", str(self.loader_path))

    def validate_launch(self) -> None:
        if self._closed:
            raise ValueError("Pi extension lease is closed")
        try:
            path_details = os.stat(self.loader_path, follow_symlinks=False)
            held_details = os.fstat(self._loader_fd)
            if _stat_identity(path_details) != _stat_identity(held_details):
                raise OSError
            loader = _read_fd(self._loader_fd, _MAX_SOURCE_BYTES)
            os.lseek(self._loader_fd, 0, os.SEEK_SET)
            if hashlib.sha256(loader).hexdigest() != self._loader_digest:
                raise OSError
            for descriptor, identity in self._fd_identities.items():
                if _fd_identity(descriptor) != identity:
                    raise OSError
        except OSError:
            raise ValueError("Pi extension lease is unavailable") from None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for descriptor in (*self.inherited_fds, self._loader_fd):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _open_regular(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        details = os.fstat(descriptor)
        path_details = os.stat(path, follow_symlinks=False)
        if (
            not stat.S_ISREG(details.st_mode)
            or _stat_identity(details) != _stat_identity(path_details)
        ):
            raise OSError
    except (OSError, TypeError, ValueError):
        os.close(descriptor)
        raise
    return descriptor


def _read_exact_source(path: Path) -> bytes:
    descriptor = _open_regular(path)
    try:
        if path.resolve(strict=True) != path:
            raise OSError
        return _read_fd(descriptor, _MAX_SOURCE_BYTES)
    finally:
        os.close(descriptor)


def _read_fd(descriptor: int, limit: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = os.read(descriptor, min(64 * 1024, limit + 1 - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
        if size > limit:
            raise OSError
    return b"".join(chunks)


def _snapshot_source(source: bytes) -> int:
    with tempfile.TemporaryFile() as snapshot:
        snapshot.write(source)
        snapshot.flush()
        snapshot.seek(0)
        descriptor = os.dup(snapshot.fileno())
    try:
        os.set_inheritable(descriptor, False)
    except OSError:
        os.close(descriptor)
        raise
    return descriptor


def _validate_source(name: str, source: bytes) -> None:
    if _SOURCE_NAME.fullmatch(name) is None or not source:
        raise ValueError
    text = source.decode("utf-8")
    if "\x00" in text or re.search(r"\bimport\s*\(", text):
        raise ValueError
    if _REEXPORT.search(text):
        raise ValueError
    imports = list(re.finditer(r"\bimport\b", text))
    matches = list(_STATIC_IMPORT.finditer(text))
    if len(imports) != len(matches) or any(
        not match.group(1).startswith("node:") for match in matches
    ):
        raise ValueError
    if re.search(r"\bexport\s+default\b", text) is None:
        raise ValueError


def _fd_identity(descriptor: int) -> tuple[int, int, int, int]:
    return _stat_identity(os.fstat(descriptor))


def _stat_identity(details: os.stat_result) -> tuple[int, int, int, int]:
    return (details.st_dev, details.st_ino, details.st_mode, details.st_rdev)
