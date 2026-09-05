"""Exact privilege transition for the private, manager-forked Linux authority."""

from __future__ import annotations

import ctypes
from dataclasses import InitVar, dataclass
import os
import resource
import signal
import sys
from typing import NoReturn


class AuthorityLinuxPolicyError(ValueError):
    def __init__(self) -> None:
        super().__init__("prime authority launch is unavailable")


_POLICY_TOKEN = object()


@dataclass(frozen=True, slots=True, repr=False)
class LinuxIdentityPolicy:
    cap_last_cap: int
    reset_signals: tuple[int, ...]
    prepare_pid: int
    _libc: ctypes.CDLL
    token: InitVar[object]

    def __post_init__(self, token: object) -> None:
        if type(self) is not LinuxIdentityPolicy or token is not _POLICY_TOKEN:
            raise AuthorityLinuxPolicyError()

    def __repr__(self) -> str:
        return "LinuxIdentityPolicy(redacted)"

    def __reduce__(self) -> NoReturn:
        raise TypeError("prime authority launch is unavailable")

    def __copy__(self) -> NoReturn:
        raise TypeError("prime authority launch is unavailable")

    def __deepcopy__(self, _: object) -> NoReturn:
        raise TypeError("prime authority launch is unavailable")


class _CapabilityHeader(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]


class _CapabilityData(ctypes.Structure):
    _fields_ = [
        ("effective", ctypes.c_uint32),
        ("permitted", ctypes.c_uint32),
        ("inheritable", ctypes.c_uint32),
    ]


def prepare_linux_identity_policy() -> LinuxIdentityPolicy:
    """Load all syscall bindings and freeze the kernel capability range before fork."""
    try:
        if sys.platform != "linux" or os.geteuid() != 0:
            raise ValueError
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl.argtypes = [ctypes.c_int] + [ctypes.c_ulong] * 4
        libc.prctl.restype = ctypes.c_int
        libc.capset.argtypes = [
            ctypes.POINTER(_CapabilityHeader), ctypes.POINTER(_CapabilityData),
        ]
        libc.capset.restype = ctypes.c_int
        with open("/proc/sys/kernel/cap_last_cap", encoding="ascii") as source:
            raw = source.read(32)
        if not raw.endswith("\n") or not raw[:-1].isascii() or not raw[:-1].isdecimal():
            raise ValueError
        last = int(raw)
        if not 0 <= last <= 63:
            raise ValueError
        reset_signals = tuple(sorted(
            int(number) for number in signal.valid_signals()
            if number not in (signal.SIGKILL, signal.SIGSTOP)
            and signal.getsignal(number) != signal.SIG_DFL
        ))
        return LinuxIdentityPolicy(last, reset_signals, os.getpid(), libc, _POLICY_TOKEN)
    except Exception:
        raise AuthorityLinuxPolicyError() from None


def _prctl(prepared: LinuxIdentityPolicy, option: int, arg2: int = 0, arg3: int = 0) -> int:
    result = prepared._libc.prctl(option, arg2, arg3, 0, 0)
    if result < 0:
        raise ValueError
    return int(result)


def _identities(uid: int, gid: int, parent: int) -> None:
    if (
        sys.platform != "linux"
        or any(type(value) is not int for value in (uid, gid, parent))
        or not 1 <= uid <= 4294967294
        or not 1 <= gid <= 4294967294
        or not 1 <= parent <= 2147483647
        or os.getppid() != parent
    ):
        raise ValueError


def _snapshot(prepared: LinuxIdentityPolicy, parent: int) -> None:
    if (
        type(prepared) is not LinuxIdentityPolicy
        or type(prepared.prepare_pid) is not int
        or prepared.prepare_pid != parent
        or type(prepared.cap_last_cap) is not int
        or not 0 <= prepared.cap_last_cap <= 63
        or type(prepared.reset_signals) is not tuple
        or any(type(number) is not int for number in prepared.reset_signals)
        or tuple(sorted(set(prepared.reset_signals))) != prepared.reset_signals
        or not isinstance(prepared._libc, ctypes.CDLL)
    ):
        raise ValueError


