"""Manager-side bounded qualification exchange for an admitted authority child."""

from __future__ import annotations

import os
import socket
import time
from typing import Any

from .authority_linux_launch import launch_authority_child
from .authority_qualification_entry import (
    AuthorityQualificationError,
    SOCKET_TIMEOUT_SECONDS,
    _binding,
    _frame,
    _peer,
    _read_frame,
    _validate_instance,
)


def _close_quietly(fd: int | None) -> None:
    if type(fd) is int and fd >= 0:
        try:
            os.close(fd)
        except OSError:
            pass


def _close_inputs(inputs: tuple[object, ...]) -> None:
    for fd in dict.fromkeys(fd for fd in inputs if type(fd) is int and fd >= 0):
        _close_quietly(fd)


def _close_bundle_quietly(bundle: object) -> None:
    try:
        bundle.close()
    except BaseException:
        pass


def _same_identity(actual: object, expected: dict[str, object]) -> bool:
    return all(
        getattr(actual, field, None) == expected[field]
        for field in (
            "interpreter_executable_sha256",
            "authority_bundle_sha256",
            "launch_profile_sha256",
        )
    )


def _connect(runtime_fd: int) -> socket.socket:
    directory = os.readlink(f"/proc/self/fd/{runtime_fd}")
    path = os.path.join(directory, "authority.sock")
    deadline = time.monotonic() + SOCKET_TIMEOUT_SECONDS
    while True:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        connection.settimeout(SOCKET_TIMEOUT_SECONDS)
        try:
            connection.connect(path)
            return connection
        except OSError:
            connection.close()
            if time.monotonic() >= deadline:
                raise ValueError
            time.sleep(0.01)


def run_authority_qualification(
    bundle: object,
    *,
    config_fd: int,
    session_key_fd: int,
    runtime_directory_fd: int,
    launch_instance_fd: int,
    cancel: bool = False,
) -> str:
    """Run one fixed authenticated exchange and render its safe outcome."""
    child: Any | None = None
    connection: socket.socket | None = None
    manager_key: int | None = None
    manager_runtime: int | None = None
    inputs = (config_fd, session_key_fd, runtime_directory_fd, launch_instance_fd)
    handoff = False
    try:
        if type(cancel) is not bool or any(
            type(fd) is not int or fd < 0 for fd in inputs
        ):
            raise ValueError
        instance = _validate_instance(os.pread(launch_instance_fd, 65536, 0))
        if not _same_identity(bundle._runtime_identity(), instance["runtime_identity"]):
            raise ValueError
        manager_key = os.dup(session_key_fd)
        manager_runtime = os.dup(runtime_directory_fd)
        key = os.pread(manager_key, 32, 0)
        if len(key) != 32:
            raise ValueError
        handoff = True
        child = launch_authority_child(
            bundle,
            config_fd=config_fd,
            session_key_fd=session_key_fd,
            runtime_directory_fd=runtime_directory_fd,
            launch_instance_fd=launch_instance_fd,
        )
        connection = _connect(manager_runtime)
        if _peer(connection) != child._process_identity():
            raise ValueError
        binding = _binding(instance)
        _read_frame(key, connection, instance["session_id"], 0, "ready", binding)
        connection.send(_frame(key, instance["session_id"], 0, "execute", binding))
        if cancel:
            connection.send(_frame(key, instance["session_id"], 1, "cancel", binding))
        terminal = {**binding, "terminal": "cancelled" if cancel else "completed"}
        _read_frame(key, connection, instance["session_id"], 1, "terminal", terminal)
        if child.wait(deadline=time.monotonic() + SOCKET_TIMEOUT_SECONDS) != "exited":
            raise ValueError
        child.close()
        return "qualification cancelled" if cancel else "qualification completed"
    except BaseException as error:
        if child is not None:
            try:
                child.close()
            except BaseException:
                pass
        if isinstance(error, AuthorityQualificationError):
            raise
        raise AuthorityQualificationError() from None
    finally:
        if connection is not None:
            connection.close()
        _close_quietly(manager_key)
        _close_quietly(manager_runtime)
        if not handoff:
            _close_inputs(inputs)
            _close_bundle_quietly(bundle)
