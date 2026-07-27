"""Explicit canonical-root adapter for local capability packages."""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import importlib.util
import os
import secrets
import stat
import sys
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import ModuleType
from typing import Iterator

from asterion.capability_packages.model import (
    CapabilityPackageCandidate,
    InstalledCapabilityPackage,
    PortableCapabilityPayload,
)
from asterion.capability_packages.payload import open_portable_payload
from asterion.capability_packages.protocol import (
    IDENTIFIER,
    SHA256,
    CapabilityPackageRef,
    CapabilitySourceDeclaration,
)


_PAYLOAD_DIRECTORY = "payload"
_TEMPORARY_MODULE_PREFIX = "_asterion_local_"
_MAXIMUM_FACTORY_BYTES = 16 * 1024 * 1024


class LocalDirectoryCapabilitySourceError(ValueError):
    """Raised when an explicit local package source is unsafe or invalid."""


class LocalDirectoryCapabilityPackageSource:
    """Load one exact operator-declared local source without directory scans."""

    __slots__ = (
        "_declaration",
        "_factory_module",
        "_factory_name",
        "_root",
        "_root_identity",
    )

    def __init__(self, declaration: CapabilitySourceDeclaration) -> None:
        try:
            if (
                not isinstance(declaration, CapabilitySourceDeclaration)
                or declaration.kind != "local-directory"
                or not isinstance(declaration.source_id, str)
                or IDENTIFIER.fullmatch(declaration.source_id) is None
                or not isinstance(
                    declaration.package_ref,
                    CapabilityPackageRef,
                )
                or (
                    declaration.payload_sha256 is not None
                    and (
                        not isinstance(declaration.payload_sha256, str)
                        or SHA256.fullmatch(declaration.payload_sha256) is None
                    )
                )
                or set(declaration.locator) != {"root"}
                or set(declaration.provider_factory) != {"module", "name"}
            ):
                _invalid()
            root = _canonical_root(declaration.locator["root"])
            factory_module = declaration.provider_factory["module"]
            factory_name = declaration.provider_factory["name"]
            if not _module_name(factory_module) or not factory_name.isidentifier():
                _invalid()
            root_identity = _opened_root_identity(root)
        except LocalDirectoryCapabilitySourceError:
            raise
        except Exception:
            _invalid()
        self._declaration = declaration
        self._factory_module = factory_module
        self._factory_name = factory_name
        self._root = root
        self._root_identity = root_identity

    def discover_metadata(self) -> tuple[CapabilityPackageCandidate, ...]:
        """Return the declared identity without opening payload or provider."""

        self._validate_root_identity()
        return (self._candidate(),)

    def open_payload(
        self,
        candidate: CapabilityPackageCandidate,
    ) -> PortableCapabilityPayload:
        """Validate and snapshot the exact fixed payload child."""

        self._require_candidate(candidate)
        try:
            self._validate_payload_directory()
            payload = open_portable_payload(self._root / _PAYLOAD_DIRECTORY)
            self._validate_payload_directory()
            self.validate_source_identity(candidate, payload)
            return payload
        except LocalDirectoryCapabilitySourceError:
            raise
        except Exception:
            _invalid()

    def validate_source_identity(
        self,
        candidate: CapabilityPackageCandidate,
        payload: PortableCapabilityPayload,
    ) -> None:
        """Bind the explicit declaration to the opened portable content."""

        self._require_candidate(candidate)
        if (
            not isinstance(payload, PortableCapabilityPayload)
            or payload.manifest.package_ref != candidate.package_ref
            or (
                candidate.payload_sha256 is not None
                and candidate.payload_sha256 != payload.payload_sha256
            )
        ):
            _invalid()

    def load_provider(
        self,
        candidate: CapabilityPackageCandidate,
    ) -> InstalledCapabilityPackage:
        """Import and call only the exact selected local provider factory."""

        self._require_candidate(candidate)
        payload = self.open_payload(candidate)
        try:
            installed = self._invoke_factory()
        except LocalDirectoryCapabilitySourceError:
            raise
        except BaseException:
            _invalid()
        if (
            not isinstance(installed, InstalledCapabilityPackage)
            or installed.package_ref != candidate.package_ref
            or installed.payload_sha256 != payload.payload_sha256
            or installed.source_id != candidate.source_id
            or installed.source_kind != "local-directory"
            or not _provider_resources_match(
                installed,
                payload_root=self._root / _PAYLOAD_DIRECTORY,
                payload=payload,
            )
        ):
            _invalid()
        return installed

    def _candidate(self) -> CapabilityPackageCandidate:
        return CapabilityPackageCandidate(
            package_ref=self._declaration.package_ref,
            source_id=self._declaration.source_id,
            source_kind="local-directory",
            payload_sha256=self._declaration.payload_sha256,
            metadata={},
        )

    def _require_candidate(
        self,
        candidate: CapabilityPackageCandidate,
    ) -> None:
        if (
            not isinstance(candidate, CapabilityPackageCandidate)
            or candidate != self._candidate()
        ):
            _invalid()

    def _validate_root_identity(self) -> None:
        try:
            if _opened_root_identity(self._root) != self._root_identity:
                _invalid()
        except LocalDirectoryCapabilitySourceError:
            raise
        except Exception:
            _invalid()

    def _validate_payload_directory(self) -> None:
        try:
            with _open_root(
                self._root,
                expected_identity=self._root_identity,
            ) as root_fd:
                with ExitStack() as descriptors:
                    payload_fd = _open_directory_at(
                        root_fd,
                        _PAYLOAD_DIRECTORY,
                        descriptors,
                    )
                    expected = os.stat(
                        _PAYLOAD_DIRECTORY,
                        dir_fd=root_fd,
                        follow_symlinks=False,
                    )
                    opened = os.fstat(payload_fd)
                    if not stat.S_ISDIR(expected.st_mode) or _file_identity(
                        expected
                    ) != _file_identity(opened):
                        _invalid()
        except LocalDirectoryCapabilitySourceError:
            raise
        except Exception:
            _invalid()

    def _invoke_factory(self) -> object:
        with _open_root(
            self._root,
            expected_identity=self._root_identity,
        ) as root_fd:
            with ExitStack() as descriptors:
                module_parts = self._factory_module.split(".")
                parent_fd = root_fd
                for part in module_parts[:-1]:
                    parent_fd = _open_directory_at(
                        parent_fd,
                        part,
                        descriptors,
                    )
                file_name = f"{module_parts[-1]}.py"
                source, fingerprint = _read_regular_at(
                    parent_fd,
                    file_name,
                    descriptors,
                )
                factory_path = self._root.joinpath(
                    *module_parts[:-1],
                    file_name,
                )
                prefix = _TEMPORARY_MODULE_PREFIX + secrets.token_hex(16)
                scoped_name = f"{prefix}.{self._factory_module}"
                try:
                    _install_scoped_packages(
                        prefix,
                        module_parts[:-1],
                    )
                    loader = _PinnedSourceLoader(
                        source=source,
                        source_path=factory_path,
                    )
                    spec = importlib.util.spec_from_loader(
                        scoped_name,
                        loader,
                        origin=str(factory_path),
                    )
                    if spec is None:
                        _invalid()
                    module = importlib.util.module_from_spec(spec)
                    module.__file__ = str(factory_path)
                    sys.modules[scoped_name] = module
                    loader.exec_module(module)
                    factory = getattr(module, self._factory_name, None)
                    if not callable(factory):
                        _invalid()
                    installed = factory()
                    _verify_regular_at(
                        parent_fd,
                        file_name,
                        fingerprint,
                    )
                    return installed
                finally:
                    _purge_scoped_modules(prefix)


