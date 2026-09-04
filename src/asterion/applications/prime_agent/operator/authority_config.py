"""Authority-only loader for the fixed external Prime P1 configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
import stat
from types import MappingProxyType
from collections.abc import Mapping


_KEYS = frozenset(
    {
        "ASTERION_PRIME_P1_DOCKER_EXECUTABLE",
        "ASTERION_PRIME_P1_DOCKER_SOCKET",
        "ASTERION_PRIME_P1_SECCOMP_PROFILE",
        "ASTERION_PRIME_P1_IMAGE_CONFIG_DIGEST",
        "ASTERION_PRIME_P1_MODEL_ID",
        "ASTERION_PRIME_P1_EVIDENCE_ROOT",
        "ASTERION_PRIME_P1_RECEIPT_KEY_ID",
        "ASTERION_PRIME_P1_RECEIPT_HMAC_KEY",
        "DEEPSEEK_API_KEY",
    }
)
_RECEIPT_KEY = re.compile(r"[0-9a-f]{64}\Z")
_MAX_BYTES = 65536


class PrimeP1OperatorConfigError(ValueError):
    """Single public-safe configuration failure category."""

    def __init__(self, *_: object) -> None:
        super().__init__("prime P1 operator configuration is unavailable")


@dataclass(frozen=True, repr=False)
class PrimeP1OperatorConfig:
    _values: Mapping[str, str]

    @property
    def model_id(self) -> str:
        return self._values["ASTERION_PRIME_P1_MODEL_ID"]

    def __repr__(self) -> str:
        return "PrimeP1OperatorConfig(redacted)"


def load_operator_config(path: Path, *, authority_uid: int, application_uid: int) -> PrimeP1OperatorConfig:
    """Load one explicit, no-follow external file; never consult ambient state."""
    try:
        target = Path(path)
        if not target.is_absolute() or target.name == ".env" or authority_uid < 0 or application_uid < 0:
            raise ValueError
        fd = _open_secure_file(target, application_uid)
        try:
            before = os.fstat(fd)
            _validate_file(before, authority_uid)
            data = _read_bounded(fd)
            after = os.fstat(fd)
            if (before.st_dev, before.st_ino, before.st_mode, before.st_size) != (after.st_dev, after.st_ino, after.st_mode, after.st_size):
                raise ValueError
        finally:
            os.close(fd)
        return PrimeP1OperatorConfig(MappingProxyType(_parse(data)))
    except (OSError, TypeError, UnicodeError, ValueError):
        raise PrimeP1OperatorConfigError() from None


def _open_secure_file(path: Path, application_uid: int) -> int:
    """Walk absolute components through descriptors, never following a link."""
    directory_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        _validate_directory_stat(os.fstat(directory_fd), application_uid)
        parts = path.parts[1:]
        if not parts:
            raise ValueError
        for component in parts[:-1]:
            next_fd = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = next_fd
            _validate_directory_stat(os.fstat(directory_fd), application_uid)
        return os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd
        )
    finally:
        os.close(directory_fd)


def _validate_directory_stat(info: os.stat_result, application_uid: int) -> None:
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError
    # Group/world writable ancestors could be writable by the application.
    if info.st_mode & 0o022 or (info.st_uid == application_uid and info.st_mode & 0o200):
        raise ValueError


def _validate_file(info: os.stat_result, authority_uid: int) -> None:
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != authority_uid or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError


def _read_bounded(fd: int) -> bytes:
    data = os.read(fd, _MAX_BYTES + 1)
    if not 1 <= len(data) <= _MAX_BYTES or os.read(fd, 1):
        raise ValueError
    return data


def _parse(data: bytes) -> dict[str, str]:
    text = data.decode("utf-8")
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line or "=" not in line or line.startswith(("#", "export ")):
            raise ValueError
        key, value = line.split("=", 1)
        if key not in _KEYS or key in values or not value or "${" in value or "$" in value:
            raise ValueError
        if "\x00" in value or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError
        values[key] = value
    if set(values) != _KEYS or _RECEIPT_KEY.fullmatch(values["ASTERION_PRIME_P1_RECEIPT_HMAC_KEY"]) is None:
        raise ValueError
    return values
