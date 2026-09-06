"""Metadata-only exact source-lock creation for DCI benchmark instances."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path

from asterion.applications.dci_agent_lite.benchmark_instances import (
    DciBenchmarkInstance,
)
from asterion.capability_packages import (
    CAPABILITY_LOCK_PROTOCOL_VERSION,
    CapabilityPackageRef,
    CapabilitySourceLock,
    CapabilitySourceLockEntry,
    prepare_capability_source,
)
from asterion.capability_packages.sources.base import CapabilityPackageSource
from asterion.capability_packages.sources.builtin import BuiltinCapabilitySource
from asterion.applications.first_party_packages import builtin_capability_registrations
from asterion.capability_packages.sources.distribution import (
    DistributionCapabilityPackageSource,
)


_DCI_PACKAGE = CapabilityPackageRef("dci", "1.0.0")
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


class DciBenchmarkSourceLockError(ValueError):
    """Raised when a DCI source lock cannot be resolved or persisted safely."""


def resolve_benchmark_source_lock(
    instance: DciBenchmarkInstance,
    *,
    package_sources: Sequence[CapabilityPackageSource] | None = None,
) -> CapabilitySourceLock:
    """Resolve one verified exact DCI payload without loading its provider."""

    try:
        if not isinstance(instance, DciBenchmarkInstance):
            _fail()
        sources = (
            (
                BuiltinCapabilitySource(builtin_capability_registrations()),
                DistributionCapabilityPackageSource(),
            )
            if package_sources is None
            else tuple(package_sources)
        )
        if not sources:
            _fail()
        prepared = prepare_capability_source(_DCI_PACKAGE, sources, None)
        selected = prepared.candidate
        if selected.payload_sha256 is None:
            _fail()
        return CapabilitySourceLock(
            entries=(
                CapabilitySourceLockEntry(
                    package_ref=_DCI_PACKAGE,
                    payload_sha256=selected.payload_sha256,
                    source_id=selected.source_id,
                ),
            )
        )
    except DciBenchmarkSourceLockError:
        raise
    except Exception:
        _fail()


def write_benchmark_source_lock(
    lock: CapabilitySourceLock,
    output: Path,
) -> None:
    """Create one canonical private lock file without overwrite or symlinks."""

    fd: int | None = None
    parent_fd: int | None = None
    created = False
    completed = False
    path: Path | None = None
    try:
        if not isinstance(lock, CapabilitySourceLock) or not isinstance(output, Path):
            _fail()
        if output.is_symlink() or output.parent.is_symlink():
            _fail()
        parent = output.parent.resolve(strict=True)
        if not parent.is_dir():
            _fail()
        path = parent / output.name
        if not output.name or output.name in {".", ".."}:
            _fail()
        content = (
            json.dumps(
                {
                    "entries": [
                        {
                            "package_ref": {
                                "package_id": entry.package_ref.package_id,
                                "version": entry.package_ref.version,
                            },
                            "payload_sha256": entry.payload_sha256,
                            "source_id": entry.source_id,
                        }
                        for entry in lock.entries
                    ],
                    "protocol": CAPABILITY_LOCK_PROTOCOL_VERSION,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        fd = os.open(
            path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | int(_O_NOFOLLOW)
            | int(_O_CLOEXEC),
            0o600,
        )
        created = True
        offset = 0
        while offset < len(content):
            written = os.write(fd, content[offset:])
            if written < 1:
                _fail()
            offset += written
        os.fsync(fd)
        os.close(fd)
        fd = None
        parent_fd = os.open(
            parent,
            os.O_RDONLY | int(_O_DIRECTORY) | int(_O_CLOEXEC),
        )
        os.fsync(parent_fd)
        completed = True
    except DciBenchmarkSourceLockError:
        raise
    except Exception:
        _fail()
    finally:
        if fd is not None:
            os.close(fd)
        if parent_fd is not None:
            os.close(parent_fd)
        if created and not completed and path is not None:
            try:
                path.unlink()
            except OSError:
                pass


def _fail() -> None:
    raise DciBenchmarkSourceLockError("DCI benchmark source lock is invalid")


__all__ = (
    "DciBenchmarkSourceLockError",
    "resolve_benchmark_source_lock",
    "write_benchmark_source_lock",
)