class _PinnedSourceLoader(importlib.abc.Loader):
    """Execute already pinned source bytes through an isolated import spec."""

    def __init__(self, *, source: bytes, source_path: Path) -> None:
        self._source = source
        self._source_path = source_path

    def create_module(self, spec: object) -> None:
        del spec
        return None

    def exec_module(self, module: ModuleType) -> None:
        try:
            code = compile(
                self._source,
                str(self._source_path),
                "exec",
                dont_inherit=True,
            )
            exec(code, module.__dict__)
        except LocalDirectoryCapabilitySourceError:
            raise
        except BaseException:
            _invalid()


def _canonical_root(value: object) -> Path:
    if not isinstance(value, str) or not value:
        _invalid()
    root = Path(value)
    if not root.is_absolute():
        _invalid()
    try:
        resolved = root.resolve(strict=True)
        details = root.lstat()
    except (OSError, RuntimeError, ValueError):
        _invalid()
    if root != resolved or root.is_symlink() or not stat.S_ISDIR(details.st_mode):
        _invalid()
    return resolved


def _module_name(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and all(part.isidentifier() for part in value.split("."))
    )


def _opened_root_identity(root: Path) -> tuple[int, int]:
    with _open_root(root, expected_identity=None) as root_fd:
        return _file_identity(os.fstat(root_fd))


