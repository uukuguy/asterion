"""Private, fail-closed release inventory records for an authority bundle."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import os
import re
import stat
import threading
from typing import NoReturn, SupportsIndex

from .image_input_lock import (
    ImagePlatformDescriptor,
    validate_image_platform_descriptor,
)

_FORMAT = "asterion.prime-p1-authority-bundle-release/v1"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_PART = re.compile(r"[A-Za-z0-9_.-]+\Z")
_ROLES = frozenset(
    (
        "bootstrap",
        "interpreter",
        "python-source",
        "native-extension",
        "shared-library",
        "distribution-metadata",
        "data",
    )
)
_MODES = frozenset((0o444, 0o555, 0o644, 0o755))


class AuthorityBundleError(Exception):
    """Public-safe rejection of a private authority bundle."""

    def __init__(self) -> None:
        super().__init__("prime authority bundle is unavailable")


@dataclass(frozen=True, slots=True, repr=False)
class AuthorityRuntimeIdentityV2:
    interpreter_executable_sha256: str
    authority_bundle_sha256: str
    launch_profile_sha256: str


@dataclass(frozen=True, slots=True, repr=False)
class AuthorityBundleFile:
    path: str
    role: str
    mode: int
    size: int
    sha256: str


@dataclass(frozen=True, slots=True, repr=False)
class AuthorityRlimits:
    cpu_seconds: int
    file_bytes: int
    open_files: int
    processes: int
    address_space_bytes: int


@dataclass(frozen=True, slots=True, repr=False)
class AuthoritySocketProfile:
    basename: str
    runtime_dir_role: str
    type: str
    max_clients: int
    peer_policy: str


@dataclass(frozen=True, slots=True, repr=False)
class AuthorityExternalRuntimeFile:
    path: str
    role: str
    mode: int
    size: int
    sha256: str


@dataclass(frozen=True, slots=True, repr=False)
class AuthorityLaunchProfile:
    profile_version: str
    bootstrap_path: str
    argv: tuple[str, ...]
    python_flags: tuple[str, ...]
    python_path: tuple[str, ...]
    environment: tuple[object, ...]
    cwd_role: str
    umask: int
    authority_uid: int
    authority_gid: int
    supplementary_gids: tuple[object, ...]
    capabilities: tuple[object, ...]
    no_new_privs: bool
    rlimits: AuthorityRlimits
    inherited_fds: tuple[tuple[int, str], ...]
    socket: AuthoritySocketProfile
    ipc_protocol: str
    receipt_format: str
    max_packet_bytes: int
    deadline_milliseconds: int
    external_runtime: tuple[AuthorityExternalRuntimeFile, ...]


@dataclass(frozen=True, slots=True, repr=False)
class AuthorityBundleRelease:
    release_version: str
    target: ImagePlatformDescriptor
    interpreter_path: str
    files: tuple[AuthorityBundleFile, ...]
    launch_profile: AuthorityLaunchProfile


_BUNDLE_TOKEN = object()
_SPAWN_TOKEN = object()


class _AuthoritySpawnDescriptors:
    __slots__ = ("_closed", "_lock", "bootstrap_fd", "interpreter_fd", "inventory_fd", "profile", "root_fd", "runtime_identity")

    def __init__(self, root_fd: int, inventory_fd: int, interpreter_fd: int, bootstrap_fd: int, identity: AuthorityRuntimeIdentityV2, profile: AuthorityLaunchProfile, *, _token: object | None = None) -> None:
        if type(self) is not _AuthoritySpawnDescriptors or _token is not _SPAWN_TOKEN:
            raise AuthorityBundleError()
        self._closed = False
        self._lock = threading.Lock()
        self.root_fd = root_fd
        self.inventory_fd = inventory_fd
        self.interpreter_fd = interpreter_fd
        self.bootstrap_fd = bootstrap_fd
        self.runtime_identity, self.profile = identity, profile

    def __repr__(self) -> str:
        return "AuthoritySpawnDescriptors(redacted)"

    def __reduce__(self) -> NoReturn:
        raise TypeError("prime authority bundle is unavailable")

    def __reduce_ex__(self, _: SupportsIndex) -> NoReturn:
        raise TypeError("prime authority bundle is unavailable")

    def __copy__(self) -> object:
        raise TypeError("prime authority bundle is unavailable")

    def __deepcopy__(self, _: object) -> object:
        raise TypeError("prime authority bundle is unavailable")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            fds = (
                self.bootstrap_fd,
                self.interpreter_fd,
                self.inventory_fd,
                self.root_fd,
            )
            self.root_fd = -1
            self.inventory_fd = -1
            self.interpreter_fd = -1
            self.bootstrap_fd = -1
        for fd in fds:
            try:
                os.close(fd)
            except OSError:
                pass


class AdmittedAuthorityBundle:
    __slots__ = (
        "_closed",
        "_identity",
        "_interpreter_fd",
        "_inventory_bytes",
        "_inventory_fd",
        "_inventory_identity",
        "_lock",
        "_release",
        "_root_fd",
        "_root_identity",
        "_interpreter_identity",
    )

    def __init__(
        self,
        root_fd: int,
        inventory_fd: int,
        interpreter_fd: int,
        inventory_bytes: bytes,
        inventory_identity: tuple[int, ...],
        root_identity: tuple[int, ...],
        interpreter_identity: tuple[int, ...],
        release: AuthorityBundleRelease,
        identity: AuthorityRuntimeIdentityV2,
        *,
        _token: object | None = None,
    ) -> None:
        if type(self) is not AdmittedAuthorityBundle or _token is not _BUNDLE_TOKEN:
            raise AuthorityBundleError()
        self._closed, self._root_fd, self._inventory_fd, self._interpreter_fd = (
            False,
            root_fd,
            inventory_fd,
            interpreter_fd,
        )
        (
            self._inventory_bytes,
            self._inventory_identity,
            self._root_identity,
            self._interpreter_identity,
        ) = inventory_bytes, inventory_identity, root_identity, interpreter_identity
        self._release, self._identity, self._lock = release, identity, threading.Lock()

    def __repr__(self) -> str:
        return "AdmittedAuthorityBundle(redacted)"

    def __reduce__(self) -> NoReturn:
        raise TypeError("prime authority bundle is unavailable")

    def __reduce_ex__(self, _: SupportsIndex) -> NoReturn:
        raise TypeError("prime authority bundle is unavailable")

    def __copy__(self) -> object:
        raise TypeError("prime authority bundle is unavailable")

    def __deepcopy__(self, _: object) -> object:
        raise TypeError("prime authority bundle is unavailable")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for fd in (self._interpreter_fd, self._inventory_fd, self._root_fd):
                try:
                    os.close(fd)
                except OSError:
                    pass

    def _runtime_identity(self) -> AuthorityRuntimeIdentityV2:
        with self._lock:
            if self._closed:
                raise AuthorityBundleError()
            release, expected = self._release, self._identity
        identity = declared_authority_runtime_identity(release)
        with self._lock:
            if self._closed:
                raise AuthorityBundleError()
            accepted = _runtime_identity_fields(expected) and _same_runtime_identity(
                identity, expected
            )
        if not accepted:
            self.close()
            raise AuthorityBundleError()
        return identity

    def _revalidate_for_spawn(self) -> None:
        try:
            with self._lock:
                if self._closed:
                    raise ValueError
                if _fd_identity(self._inventory_fd) != self._inventory_identity:
                    raise ValueError
                inventory_bytes = _read_fd(self._inventory_fd)
                if (
                    inventory_bytes != self._inventory_bytes
                    or _fd_identity(self._inventory_fd) != self._inventory_identity
                ):
                    raise ValueError
                from .authority_bundle_files import (
                    verify_authority_bundle_files,
                    verify_external_runtime_files,
                )

                verified = verify_authority_bundle_files(
                    self._root_fd,
                    self._release.files,
                    self._release.interpreter_path,
                    self._release.target,
                    _devino(self._inventory_identity),
                )
                try:
                    if (
                        verified.root_identity != self._root_identity
                        or verified.interpreter_identity != self._interpreter_identity
                        or _digest_fd(self._interpreter_fd, self._interpreter_identity)
                        != self._identity.interpreter_executable_sha256
                    ):
                        raise ValueError
                    verify_external_runtime_files(
                        self._release.launch_profile.external_runtime
                    )
                finally:
                    os.close(verified.interpreter_fd)
        except BaseException:
            self.close()
            raise AuthorityBundleError() from None

    def _consume_spawn_descriptors(self) -> _AuthoritySpawnDescriptors:
        bootstrap_fd: int | None = None
        try:
            with self._lock:
                if self._closed:
                    raise ValueError
                release, identity = self._release, self._identity
            self._revalidate_for_spawn()
            from .authority_bundle_files import verify_authority_bundle_bootstrap

            bootstrap_fd = verify_authority_bundle_bootstrap(
                self._root_fd,
                release.files,
                release.launch_profile.bootstrap_path,
                _devino(self._inventory_identity),
            )
            with self._lock:
                if self._closed:
                    raise ValueError
                result = _AuthoritySpawnDescriptors(
                    self._root_fd,
                    self._inventory_fd,
                    self._interpreter_fd,
                    bootstrap_fd,
                    identity,
                    release.launch_profile,
                    _token=_SPAWN_TOKEN,
                )
                self._closed = True
                self._root_fd = self._inventory_fd = self._interpreter_fd = -1
                bootstrap_fd = None
                return result
        except BaseException:
            if bootstrap_fd is not None:
                try:
                    os.close(bootstrap_fd)
                except OSError:
                    pass
            self.close()
            raise AuthorityBundleError() from None


def _fd_identity(fd: int) -> tuple[int, ...]:
    info = os.fstat(fd)
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _devino(identity: tuple[int, ...]) -> tuple[int, int]:
    return identity[0], identity[1]


def _read_fd(fd: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks = []
    while chunk := os.read(fd, 1024 * 1024):
        if sum(map(len, chunks)) + len(chunk) > 16 * 1024 * 1024:
            raise ValueError
        chunks.append(chunk)
    return b"".join(chunks)


def _digest_fd(fd: int, identity: tuple[int, ...]) -> str:
    digest, total = hashlib.sha256(), 0
    os.lseek(fd, 0, os.SEEK_SET)
    while chunk := os.read(fd, 1024 * 1024):
        total += len(chunk)
        if total > 512 * 1024 * 1024:
            raise ValueError
        digest.update(chunk)
    if total != identity[6] or _fd_identity(fd) != identity:
        raise ValueError
    return digest.hexdigest()


def _runtime_identity_fields(value: object) -> bool:
    return type(value) is AuthorityRuntimeIdentityV2 and all(
        type(field) is str and _SHA.fullmatch(field) is not None
        for field in (
            value.interpreter_executable_sha256,
            value.authority_bundle_sha256,
            value.launch_profile_sha256,
        )
    )


def _same_runtime_identity(
    actual: AuthorityRuntimeIdentityV2, expected: AuthorityRuntimeIdentityV2
) -> bool:
    return all(
        hmac.compare_digest(left, right)
        for left, right in zip(
            (
                actual.interpreter_executable_sha256,
                actual.authority_bundle_sha256,
                actual.launch_profile_sha256,
            ),
            (
                expected.interpreter_executable_sha256,
                expected.authority_bundle_sha256,
                expected.launch_profile_sha256,
            ),
            strict=True,
        )
    )


def admit_authority_bundle(
    bundle_root_fd: int,
    release_inventory_fd: int,
    selected_target: ImagePlatformDescriptor,
    expected_identity: AuthorityRuntimeIdentityV2,
) -> AdmittedAuthorityBundle:
    """Take custody of exact descriptors and admit one verified private release."""
    owned = tuple(
        dict.fromkeys(
            fd for fd in (bundle_root_fd, release_inventory_fd) if type(fd) is int and fd >= 0
        )
    )
    interpreter_fd: int | None = None
    try:
        if (
            type(bundle_root_fd) is not int
            or bundle_root_fd < 0
            or type(release_inventory_fd) is not int
            or release_inventory_fd < 0
            or bundle_root_fd == release_inventory_fd
            or not _runtime_identity_fields(expected_identity)
        ):
            raise ValueError
        for fd in owned:
            os.set_inheritable(fd, False)
        target = validate_image_platform_descriptor(selected_target)
        inventory_identity = _fd_identity(release_inventory_fd)
        if (
            not stat.S_ISREG(inventory_identity[2])
            or inventory_identity[3] != 0
            or inventory_identity[5] != 1
            or inventory_identity[2] & 0o022
            or inventory_identity[6] > 16 * 1024 * 1024
        ):
            raise ValueError
        raw = _read_fd(release_inventory_fd)
        if _fd_identity(release_inventory_fd) != inventory_identity:
            raise ValueError
        release = parse_authority_bundle_release(raw)
        if release.target != target:
            raise ValueError
        identity = declared_authority_runtime_identity(release)
        if not _same_runtime_identity(identity, expected_identity):
            raise ValueError
        from .authority_bundle_files import (
            verify_authority_bundle_files,
            verify_external_runtime_files,
        )

        verified = verify_authority_bundle_files(
            bundle_root_fd,
            release.files,
            release.interpreter_path,
            target,
            _devino(inventory_identity),
        )
        interpreter_fd = verified.interpreter_fd
        if (
            _digest_fd(interpreter_fd, verified.interpreter_identity)
            != identity.interpreter_executable_sha256
        ):
            raise ValueError
        verify_external_runtime_files(release.launch_profile.external_runtime)
        result = AdmittedAuthorityBundle(
            bundle_root_fd,
            release_inventory_fd,
            interpreter_fd,
            raw,
            inventory_identity,
            verified.root_identity,
            verified.interpreter_identity,
            release,
            identity,
            _token=_BUNDLE_TOKEN,
        )
        interpreter_fd = None
        return result
    except BaseException:
        if interpreter_fd is not None:
            try:
                os.close(interpreter_fd)
            except OSError:
                pass
        raise AuthorityBundleError() from None
    finally:
        if interpreter_fd is not None or "result" not in locals():
            for fd in owned:
                try:
                    os.close(fd)
                except OSError:
                    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _path(value: object) -> str:
    if type(value) is not str or not value or value.startswith("/") or "\\" in value:
        raise ValueError
    parts = value.split("/")
    if any(part in {"", ".", ".."} or _PART.fullmatch(part) is None for part in parts):
        raise ValueError
    return value


def _absolute_path(value: object) -> str:
    if type(value) is not str or not value.startswith("/") or "\\" in value:
        raise ValueError
    parts = value[1:].split("/")
    if any(part in {"", ".", ".."} or _PART.fullmatch(part) is None for part in parts):
        raise ValueError
    return value


def _integer(value: object, maximum: int) -> int:
    if type(value) is not int or not 0 < value <= maximum:
        raise ValueError
    return value


def _size(value: object) -> int:
    if type(value) is not int or not 0 <= value <= 512 * 1024 * 1024:
        raise ValueError
    return value


def _file(
    value: object, external: bool = False
) -> AuthorityBundleFile | AuthorityExternalRuntimeFile:
    if type(value) is not dict or set(value) != {
        "path",
        "role",
        "mode",
        "size",
        "sha256",
    }:
        raise ValueError
    path = _absolute_path(value["path"]) if external else _path(value["path"])
    role = value["role"]
    if type(role) is not str or role not in (
        _ROLES if not external else {"elf-loader", "shared-library"}
    ):
        raise ValueError
    mode, size, digest = value["mode"], value["size"], value["sha256"]
    if (
        type(mode) is not int
        or mode not in _MODES
        or type(digest) is not str
        or _SHA.fullmatch(digest) is None
    ):
        raise ValueError
    _size(size)
    if external:
        return AuthorityExternalRuntimeFile(path, role, mode, size, digest)
    if any(
        path.endswith(suffix)
        for suffix in (".pyc", ".pyo", ".pth", ".egg-link", "direct_url.json")
    ) or path.endswith(("sitecustomize.py", "usercustomize.py")):
        raise ValueError
    return AuthorityBundleFile(path, role, mode, size, digest)


def _profile(value: object, directories: tuple[str, ...]) -> AuthorityLaunchProfile:
    keys = {
        "profile_version",
        "bootstrap_path",
        "argv",
        "python_flags",
        "python_path",
        "environment",
        "cwd_role",
        "umask",
        "authority_uid",
        "authority_gid",
        "supplementary_gids",
        "capabilities",
        "no_new_privs",
        "rlimits",
        "inherited_fds",
        "socket",
        "ipc_protocol",
        "receipt_format",
        "max_packet_bytes",
        "deadline_milliseconds",
        "external_runtime",
    }
    if type(value) is not dict or set(value) != keys:
        raise ValueError
    if (
        value["profile_version"] != "1.0.0"
        or value["python_flags"] != ["-I", "-S", "-B"]
        or value["argv"]
        != ["/proc/self/fd/7/bin/python3", "-I", "-S", "-B", "/proc/self/fd/9"]
        or value["environment"] != {}
        or value["cwd_role"] != "runtime-directory"
        or type(value["umask"]) is not int
        or value["umask"] != 63
        or value["supplementary_gids"] != []
        or value["capabilities"] != []
        or value["no_new_privs"] is not True
        or value["ipc_protocol"] != "asterion.prime-p1-authority-ipc/v2"
        or value["receipt_format"] != "asterion.prime-p1-authority-receipt/v2"
        or type(value["max_packet_bytes"]) is not int
        or value["max_packet_bytes"] != 8192
        or type(value["deadline_milliseconds"]) is not int
        or value["deadline_milliseconds"] != 60000
    ):
        raise ValueError
    bootstrap = _path(value["bootstrap_path"])
    python_path = value["python_path"]
    if (
        type(python_path) is not list
        or not python_path
        or tuple(python_path) != tuple(sorted(set(python_path)))
        or any(_path(path) not in directories for path in python_path)
    ):
        raise ValueError
    uid, gid = (
        _integer(value["authority_uid"], 4294967294),
        _integer(value["authority_gid"], 4294967294),
    )
    limits = value["rlimits"]
    limit_keys = (
        "cpu_seconds",
        "file_bytes",
        "open_files",
        "processes",
        "address_space_bytes",
    )
    bounds = (120, 16777216, 256, 64, 2147483648)
    if type(limits) is not dict or set(limits) != set(limit_keys):
        raise ValueError
    rlimits = AuthorityRlimits(
        *(
            _integer(limits[key], bound)
            for key, bound in zip(limit_keys, bounds, strict=True)
        )
    )
    expected_fds = [
        {"fd": fd, "role": role}
        for fd, role in (
            (3, "config"),
            (4, "session-key"),
            (5, "runtime-directory"),
            (6, "launch-instance"),
            (7, "bundle-root"),
            (8, "release-inventory"),
            (9, "bootstrap"),
        )
    ]
    inherited = value["inherited_fds"]
    socket = value["socket"]
    if (
        type(inherited) is not list
        or len(inherited) != len(expected_fds)
        or any(
            type(item) is not dict
            or set(item) != {"fd", "role"}
            or type(item["fd"]) is not int
            or type(item["role"]) is not str
            for item in inherited
        )
        or inherited != expected_fds
        or type(socket) is not dict
        or set(socket) != {"basename", "runtime_dir_role", "type", "max_clients", "peer_policy"}
        or type(socket["basename"]) is not str
        or type(socket["runtime_dir_role"]) is not str
        or type(socket["type"]) is not str
        or type(socket["max_clients"]) is not int
        or type(socket["peer_policy"]) is not str
        or socket != {
        "basename": "authority.sock",
        "runtime_dir_role": "runtime-directory",
        "type": "SOCK_SEQPACKET",
        "max_clients": 1,
        "peer_policy": "exact-supervisor-pid-uid",
        }
    ):
        raise ValueError
    external = value["external_runtime"]
    if type(external) is not list or len(external) > 512:
        raise ValueError
    external_records: list[AuthorityExternalRuntimeFile] = []
    for item in external:
        record = _file(item, True)
        if type(record) is not AuthorityExternalRuntimeFile:
            raise ValueError
        external_records.append(record)
    ext = tuple(external_records)
    if tuple(item.path for item in ext) != tuple(sorted({item.path for item in ext})):
        raise ValueError
    return AuthorityLaunchProfile(
        "1.0.0",
        bootstrap,
        tuple(value["argv"]),
        tuple(value["python_flags"]),
        tuple(python_path),
        (),
        "runtime-directory",
        63,
        uid,
        gid,
        (),
        (),
        True,
        rlimits,
        tuple((item["fd"], item["role"]) for item in expected_fds),
        AuthoritySocketProfile(
            "authority.sock",
            "runtime-directory",
            "SOCK_SEQPACKET",
            1,
            "exact-supervisor-pid-uid",
        ),
        "asterion.prime-p1-authority-ipc/v2",
        "asterion.prime-p1-authority-receipt/v2",
        8192,
        60000,
        ext,
    )


def parse_authority_bundle_release(data: bytes) -> AuthorityBundleRelease:
    try:
        if (
            type(data) is not bytes
            or not data
            or len(data) > 16 * 1024 * 1024
            or data.startswith(b"\xef\xbb\xbf")
        ):
            raise ValueError
        value = json.loads(
            data.decode("utf-8"),
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError),
            object_pairs_hook=lambda pairs: _unique_object(pairs),
        )
        _depth(value)
        if (
            _canonical(value) != data
            or type(value) is not dict
            or set(value)
            != {
                "format",
                "release_version",
                "target",
                "interpreter_path",
                "files",
                "launch_profile",
            }
            or value["format"] != _FORMAT
            or value["release_version"] != "2.0.0"
        ):
            raise ValueError
        if type(value["target"]) is not dict or set(value["target"]) != {
            "os",
            "architecture",
            "variant",
        }:
            raise ValueError
        target = validate_image_platform_descriptor(
            ImagePlatformDescriptor(**value["target"])
        )
        if (
            target
            not in (
                ImagePlatformDescriptor("linux", "arm64", None),
                ImagePlatformDescriptor("linux", "amd64", None),
            )
            or value["interpreter_path"] != "bin/python3"
        ):
            raise ValueError
        files_value = value["files"]
        if (
            type(files_value) is not list
            or not files_value
            or len(files_value) > 100000
        ):
            raise ValueError
        file_records: list[AuthorityBundleFile] = []
        for item in files_value:
            record = _file(item)
            if type(record) is not AuthorityBundleFile:
                raise ValueError
            file_records.append(record)
        files = tuple(file_records)
        if (
            tuple(item.path for item in files)
            != tuple(sorted({item.path for item in files}))
            or sum(item.size for item in files) > 2 * 1024 * 1024 * 1024
        ):
            raise ValueError
        if (
            sum(item.role == "interpreter" for item in files) != 1
            or sum(item.role == "bootstrap" for item in files) != 1
            or files[[item.path for item in files].index("bin/python3")].role
            != "interpreter"
            or files[[item.role for item in files].index("interpreter")].mode
            not in {0o555, 0o755}
        ):
            raise ValueError
        directories = tuple(
            sorted(
                {
                    "/".join(item.path.split("/")[:index])
                    for item in files
                    for index in range(1, len(item.path.split("/")))
                }
            )
        )
        profile = _profile(value["launch_profile"], directories)
        if (
            sum(
                item.path == profile.bootstrap_path and item.role == "bootstrap"
                for item in files
            )
            != 1
        ):
            raise ValueError
        return AuthorityBundleRelease("2.0.0", target, "bin/python3", files, profile)
    except BaseException:
        raise AuthorityBundleError() from None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _depth(value: object, level: int = 0) -> None:
    if level > 16:
        raise ValueError
    if type(value) is dict:
        for item in value.values():
            _depth(item, level + 1)
    elif type(value) is list:
        for item in value:
            _depth(item, level + 1)


def declared_authority_runtime_identity(
    release: AuthorityBundleRelease,
) -> AuthorityRuntimeIdentityV2:
    try:
        release = parse_authority_bundle_release(_canonical(_release_projection(release)))
        target_record = validate_image_platform_descriptor(release.target)
        if target_record not in (
            ImagePlatformDescriptor("linux", "arm64", None),
            ImagePlatformDescriptor("linux", "amd64", None),
        ):
            raise ValueError
        target = {
            "os": target_record.os,
            "architecture": target_record.architecture,
            "variant": target_record.variant,
        }
        files = [
            {
                "path": f.path,
                "role": f.role,
                "mode": f.mode,
                "size": f.size,
                "sha256": f.sha256,
            }
            for f in release.files
        ]
        interpreter = next(
            file.sha256
            for file in release.files
            if file.role == "interpreter" and file.path == "bin/python3"
        )
        bundle = hashlib.sha256(
            b"asterion.prime-p1-authority-bundle/v1\0"
            + _canonical(
                {
                    "release_version": release.release_version,
                    "target": target,
                    "interpreter_path": release.interpreter_path,
                    "files": files,
                }
            )
        ).hexdigest()
        profile = _profile_projection(release.launch_profile)
        profile.update(
            {
                "target": target,
                "interpreter_executable_sha256": interpreter,
                "authority_bundle_sha256": bundle,
            }
        )
        launch = hashlib.sha256(
            b"asterion.prime-p1-authority-launch-profile/v1\0" + _canonical(profile)
        ).hexdigest()
        return AuthorityRuntimeIdentityV2(interpreter, bundle, launch)
    except BaseException:
        raise AuthorityBundleError() from None


def _release_projection(release: object) -> dict[str, object]:
    if type(release) is not AuthorityBundleRelease:
        raise ValueError
    target = validate_image_platform_descriptor(release.target)
    return {
        "format": _FORMAT,
        "release_version": release.release_version,
        "target": {"os": target.os, "architecture": target.architecture, "variant": target.variant},
        "interpreter_path": release.interpreter_path,
        "files": [
            {"path": item.path, "role": item.role, "mode": item.mode, "size": item.size, "sha256": item.sha256}
            for item in release.files
        ],
        "launch_profile": _profile_projection(release.launch_profile),
    }


def _profile_projection(profile: object) -> dict[str, object]:
    if (
        type(profile) is not AuthorityLaunchProfile
        or type(profile.rlimits) is not AuthorityRlimits
        or type(profile.socket) is not AuthoritySocketProfile
        or type(profile.external_runtime) is not tuple
    ):
        raise ValueError
    if (
        profile.profile_version != "1.0.0"
        or profile.argv
        != ("/proc/self/fd/7/bin/python3", "-I", "-S", "-B", "/proc/self/fd/9")
        or profile.python_flags != ("-I", "-S", "-B")
        or profile.environment != ()
        or profile.cwd_role != "runtime-directory"
        or type(profile.umask) is not int
        or profile.umask != 63
        or profile.supplementary_gids != ()
        or profile.capabilities != ()
        or profile.no_new_privs is not True
        or profile.ipc_protocol != "asterion.prime-p1-authority-ipc/v2"
        or profile.receipt_format != "asterion.prime-p1-authority-receipt/v2"
        or type(profile.max_packet_bytes) is not int
        or profile.max_packet_bytes != 8192
        or type(profile.deadline_milliseconds) is not int
        or profile.deadline_milliseconds != 60000
    ):
        raise ValueError
    _path(profile.bootstrap_path)
    if (
        type(profile.python_path) is not tuple
        or not profile.python_path
        or tuple(sorted(set(profile.python_path))) != profile.python_path
    ):
        raise ValueError
    for item in profile.python_path:
        _path(item)
    _integer(profile.authority_uid, 4294967294)
    _integer(profile.authority_gid, 4294967294)
    for key, bound in zip(
        ("cpu_seconds", "file_bytes", "open_files", "processes", "address_space_bytes"),
        (120, 16777216, 256, 64, 2147483648),
        strict=True,
    ):
        _integer(getattr(profile.rlimits, key), bound)
    if profile.inherited_fds != (
        (3, "config"),
        (4, "session-key"),
        (5, "runtime-directory"),
        (6, "launch-instance"),
        (7, "bundle-root"),
        (8, "release-inventory"),
        (9, "bootstrap"),
    ) or profile.socket != AuthoritySocketProfile(
        "authority.sock",
        "runtime-directory",
        "SOCK_SEQPACKET",
        1,
        "exact-supervisor-pid-uid",
    ):
        raise ValueError
    external = []
    for item in profile.external_runtime:
        if type(item) is not AuthorityExternalRuntimeFile:
            raise ValueError
        _absolute_path(item.path)
        _size(item.size)
        if (
            item.role not in {"elf-loader", "shared-library"}
            or item.mode not in _MODES
            or type(item.sha256) is not str
            or _SHA.fullmatch(item.sha256) is None
        ):
            raise ValueError
        external.append(
            {
                "path": item.path,
                "role": item.role,
                "mode": item.mode,
                "size": item.size,
                "sha256": item.sha256,
            }
        )
    if tuple(item["path"] for item in external) != tuple(
        sorted({item["path"] for item in external})
    ):
        raise ValueError
    return {
        "profile_version": profile.profile_version,
        "bootstrap_path": profile.bootstrap_path,
        "argv": list(profile.argv),
        "python_flags": list(profile.python_flags),
        "python_path": list(profile.python_path),
        "environment": {},
        "cwd_role": profile.cwd_role,
        "umask": profile.umask,
        "authority_uid": profile.authority_uid,
        "authority_gid": profile.authority_gid,
        "supplementary_gids": [],
        "capabilities": [],
        "no_new_privs": profile.no_new_privs,
        "rlimits": {
            key: getattr(profile.rlimits, key)
            for key in (
                "cpu_seconds",
                "file_bytes",
                "open_files",
                "processes",
                "address_space_bytes",
            )
        },
        "inherited_fds": [
            {"fd": fd, "role": role} for fd, role in profile.inherited_fds
        ],
        "socket": {
            "basename": profile.socket.basename,
            "runtime_dir_role": profile.socket.runtime_dir_role,
            "type": profile.socket.type,
            "max_clients": profile.socket.max_clients,
            "peer_policy": profile.socket.peer_policy,
        },
        "ipc_protocol": profile.ipc_protocol,
        "receipt_format": profile.receipt_format,
        "max_packet_bytes": profile.max_packet_bytes,
        "deadline_milliseconds": profile.deadline_milliseconds,
        "external_runtime": external,
    }
