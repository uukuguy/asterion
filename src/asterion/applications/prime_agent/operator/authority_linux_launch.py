"""Private Linux authority child-launch primitive."""

from __future__ import annotations

import os
import resource
import fcntl
import stat
import select
import signal
import sys
import threading
import time
import math
import errno
from typing import Literal, NoReturn, SupportsIndex

from .authority_bundle import AdmittedAuthorityBundle
from .authority_linux_policy import apply_linux_identity_policy, prepare_linux_identity_policy

_CHILD_TOKEN = object()
_ChildStatus = Literal["exited", "failed", "cancelled", "timed-out"]


class AuthorityLinuxLaunchError(Exception):
    def __init__(self) -> None:
        super().__init__("prime authority launch is unavailable")


class AuthorityLinuxChild:
    __slots__ = ("_closed", "_deadline", "_lock", "_ownership_lost", "_pid", "_reaped", "_signalled", "_status", "_terminal_reason", "_uid")

    def __init__(self, pid: int, uid: int, deadline: float, *, _token: object | None = None) -> None:
        if type(self) is not AuthorityLinuxChild or _token is not _CHILD_TOKEN:
            raise AuthorityLinuxLaunchError()
        self._closed = False
        self._deadline = deadline
        self._lock = threading.Lock()
        self._pid, self._uid = pid, uid
        self._status: _ChildStatus | None = None
        self._terminal_reason: Literal["cancelled", "timed-out"] | None = None
        self._ownership_lost = self._reaped = self._signalled = False

    def __repr__(self) -> str:
        return "AuthorityLinuxChild(redacted)"

    def __reduce__(self) -> NoReturn:
        raise TypeError("prime authority launch is unavailable")

    def __reduce_ex__(self, _: SupportsIndex) -> NoReturn:
        raise TypeError("prime authority launch is unavailable")

    def __copy__(self) -> NoReturn:
        raise TypeError("prime authority launch is unavailable")

    def __deepcopy__(self, _: object) -> NoReturn:
        raise TypeError("prime authority launch is unavailable")

    def _process_identity(self) -> tuple[int, int]:
        return self._pid, self._uid

    def wait(self, *, deadline: float | None = None) -> _ChildStatus:
        if deadline is not None and (type(deadline) not in (int, float) or not math.isfinite(deadline)):
            raise AuthorityLinuxLaunchError()
        limit = self._deadline if deadline is None else min(deadline, self._deadline)
        while True:
            with self._lock:
                if self._status is not None:
                    return self._status
                try:
                    observed = os.waitid(os.P_PID, self._pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                except ChildProcessError:
                    self._ownership_lost = True
                    raise AuthorityLinuxLaunchError() from None
                if observed is not None:
                    if not self._signalled:
                        self._signal_locked()
                    _, status = os.waitpid(self._pid, 0)
                    self._reaped = True
                    self._status = self._terminal_reason or ("exited" if os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0 else "failed")
                    return self._status
                if time.monotonic() >= limit:
                    if self._terminal_reason is None:
                        self._terminal_reason = "timed-out"
                    self._signal_locked()
                    os.waitpid(self._pid, 0)
                    self._reaped = True
                    self._status = self._terminal_reason or "timed-out"
                    return self._status
            time.sleep(0.01)

    def cancel(self) -> None:
        with self._lock:
            if self._reaped or self._status is not None:
                return
            self._terminal_reason = "cancelled"
            self._signal_locked()

    def close(self) -> None:
        self.cancel()
        self.wait(deadline=time.monotonic())
        with self._lock:
            self._closed = True

    def _signal_locked(self) -> None:
        if self._signalled or self._reaped or self._ownership_lost:
            return
        if not _owned_child(self._pid):
            self._ownership_lost = True
            return
        try:
            os.killpg(self._pid, signal.SIGKILL)
        except OSError as error:
            if error.errno == errno.ESRCH:
                try:
                    observed = os.waitid(
                        os.P_PID, self._pid, os.WEXITED | os.WNOHANG | os.WNOWAIT
                    )
                except ChildProcessError:
                    self._ownership_lost = True
                    raise AuthorityLinuxLaunchError() from None
                if observed is not None:
                    return
            try:
                os.kill(self._pid, signal.SIGKILL)
            except OSError:
                raise AuthorityLinuxLaunchError() from None
        else:
            self._signalled = True


def launch_authority_child(bundle: AdmittedAuthorityBundle, *, config_fd: int, session_key_fd: int, runtime_directory_fd: int, launch_instance_fd: int) -> AuthorityLinuxChild:
    """Consume one admitted bundle and manager-owned descriptors into one child."""
    supplied_fds = (
        config_fd,
        session_key_fd,
        runtime_directory_fd,
        launch_instance_fd,
    )
    input_fds = list(
        dict.fromkeys(
            fd for fd in supplied_fds if type(fd) is int and fd >= 0
        )
    )
    descriptors = None
    staged: list[int] = []
    status_read: int | None = None
    status_write: int | None = None
    pid: int | None = None
    old_mask: set[int] | None = None
    prepared_policy = None
    try:
        if sys.platform != "linux" or os.geteuid() != 0 or len(os.listdir("/proc/self/task")) != 1 or type(bundle) is not AdmittedAuthorityBundle or any(type(fd) is not int or fd < 0 for fd in supplied_fds) or len(set(supplied_fds)) != 4:
            raise ValueError
        for fd in input_fds:
            os.set_inheritable(fd, False)
        _sealed_inputs(config_fd, session_key_fd, launch_instance_fd)
        descriptors = bundle._consume_spawn_descriptors()
        profile = descriptors.profile
        if profile.rlimits.open_files < 32:
            raise ValueError
        runtime = os.fstat(runtime_directory_fd)
        if not stat.S_ISDIR(runtime.st_mode) or stat.S_IMODE(runtime.st_mode) != 0o700 or runtime.st_uid != profile.authority_uid or runtime.st_gid != profile.authority_gid or os.listdir(runtime_directory_fd):
            raise ValueError
        sources = (*input_fds, descriptors.root_fd, descriptors.inventory_fd, descriptors.bootstrap_fd, descriptors.interpreter_fd)
        if len(set(sources)) != 8 or len({(os.fstat(fd).st_dev, os.fstat(fd).st_ino) for fd in sources}) != 8:
            raise ValueError
        for fd in sources:
            staged.append(fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 10))
        if len(set(staged)) != len(staged):
            raise ValueError
        for fd in (staged[0], staged[1], staged[3], staged[5], staged[6]):
            os.lseek(fd, 0, os.SEEK_SET)
        if os.fstat(runtime_directory_fd) != runtime or os.listdir(runtime_directory_fd):
            raise ValueError
        _close_registered(input_fds)
        descriptors.close()
        descriptors = None
        status_read, status_write = os.pipe2(os.O_CLOEXEC)
        staged_status_write = fcntl.fcntl(status_write, fcntl.F_DUPFD_CLOEXEC, 10)
        _close_registered_fd(status_write)
        status_write = staged_status_write
        expected_parent = os.getpid()
        deadline = time.monotonic() + profile.deadline_milliseconds / 1000
        blocked = set(signal.valid_signals()) - {signal.SIGKILL, signal.SIGSTOP}
        old_mask = set(signal.pthread_sigmask(signal.SIG_BLOCK, blocked))
        _prepare_manager_child_reaping()
        prepared_policy = prepare_linux_identity_policy()
        if len(os.listdir("/proc/self/task")) != 1:
            raise ValueError
        pid = os.fork()
        if pid == 0:
            try:
                os.setsid()
                apply_linux_identity_policy(
                    prepared_policy,
                    authority_uid=profile.authority_uid,
                    authority_gid=profile.authority_gid,
                    expected_parent_pid=expected_parent,
                )
                for target, source in zip((3, 4, 5, 6, 7, 8, 9), staged[:7], strict=True):
                    os.dup2(source, target, inheritable=True)
                null = os.open("/dev/null", os.O_RDWR)
                for target in (0, 1, 2):
                    os.dup2(null, target)
                for limit, value in zip(
                    (resource.RLIMIT_CPU, resource.RLIMIT_FSIZE, resource.RLIMIT_NOFILE, resource.RLIMIT_NPROC, resource.RLIMIT_AS),
                    (profile.rlimits.cpu_seconds, profile.rlimits.file_bytes, profile.rlimits.open_files, profile.rlimits.processes, profile.rlimits.address_space_bytes),
                    strict=True,
                ):
                    resource.setrlimit(limit, (value, value))
                os.fchdir(5)
                os.umask(profile.umask)
                for name in os.listdir("/proc/self/fd"):
                    fd = int(name)
                    if fd > 9 and fd not in (staged[7], status_write):
                        try:
                            os.close(fd)
                        except OSError:
                            pass
                os.execve(staged[7], list(profile.argv), {})
            except BaseException:
                try:
                    os.write(status_write, b"F")
                except OSError:
                    pass
                os._exit(127)
        _close_registered_fd(status_write)
        status_write = None
        if old_mask is None:
            raise ValueError
        signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)
        old_mask = None
        remaining = deadline - time.monotonic()
        ready, _, _ = select.select((status_read,), (), (), max(0, remaining))
        status = os.read(status_read, 1) if ready else b"F"
        _close_registered_fd(status_read)
        status_read = None
        if status:
            raise ValueError
        observed = os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        if observed is not None and (observed.si_code != os.CLD_EXITED or observed.si_status != 0):
            raise ValueError
        _close_registered(staged)
        return AuthorityLinuxChild(
            pid,
            profile.authority_uid,
            deadline,
            _token=_CHILD_TOKEN,
        )
    except BaseException:
        if pid is not None:
            _terminate_reap(pid)
        raise AuthorityLinuxLaunchError() from None
    finally:
        if old_mask is not None:
            try:
                signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)
            except OSError:
                pass
        _close_registered_quietly(input_fds)
        _close_registered_quietly(staged)
        if status_read is not None:
            _close_quietly(status_read)
        if status_write is not None:
            _close_quietly(status_write)
        if descriptors is not None:
            try:
                descriptors.close()
            except OSError:
                pass


