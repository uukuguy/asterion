"""Authority-only loader for a service-manager supplied Prime P1 config FD."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import fcntl
import os
import re
import stat
from types import MappingProxyType
from typing import Any, SupportsIndex
import unicodedata

from .authority_receipt import _AuthorityReceiptIssuer, _new_authority_receipt_issuer


_KEYS = frozenset(
    {
        "ASTERION_PRIME_P1_DOCKER_EXECUTABLE",
        "ASTERION_PRIME_P1_DOCKER_SOCKET",
        "ASTERION_PRIME_P1_SECCOMP_PROFILE",
        "ASTERION_PRIME_P1_SECCOMP_PROFILE_SHA256",
        "ASTERION_PRIME_P1_IMAGE_CONFIG_DIGEST",
        "ASTERION_PRIME_P1_MODEL_ID",
        "ASTERION_PRIME_P1_EVIDENCE_ROOT",
        "ASTERION_PRIME_P1_RECEIPT_KEY_ID",
        "ASTERION_PRIME_P1_RECEIPT_HMAC_KEY",
        "DEEPSEEK_API_KEY",
        "ASTERION_PRIME_P1_IMAGE_PLATFORM_OS",
        "ASTERION_PRIME_P1_IMAGE_PLATFORM_ARCHITECTURE",
        "ASTERION_PRIME_P1_IMAGE_PLATFORM_VARIANT",
    }
)
_RECEIPT_KEY = re.compile(r"[0-9a-f]{64}\Z")
_OCI_COMPONENT = re.compile(r"[a-z0-9]+\Z")
_OCI_VARIANT = re.compile(r"v[0-9]+\Z")
_MAX_BYTES = 65536


class PrimeP1OperatorConfigError(ValueError):
    """Single public-safe configuration failure category."""

    def __init__(self, *_: object) -> None:
        super().__init__("prime P1 operator configuration is unavailable")


@dataclass(frozen=True, repr=False, slots=True)
class PrimeP1OperatorConfig:
    _values: Mapping[str, str]
    _receipt_issuer: _AuthorityReceiptIssuer

    @property
    def model_id(self) -> str:
        return self._values["ASTERION_PRIME_P1_MODEL_ID"]

    def __repr__(self) -> str:
        return "PrimeP1OperatorConfig(redacted)"

    def __reduce__(self) -> str | tuple[Any, ...]:
        raise TypeError("prime P1 operator configuration is unavailable")

    def __reduce_ex__(self, _: SupportsIndex) -> str | tuple[Any, ...]:
        raise TypeError("prime P1 operator configuration is unavailable")

    def __copy__(self) -> object:
        raise TypeError("prime P1 operator configuration is unavailable")

    def __deepcopy__(self, _: object) -> object:
        raise TypeError("prime P1 operator configuration is unavailable")


def load_operator_config(config_fd: int) -> PrimeP1OperatorConfig:
    """Consume an already-open, close-on-exec authority configuration FD.

    This is the production admission boundary.  It intentionally accepts no
    path, identity, command-line, environment, or parser configuration input.
    """
    fd: int | None = config_fd if type(config_fd) is int else None
    result: PrimeP1OperatorConfig | None = None
    failed = False
    try:
        if fd is None:
            raise ValueError
        _validate_close_on_exec(fd)
        before = os.fstat(fd)
        _validate_file(before, os.geteuid())
        os.lseek(fd, 0, os.SEEK_SET)
        data = _read_bounded(fd)
        after = os.fstat(fd)
        if _stable_identity(before) != _stable_identity(after):
            raise ValueError
        values = _parse_verified_bytes(data)
        issuer = _new_authority_receipt_issuer(
            values.pop("ASTERION_PRIME_P1_RECEIPT_HMAC_KEY")
        )
        result = PrimeP1OperatorConfig(MappingProxyType(values), issuer)
    except (OSError, OverflowError, TypeError, UnicodeError, ValueError):
        failed = True
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except (OSError, OverflowError):
                pass
    if failed or result is None:
        raise PrimeP1OperatorConfigError() from None
    return result


def _validate_close_on_exec(fd: int) -> None:
    if not fcntl.fcntl(fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC:
        raise ValueError


def _validate_file(info: os.stat_result, authority_uid: int) -> None:
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != authority_uid
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise ValueError


def _stable_identity(info: os.stat_result) -> tuple[int, ...]:
    """Fields that must not change while the authority reads this FD.

    Access time is excluded because a successful read may legitimately update
    it.  All ownership, link, object, size, and mutation/change timestamps are
    retained.
    """
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_uid,
        info.st_gid,
        info.st_rdev,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _read_bounded(fd: int) -> bytes:
    data = os.read(fd, _MAX_BYTES + 1)
    if not 1 <= len(data) <= _MAX_BYTES or os.read(fd, 1):
        raise ValueError
    return data


def _parse_verified_bytes(data: bytes) -> dict[str, str]:
    """Parse verified bytes only; this helper is not a resource admission API."""
    text = data.decode("utf-8")
    values: dict[str, str] = {}
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    for line in lines:
        if not line:
            raise ValueError
        if line.count("=") < 1:
            raise ValueError
        key, value = line.split("=", 1)
        if (
            key not in _KEYS
            or key in values
            or not value
            or _unsafe_text(key)
            or _unsafe_text(value)
        ):
            raise ValueError
        values[key] = value
    if (
        set(values) != _KEYS
        or _RECEIPT_KEY.fullmatch(values["ASTERION_PRIME_P1_RECEIPT_HMAC_KEY"]) is None
        or _RECEIPT_KEY.fullmatch(
            values["ASTERION_PRIME_P1_SECCOMP_PROFILE_SHA256"]
        )
        is None
        or values["ASTERION_PRIME_P1_IMAGE_PLATFORM_OS"] != "linux"
        or _OCI_COMPONENT.fullmatch(values["ASTERION_PRIME_P1_IMAGE_PLATFORM_OS"])
        is None
        or _OCI_COMPONENT.fullmatch(
            values["ASTERION_PRIME_P1_IMAGE_PLATFORM_ARCHITECTURE"]
        )
        is None
        or (
            values["ASTERION_PRIME_P1_IMAGE_PLATFORM_VARIANT"] != "none"
            and _OCI_VARIANT.fullmatch(
                values["ASTERION_PRIME_P1_IMAGE_PLATFORM_VARIANT"]
            )
            is None
        )
    ):
        raise ValueError
    return values


def _unsafe_text(value: str) -> bool:
    return any(unicodedata.category(char) in {"Cc", "Cf", "Zl", "Zp"} for char in value)
