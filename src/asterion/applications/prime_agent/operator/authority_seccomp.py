"""Static, authority-only admission of one locked Prime P1 seccomp profile."""

from __future__ import annotations

from dataclasses import dataclass
import fcntl
import hashlib
import hmac
import json
import os
import stat
import sys
import threading
from typing import Final, SupportsIndex

from .authority_config import PrimeP1OperatorConfig
from .image_input_lock import ImagePlatformDescriptor
from .seccomp_policy_lock import (
    SeccompArgumentConstraint,
    SeccompPolicyLock,
    SeccompRuleAtom,
    resolve_promoted_seccomp_policy,
)


_MAX_BYTES: Final = 65_536
_MAX_DEPTH: Final = 32
_MAX_EINTR: Final = 8
_MAX_PATH_BYTES: Final = 4096
_MAX_PATH_COMPONENTS: Final = 64
_U64_MAX: Final = 2**64 - 1
_OPS: Final = frozenset(
    {
        "SCMP_CMP_EQ",
        "SCMP_CMP_NE",
        "SCMP_CMP_LT",
        "SCMP_CMP_LE",
        "SCMP_CMP_GT",
        "SCMP_CMP_GE",
        "SCMP_CMP_MASKED_EQ",
    }
)


class PrimeP1AuthorityResourceError(ValueError):
    """Single public-safe seccomp-resource failure category."""

    def __init__(self, *_: object) -> None:
        super().__init__("prime P1 authority resource is unavailable")


@dataclass(frozen=True, repr=False, slots=True)
class _Identity:
    device: int
    inode: int
    mode: int
    links: int
    owner: int
    group: int
    size: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True, repr=False, slots=True)
class AdmittedPrimeP1SeccompResource:
    """Opaque retained profile descriptor, never execution authority."""

    _fds: tuple[int, ...]
    _path: str
    _identities: tuple[_Identity, ...]
    _policy: SeccompPolicyLock
    _sha256: str
    _lock: threading.Lock
    _closed: list[bool]

    @property
    def sha256(self) -> str:
        return self._sha256

    def close(self) -> None:
        fds: tuple[int, ...] = ()
        with self._lock:
            if not self._closed[0]:
                self._closed[0] = True
                fds = self._fds
        _close_all(fds)

    def __repr__(self) -> str:
        return "AdmittedPrimeP1SeccompResource(redacted)"

    def __reduce__(self) -> object:
        raise TypeError("prime P1 authority resource is unavailable")

    def __reduce_ex__(self, _: SupportsIndex) -> object:
        raise TypeError("prime P1 authority resource is unavailable")

    def __copy__(self) -> object:
        raise TypeError("prime P1 authority resource is unavailable")

    def __deepcopy__(self, _: object) -> object:
        raise TypeError("prime P1 authority resource is unavailable")


def admit_static_seccomp_resource(config: object) -> AdmittedPrimeP1SeccompResource:
    """Open and validate only the configured profile against a promoted lock."""
    fds: tuple[int, ...] = ()
    result: AdmittedPrimeP1SeccompResource | None = None
    try:
        _require_linux_posix()
        if type(config) is not PrimeP1OperatorConfig:
            raise ValueError
        values = config._values
        variant = values["ASTERION_PRIME_P1_IMAGE_PLATFORM_VARIANT"]
        platform = ImagePlatformDescriptor(
            values["ASTERION_PRIME_P1_IMAGE_PLATFORM_OS"],
            values["ASTERION_PRIME_P1_IMAGE_PLATFORM_ARCHITECTURE"],
            None if variant == "none" else variant,
        )
        # This resolution intentionally happens before any profile filesystem I/O.
        policy = resolve_promoted_seccomp_policy(platform)
        if values["ASTERION_PRIME_P1_IMAGE_CONFIG_DIGEST"] != policy.image_config_digest:
            raise ValueError
        path = values["ASTERION_PRIME_P1_SECCOMP_PROFILE"]
        expected = values["ASTERION_PRIME_P1_SECCOMP_PROFILE_SHA256"]
        fds = _open_profile(path)
        identities = _chain_identities(fds)
        data, actual = _read_profile(fds[-1], identities[-1])
        if not hmac.compare_digest(actual, expected):
            raise ValueError
        _validate_profile(data, policy)
        if _chain_identities(fds) != identities:
            raise ValueError
        result = AdmittedPrimeP1SeccompResource(
            fds, path, identities, policy, actual, threading.Lock(), [False]
        )
        fds = ()
    except BaseException:
        pass
    finally:
        _close_all(fds)
    if result is None:
        raise PrimeP1AuthorityResourceError() from None
    return result


