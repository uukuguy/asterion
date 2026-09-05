"""Self-contained entry and protocol helpers for authority qualification."""

# ruff: noqa: E402 -- script entry must secure descriptors before ordinary imports.

from __future__ import annotations

import os as _bootstrap_os
import sys as _bootstrap_sys


def _bootstrap_main() -> bool:
    """Perform the script-only checks before loading ordinary stdlib modules."""
    try:
        for descriptor in range(3, 10):
            _bootstrap_os.set_inheritable(descriptor, False)
        flags = _bootstrap_sys.flags
        if (
            flags.isolated != 1
            or flags.no_site != 1
            or flags.dont_write_bytecode != 1
            or _bootstrap_sys.prefix != "/proc/self/fd/7"
            or _bootstrap_sys.exec_prefix != "/proc/self/fd/7"
        ):
            return False
        for module in tuple(_bootstrap_sys.modules.values()):
            origin = getattr(module, "__file__", None)
            if origin is None:
                continue
            if type(origin) is not str:
                return False
            if origin == "/proc/self/fd/9":
                continue
            if not origin.startswith("/proc/self/fd/7/"):
                return False
        return True
    except BaseException:
        return False


if __name__ == "__main__" and not _bootstrap_main():
    _bootstrap_os._exit(127)

import hashlib
import hmac
import json
import os
import re
import select
import socket
import struct

DOMAIN = b"asterion.prime-p1-authority-qualification-ipc/v2\0"
PROTOCOL = "asterion.prime-p1-authority-qualification-ipc/v2"
MAX_PACKET_BYTES = 8192
SOCKET_TIMEOUT_SECONDS = 2.0
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_RUN_ID = re.compile(r"[a-z][a-z0-9.-]{0,127}\Z")
_INSTANCE_KEYS = frozenset(
    (
        "format",
        "purpose",
        "run_id",
        "session_id",
        "supervisor_pid",
        "supervisor_uid",
        "runtime_identity",
        "request_contract_sha256",
        "resource_set_sha256",
        "application_request_sha256",
        "workload_id",
    )
)
_IDENTITY_KEYS = frozenset(
    (
        "interpreter_executable_sha256",
        "authority_bundle_sha256",
        "launch_profile_sha256",
    )
)
_BINDING_KEYS = frozenset(
    (
        "run_id",
        "purpose",
        "workload_id",
        "runtime_identity",
        "request_contract_sha256",
        "resource_set_sha256",
        "application_request_sha256",
    )
)
_FRAME_KEYS = frozenset(
    ("protocol", "session_id", "sequence", "kind", "payload", "frame_hmac_sha256")
)


def _close_descriptor(descriptor: int) -> None:
    try:
        os.close(descriptor)
    except OSError:
        pass


def _restore_linux_parent_policy() -> int:
    """Re-arm and verify the two post-exec Linux process protections."""
    import ctypes

    parent = os.getppid()
    if parent <= 1:
        raise ValueError
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [ctypes.c_int] + [ctypes.c_ulong] * 4
    libc.prctl.restype = ctypes.c_int

    def prctl(option: int, argument: int = 0) -> None:
        if libc.prctl(option, argument, 0, 0, 0) != 0:
            raise ValueError

    prctl(4, 0)  # PR_SET_DUMPABLE
    prctl(1, 9)  # PR_SET_PDEATHSIG, SIGKILL
    if os.getppid() != parent:
        raise ValueError
    death_signal = ctypes.c_int()
    if libc.prctl(2, ctypes.addressof(death_signal), 0, 0, 0) != 0:
        raise ValueError
    if death_signal.value != 9 or libc.prctl(3, 0, 0, 0, 0) != 0:
        raise ValueError
    return parent


class AuthorityQualificationError(Exception):
    """Public-safe qualification failure."""

    def __init__(self) -> None:
        super().__init__("prime authority qualification is unavailable")


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _json(raw: bytes) -> object:
    def reject_constant(_: str) -> object:
        raise ValueError

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=unique, parse_constant=reject_constant)
    if _canonical(value) != raw:
        raise ValueError
    return value