def _prepare_manager_child_reaping() -> None:
    """Keep direct-child wait ownership with the opaque child owner."""
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)


def _close_registered(fds: list[int]) -> None:
    for index, fd in enumerate(fds):
        if fd >= 0:
            os.close(fd)
            fds[index] = -1


def _close_registered_fd(fd: int) -> None:
    os.close(fd)


def _close_registered_quietly(fds: list[int]) -> None:
    for index, fd in enumerate(fds):
        if fd >= 0:
            _close_quietly(fd)
            fds[index] = -1


def _close_quietly(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


def _terminate_reap(pid: int) -> None:
    if not _owned_child(pid):
        return
    signalled = False
    try:
        os.killpg(pid, signal.SIGKILL)
        signalled = True
    except OSError:
        try:
            os.kill(pid, signal.SIGKILL)
            signalled = True
        except OSError:
            return
    if signalled:
        try:
            os.waitpid(pid, 0)
        except OSError:
            pass


def _owned_child(pid: int) -> bool:
    try:
        os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
    except ChildProcessError:
        return False
    except OSError:
        raise AuthorityLinuxLaunchError() from None
    return True


def _sealed_inputs(config_fd: int, key_fd: int, instance_fd: int) -> None:
    required = fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL
    identities = []
    for fd, minimum, maximum, exact in ((config_fd, 1, 65536, None), (key_fd, 32, 32, 32), (instance_fd, 1, 65536, None)):
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not minimum <= info.st_size <= maximum or exact is not None and info.st_size != exact or fcntl.fcntl(fd, fcntl.F_GET_SEALS) & required != required:
            raise ValueError
        identities.append((info.st_dev, info.st_ino))
    if len(set(identities)) != 3:
        raise ValueError