def revalidate_static_seccomp_resource(resource: object) -> None:
    """Rewalk and recheck a retained static profile at its next safe use."""
    fds: tuple[int, ...] = ()
    failed = False
    try:
        if type(resource) is not AdmittedPrimeP1SeccompResource:
            raise ValueError
        _require_linux_posix()
        with resource._lock:
            if resource._closed[0] or _chain_identities(resource._fds) != resource._identities:
                raise ValueError
            fds = _open_profile(resource._path)
            identities = _chain_identities(fds)
            if identities != resource._identities:
                raise ValueError
            data, digest = _read_profile(fds[-1], identities[-1])
            if not hmac.compare_digest(digest, resource._sha256):
                raise ValueError
            _validate_profile(data, resource._policy)
            if (
                _chain_identities(resource._fds) != resource._identities
                or _chain_identities(fds) != resource._identities
            ):
                raise ValueError
    except BaseException:
        failed = True
    finally:
        _close_all(fds)
    if failed:
        raise PrimeP1AuthorityResourceError() from None


def _require_linux_posix() -> None:
    if sys.platform != "linux" or os.name != "posix":
        raise ValueError


def _open_profile(path: object) -> tuple[int, ...]:
    if type(path) is not str or not path.startswith("/") or "\x00" in path:
        raise ValueError
    components = path.split("/")[1:]
    if (
        not components
        or len(path.encode("utf-8")) > _MAX_PATH_BYTES
        or len(components) > _MAX_PATH_COMPONENTS
        or any(not part or part in {".", ".."} for part in components)
    ):
        raise ValueError
    root = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        fds = [root]
    except MemoryError:
        _close_quietly(root)
        raise
    try:
        _validate_directory(fds[-1])
        for part in components[:-1]:
            child = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=fds[-1],
            )
            try:
                fds.append(child)
            except MemoryError:
                _close_quietly(child)
                raise
            _validate_directory(child)
        leaf = os.open(
            components[-1], os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=fds[-1],
        )
        try:
            fds.append(leaf)
        except MemoryError:
            _close_quietly(leaf)
            raise
        try:
            result = tuple(fds)
        except MemoryError:
            _close_all(fds)
            raise
        fds = []
        return result
    except BaseException:
        _close_all(fds)
        raise


def _validate_directory(fd: int) -> None:
    info = os.fstat(fd)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid not in {0, os.geteuid()}
        or info.st_mode & 0o022
    ):
        raise ValueError


def _chain_identities(fds: tuple[int, ...]) -> tuple[_Identity, ...]:
    if not fds:
        raise ValueError
    return tuple(
        _directory_identity(fd) if index + 1 < len(fds) else _identity(fd)
        for index, fd in enumerate(fds)
    )


def _directory_identity(fd: int) -> _Identity:
    _require_cloexec(fd)
    _validate_directory(fd)
    info = os.fstat(fd)
    return _Identity(
        info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_uid,
        info.st_gid, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
    )


def _identity(fd: int) -> _Identity:
    _require_cloexec(fd)
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or not 1 <= info.st_size <= _MAX_BYTES
    ):
        raise ValueError
    return _Identity(
        info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_uid,
        info.st_gid, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
    )