def _is_sha256(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def _validate_instance(raw: bytes) -> dict[str, object]:
    value = _json(raw)
    if type(value) is not dict or set(value) != _INSTANCE_KEYS:
        raise ValueError
    if (
        value["format"] != "asterion.prime-p1-authority-launch-instance/v2"
        or value["purpose"] != "qualification"
        or value["workload_id"] != "bounded-ipc-qualification-v1"
        or type(value["run_id"]) is not str
        or _RUN_ID.fullmatch(value["run_id"]) is None
        or not _is_sha256(value["session_id"])
        or type(value["supervisor_pid"]) is not int
        or value["supervisor_pid"] <= 0
        or type(value["supervisor_uid"]) is not int
        or value["supervisor_uid"] < 0
        or any(
            not _is_sha256(value[key])
            for key in (
                "request_contract_sha256",
                "resource_set_sha256",
                "application_request_sha256",
            )
        )
    ):
        raise ValueError
    identity = value["runtime_identity"]
    if (
        type(identity) is not dict
        or set(identity) != _IDENTITY_KEYS
        or any(not _is_sha256(item) for item in identity.values())
    ):
        raise ValueError
    return value


def _binding(instance: dict[str, object]) -> dict[str, object]:
    return {key: instance[key] for key in sorted(_BINDING_KEYS)}


def _runtime_identity_from_inventory(raw: bytes) -> dict[str, str]:
    """Derive the three launch identities from the inherited release inventory."""
    release = _json(raw)
    if type(release) is not dict or set(release) != {
        "files",
        "format",
        "interpreter_path",
        "launch_profile",
        "release_version",
        "target",
    }:
        raise ValueError
    files = release["files"]
    profile = release["launch_profile"]
    target = release["target"]
    if type(files) is not list or type(profile) is not dict or type(target) is not dict:
        raise ValueError
    interpreter_records = [
        item
        for item in files
        if type(item) is dict
        and item.get("role") == "interpreter"
        and item.get("path") == "bin/python3"
        and _is_sha256(item.get("sha256"))
    ]
    if len(interpreter_records) != 1:
        raise ValueError
    interpreter = interpreter_records[0]["sha256"]
    bundle = hashlib.sha256(
        b"asterion.prime-p1-authority-bundle/v1\0"
        + _canonical(
            {
                "release_version": release["release_version"],
                "target": target,
                "interpreter_path": release["interpreter_path"],
                "files": files,
            }
        )
    ).hexdigest()
    launch_profile = dict(profile)
    launch_profile.update(
        {
            "target": target,
            "interpreter_executable_sha256": interpreter,
            "authority_bundle_sha256": bundle,
        }
    )
    launch = hashlib.sha256(
        b"asterion.prime-p1-authority-launch-profile/v1\0" + _canonical(launch_profile)
    ).hexdigest()
    return {
        "interpreter_executable_sha256": interpreter,
        "authority_bundle_sha256": bundle,
        "launch_profile_sha256": launch,
    }


def _frame(
    key: bytes, session_id: str, sequence: int, kind: str, payload: dict[str, object]
) -> bytes:
    if type(key) is not bytes or len(key) != 32:
        raise ValueError
    body: dict[str, object] = {
        "protocol": PROTOCOL,
        "session_id": session_id,
        "sequence": sequence,
        "kind": kind,
        "payload": payload,
    }
    body["frame_hmac_sha256"] = hmac.new(
        key, DOMAIN + _canonical(body), hashlib.sha256
    ).hexdigest()
    encoded = _canonical(body)
    if len(encoded) > MAX_PACKET_BYTES:
        raise ValueError
    return encoded


def _read_frame(
    key: bytes,
    connection: socket.socket,
    session_id: str,
    sequence: int,
    kind: str,
    payload: dict[str, object],
) -> None:
    raw = connection.recv(MAX_PACKET_BYTES + 1)
    if not raw or len(raw) > MAX_PACKET_BYTES:
        raise ValueError
    value = _json(raw)
    if type(value) is not dict or set(value) != _FRAME_KEYS:
        raise ValueError
    tag = value.pop("frame_hmac_sha256")
    if (
        not _is_sha256(tag)
        or value["protocol"] != PROTOCOL
        or value["session_id"] != session_id
        or type(value["sequence"]) is not int
        or value["sequence"] != sequence
        or value["kind"] != kind
        or value["payload"] != payload
    ):
        raise ValueError
    expected = hmac.new(key, DOMAIN + _canonical(value), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, tag):
        raise ValueError


def _peer(connection: socket.socket) -> tuple[int, int]:
    pid, uid, _ = struct.unpack(
        "3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
    )
    return pid, uid


def _read_optional_cancel(
    key: bytes, connection: socket.socket, instance: dict[str, object]
) -> bool:
    ready, _, _ = select.select((connection,), (), (), 0.15)
    if not ready:
        return False
    _read_frame(
        key, connection, instance["session_id"], 1, "cancel", _binding(instance)
    )
    return True


def _run_qualification_workload(
    key: bytes, connection: socket.socket, instance: dict[str, object]
) -> str:
    """Run the fixed finite workload; later P1 work may replace this hook."""
    for _ in range(3):
        if _read_optional_cancel(key, connection, instance):
            return "cancelled"
    return "completed"


def main() -> None:
    """Serve exactly one authenticated bounded qualification exchange."""
    server: socket.socket | None = None
    connection: socket.socket | None = None
    try:
        parent = _restore_linux_parent_policy()
        if not _bootstrap_main():
            raise ValueError
        instance = _validate_instance(os.pread(6, 65536, 0))
        _close_descriptor(6)
        if instance["supervisor_pid"] != parent:
            raise ValueError
        key = os.pread(4, 32, 0)
        _close_descriptor(4)
        inventory_size = os.fstat(8).st_size
        if (
            type(inventory_size) is not int
            or not 1 <= inventory_size <= 16 * 1024 * 1024
        ):
            raise ValueError
        inventory_identity = _runtime_identity_from_inventory(
            os.pread(8, inventory_size, 0)
        )
        _close_descriptor(8)
        if len(key) != 32 or inventory_identity != instance["runtime_identity"]:
            raise ValueError
        server = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        server.settimeout(SOCKET_TIMEOUT_SECONDS)
        server.bind("authority.sock")
        server.listen(1)
        connection, _ = server.accept()
        connection.settimeout(SOCKET_TIMEOUT_SECONDS)
        if _peer(connection) != (
            instance["supervisor_pid"],
            instance["supervisor_uid"],
        ):
            raise ValueError
        binding = _binding(instance)
        connection.send(_frame(key, instance["session_id"], 0, "ready", binding))
        _read_frame(key, connection, instance["session_id"], 0, "execute", binding)
        terminal = _run_qualification_workload(key, connection, instance)
        connection.send(
            _frame(
                key,
                instance["session_id"],
                1,
                "terminal",
                {**binding, "terminal": terminal},
            )
        )
    except BaseException:
        return
    finally:
        if connection is not None:
            connection.close()
        if server is not None:
            server.close()
        for descriptor in (3, 4, 5, 6, 7, 8, 9):
            _close_descriptor(descriptor)


if __name__ == "__main__":
    main()
