"""Authority-only admission of a Prime P1 evidence-root descriptor."""

from __future__ import annotations

import os
import stat
import threading
from typing import SupportsIndex

from .authority_config import PrimeP1OperatorConfig


_EVIDENCE_TOKEN = object()
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class PrimeP1EvidenceResourceError(ValueError):
    """Single public-safe evidence-resource admission failure category."""

    def __init__(self, *_: object) -> None:
        super().__init__("prime P1 evidence resource is unavailable")


class AdmittedPrimeP1EvidenceRoot:
    """Opaque owner of one admitted evidence-root directory descriptor."""

    __slots__ = ("_fd", "_lock")

    def __init__(self, fd: int, *, _token: object | None = None) -> None:
        if _token is not _EVIDENCE_TOKEN:
            raise PrimeP1EvidenceResourceError() from None
        self._fd: int | None = fd
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return "AdmittedPrimeP1EvidenceRoot(redacted)"

    def __reduce__(self) -> object:
        raise TypeError("prime P1 evidence resource is unavailable")

    def __reduce_ex__(self, _: SupportsIndex) -> object:
        raise TypeError("prime P1 evidence resource is unavailable")

    def __copy__(self) -> object:
        raise TypeError("prime P1 evidence resource is unavailable")

    def __deepcopy__(self, _: object) -> object:
        raise TypeError("prime P1 evidence resource is unavailable")

    def close(self) -> None:
        """Release the retained directory descriptor exactly once."""
        with self._lock:
            fd = self._fd
            self._fd = None
        if fd is not None:
            try:
                os.close(fd)
            except (OSError, OverflowError):
                pass


def admit_evidence_root(config: object) -> AdmittedPrimeP1EvidenceRoot:
    """Open the exact authority-owned evidence directory without retaining its path."""
    fd: int | None = None
    result: AdmittedPrimeP1EvidenceRoot | None = None
    try:
        if type(config) is not PrimeP1OperatorConfig:
            raise ValueError
        path = config._values["ASTERION_PRIME_P1_EVIDENCE_ROOT"]
        fd = _open_absolute_directory_without_symlinks(path)
        info = os.fstat(fd)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise ValueError
        result = AdmittedPrimeP1EvidenceRoot(fd, _token=_EVIDENCE_TOKEN)
        fd = None
    except BaseException:
        pass
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except (OSError, OverflowError):
                pass
    if result is None:
        raise PrimeP1EvidenceResourceError() from None
    return result


def _open_absolute_directory_without_symlinks(path: object) -> int:
    """Open each canonical absolute-path component beneath a descriptor anchor."""
    if type(path) is not str or not os.path.isabs(path):
        raise ValueError
    components = path.split("/")[1:]
    if not components or any(part in {"", ".", ".."} for part in components):
        raise ValueError
    fd: int | None = os.open("/", _DIRECTORY_FLAGS)
    try:
        for component in components:
            child = os.open(component, _DIRECTORY_FLAGS, dir_fd=fd)
            previous = fd
            fd = child
            _close_quietly(previous)
        result = fd
        fd = None
        return result
    finally:
        _close_quietly(fd)


def _close_quietly(fd: int | None) -> None:
    if fd is not None:
        try:
            os.close(fd)
        except (OSError, OverflowError):
            pass