def _require_cloexec(fd: int) -> None:
    if not fcntl.fcntl(fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC:
        raise ValueError


def _read_profile(fd: int, identity: _Identity) -> tuple[bytes, str]:
    chunks: list[bytes] = []
    digest = hashlib.sha256()
    total = 0
    retries = 0
    while True:
        try:
            chunk = os.read(fd, min(8192, _MAX_BYTES + 1 - total))
        except InterruptedError:
            retries += 1
            if retries > _MAX_EINTR:
                raise ValueError from None
            continue
        if type(chunk) is not bytes:
            raise ValueError
        if not chunk:
            break
        retries = 0
        total += len(chunk)
        if total > _MAX_BYTES:
            raise ValueError
        chunks.append(chunk)
        digest.update(chunk)
    if total != identity.size or _identity(fd) != identity:
        raise ValueError
    return b"".join(chunks), digest.hexdigest()


def _validate_profile(data: bytes, policy: SeccompPolicyLock) -> None:
    value = json.loads(
        data.decode("utf-8"),
        object_pairs_hook=_no_duplicate_keys,
        parse_constant=_reject_constant,
    )
    _depth(value)
    if _canonical_json(value) != data:
        raise ValueError
    if type(value) is not dict or set(value) != {"architectures", "defaultAction", "syscalls"}:
        raise ValueError
    if value["architectures"] != [policy.libseccomp_architecture] or value["defaultAction"] != "SCMP_ACT_ERRNO":
        raise ValueError
    rules = value["syscalls"]
    if type(rules) is not list:
        raise ValueError
    atoms = tuple(_parse_rule(rule) for rule in rules)
    if tuple(sorted(set(atoms), key=_atom_key)) != atoms:
        raise ValueError
    if not set(atoms) <= set(policy.allowed_rule_atoms):
        raise ValueError


def _parse_rule(value: object) -> SeccompRuleAtom:
    if type(value) is not dict or set(value) != {"action", "args", "names"}:
        raise ValueError
    if value["action"] != "SCMP_ACT_ALLOW" or type(value["names"]) is not list or len(value["names"]) != 1 or type(value["names"][0]) is not str:
        raise ValueError
    args = value["args"]
    if type(args) is not list:
        raise ValueError
    constraints = tuple(_parse_constraint(item) for item in args)
    if tuple(sorted(set(constraints), key=_constraint_key)) != constraints:
        raise ValueError
    return SeccompRuleAtom(value["names"][0], constraints)


def _parse_constraint(value: object) -> SeccompArgumentConstraint:
    if type(value) is not dict:
        raise ValueError
    masked = value.get("op") == "SCMP_CMP_MASKED_EQ"
    if set(value) != ({"index", "op", "value", "valueTwo"} if masked else {"index", "op", "value"}):
        raise ValueError
    index, op, number = value["index"], value["op"], value["value"]
    two = value.get("valueTwo")
    if (
        type(index) is not int or not 0 <= index <= 5 or type(op) is not str or op not in _OPS
        or type(number) is not int or not 0 <= number <= _U64_MAX
        or (masked and (type(two) is not int or not 0 <= two <= _U64_MAX))
    ):
        raise ValueError
    return SeccompArgumentConstraint(index, op, number, two)


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise ValueError


def _depth(value: object, level: int = 0) -> None:
    if level > _MAX_DEPTH:
        raise ValueError
    if type(value) is dict:
        for item in value.values():
            _depth(item, level + 1)
    elif type(value) is list:
        for item in value:
            _depth(item, level + 1)


def _atom_key(value: SeccompRuleAtom) -> tuple[str, tuple[tuple[int, str, int, bool, int], ...]]:
    return value.syscall, tuple(_constraint_key(item) for item in value.arguments)


def _constraint_key(value: SeccompArgumentConstraint) -> tuple[int, str, int, bool, int]:
    return value.index, value.op, value.value, value.value_two is not None, value.value_two or 0


def _close_quietly(fd: int) -> None:
    try:
        os.close(fd)
    except BaseException:
        pass


def _close_all(fds: tuple[int, ...] | list[int]) -> None:
    for fd in reversed(fds):
        _close_quietly(fd)