def apply_linux_identity_policy(
    prepared: LinuxIdentityPolicy,
    *,
    authority_uid: int,
    authority_gid: int,
    expected_parent_pid: int,
) -> None:
    """Permanently drop the forked child; callers must exit on any rejection."""
    try:
        _identities(authority_uid, authority_gid, expected_parent_pid)
        _snapshot(prepared, expected_parent_pid)
        if os.geteuid() != 0:
            raise ValueError
        _prctl(prepared, 1, int(signal.SIGKILL))  # PR_SET_PDEATHSIG
        _identities(authority_uid, authority_gid, expected_parent_pid)
        current = tuple(sorted(
            int(number) for number in signal.valid_signals()
            if number not in (signal.SIGKILL, signal.SIGSTOP)
            and signal.getsignal(number) != signal.SIG_DFL
        ))
        if current != prepared.reset_signals:
            raise ValueError
        for number in prepared.reset_signals:
            signal.signal(number, signal.SIG_DFL)
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        for capability in range(prepared.cap_last_cap + 1):
            _prctl(prepared, 24, capability)  # PR_CAPBSET_DROP
        _prctl(prepared, 47, 4)  # PR_CAP_AMBIENT, PR_CAP_AMBIENT_CLEAR_ALL
        os.setgroups([])
        os.setresgid(authority_gid, authority_gid, authority_gid)
        os.setresuid(authority_uid, authority_uid, authority_uid)
        header = _CapabilityHeader(0x20080522, 0)  # _LINUX_CAPABILITY_VERSION_3
        data = (_CapabilityData * 2)()
        if prepared._libc.capset(ctypes.byref(header), data) != 0:
            raise ValueError
        _prctl(prepared, 38, 1)  # PR_SET_NO_NEW_PRIVS
        _prctl(prepared, 4, 0)  # PR_SET_DUMPABLE
        _prctl(prepared, 1, int(signal.SIGKILL))  # credential changes clear PDEATHSIG
        signal.pthread_sigmask(signal.SIG_SETMASK, ())
        verify_linux_identity_policy(
            prepared,
            authority_uid=authority_uid, authority_gid=authority_gid,
            expected_parent_pid=expected_parent_pid,
        )
    except Exception:
        raise AuthorityLinuxPolicyError() from None


def verify_linux_identity_policy(
    prepared: LinuxIdentityPolicy,
    *, authority_uid: int, authority_gid: int, expected_parent_pid: int,
) -> None:
    """Verify the kernel's actual state, rather than inferring setuid side effects."""
    try:
        _identities(authority_uid, authority_gid, expected_parent_pid)
        _snapshot(prepared, expected_parent_pid)
        death_signal = ctypes.c_int()
        _prctl(prepared, 2, ctypes.addressof(death_signal))  # PR_GET_PDEATHSIG
        if (
            death_signal.value != signal.SIGKILL
            or _prctl(prepared, 3) != 0  # PR_GET_DUMPABLE
            or _prctl(prepared, 39) != 1  # PR_GET_NO_NEW_PRIVS
            or os.getresuid() != (authority_uid,) * 3
            or os.getresgid() != (authority_gid,) * 3
            or os.getgroups()
            or resource.getrlimit(resource.RLIMIT_CORE) != (0, 0)
            or signal.pthread_sigmask(signal.SIG_BLOCK, ())
            or any(signal.getsignal(number) != signal.SIG_DFL for number in prepared.reset_signals)
        ):
            raise ValueError
        with open("/proc/self/status", encoding="ascii") as source:
            values = dict(line.split(":", 1) for line in source if ":" in line)
        if (
            values.get("Uid", "").split() != [str(authority_uid)] * 4
            or values.get("Gid", "").split() != [str(authority_gid)] * 4
            or values.get("Groups", "").split()
            or values.get("NoNewPrivs", "").strip() != "1"
            or any(values.get(key, "").strip() != "0000000000000000" for key in (
                "CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb",
            ))
        ):
            raise ValueError
    except Exception:
        raise AuthorityLinuxPolicyError() from None