@contextmanager
def _open_root(
    root: Path,
    *,
    expected_identity: tuple[int, int] | None,
) -> Iterator[int]:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    descriptor = -1
    try:
        before = root.lstat()
        descriptor = os.open(root, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(before.st_mode)
            or _file_identity(before) != _file_identity(opened)
            or (
                expected_identity is not None
                and _file_identity(opened) != expected_identity
            )
        ):
            _invalid()
        yield descriptor
        after = root.lstat()
        if _file_identity(after) != _file_identity(opened) or _file_identity(
            os.fstat(descriptor)
        ) != _file_identity(opened):
            _invalid()
    except LocalDirectoryCapabilitySourceError:
        raise
    except Exception:
        _invalid()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _open_directory_at(
    parent_fd: int,
    name: str,
    descriptors: ExitStack,
) -> int:
    if not name.isidentifier():
        _invalid()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        descriptor = os.open(name, flags, dir_fd=parent_fd)
        descriptors.callback(os.close, descriptor)
        opened = os.fstat(descriptor)
    except OSError:
        _invalid()
    if not stat.S_ISDIR(before.st_mode) or _file_identity(before) != _file_identity(
        opened
    ):
        _invalid()
    return descriptor


def _read_regular_at(
    parent_fd: int,
    name: str,
    descriptors: ExitStack,
) -> tuple[bytes, tuple[int, int, int, int, int]]:
    flags = (
        os.O_RDONLY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        descriptor = os.open(name, flags, dir_fd=parent_fd)
        descriptors.callback(os.close, descriptor)
        opened = os.fstat(descriptor)
    except OSError:
        _invalid()
    if not stat.S_ISREG(before.st_mode) or _file_identity(before) != _file_identity(
        opened
    ):
        _invalid()
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAXIMUM_FACTORY_BYTES:
                _invalid()
            chunks.append(chunk)
        after = os.fstat(descriptor)
    except OSError:
        _invalid()
    fingerprint = _regular_fingerprint(opened)
    if _regular_fingerprint(after) != fingerprint:
        _invalid()
    return b"".join(chunks), fingerprint


def _verify_regular_at(
    parent_fd: int,
    name: str,
    expected: tuple[int, int, int, int, int],
) -> None:
    try:
        current = os.stat(
            name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
    except OSError:
        _invalid()
    if _regular_fingerprint(current) != expected:
        _invalid()


def _file_identity(details: os.stat_result) -> tuple[int, int]:
    return details.st_dev, details.st_ino


def _regular_fingerprint(
    details: os.stat_result,
) -> tuple[int, int, int, int, int]:
    if not stat.S_ISREG(details.st_mode):
        _invalid()
    return (
        details.st_dev,
        details.st_ino,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
    )


def _install_scoped_packages(
    prefix: str,
    package_parts: list[str],
) -> None:
    parts = [prefix, *package_parts]
    for index in range(1, len(parts) + 1):
        name = ".".join(parts[:index])
        package = ModuleType(name)
        package.__package__ = name
        package.__path__ = []  # type: ignore[attr-defined]
        package.__spec__ = importlib.machinery.ModuleSpec(
            name,
            loader=None,
            is_package=True,
        )
        sys.modules[name] = package


def _purge_scoped_modules(prefix: str) -> None:
    for name in tuple(sys.modules):
        if name == prefix or name.startswith(prefix + "."):
            sys.modules.pop(name, None)


def _provider_resources_match(
    installed: InstalledCapabilityPackage,
    *,
    payload_root: Path,
    payload: PortableCapabilityPayload,
) -> bool:
    try:
        root = payload_root.resolve(strict=True)
        expected_catalog = (root / "capabilities").resolve(strict=True)
        if expected_catalog.is_symlink() or installed.catalog_roots != (
            expected_catalog,
        ):
            return False
        suite_paths = installed.benchmark_suite_paths
        if len(suite_paths) != len(payload.manifest.benchmark_suites):
            return False
        if not suite_paths:
            return True
        suite_root = (root / "benchmark-suites").resolve(strict=True)
        return all(
            path == path.resolve(strict=True)
            and path.parent == suite_root
            and path.suffix == ".json"
            and path.is_file()
            and not path.is_symlink()
            for path in suite_paths
        )
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return False


def _invalid() -> None:
    raise LocalDirectoryCapabilitySourceError(
        "local capability source is invalid"
    ) from None
