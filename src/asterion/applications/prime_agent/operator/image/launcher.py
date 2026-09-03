#!/usr/local/bin/python
"""Closed launcher for the one image-owned Prime IPython fixture."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import NoReturn

from IPython.core.interactiveshell import InteractiveShell  # type: ignore[reportMissingImports]


WORKLOAD_DIGEST = "sha256:f4ebce1e8a4576db9235f6d8c67dffd9718931f64a07960e1d83b3809d3ce022"
RESULT = {"fixture": "passed", "oracle": "passed", "tool": "ipython"}
_SELF_CHECK = b'{"credentials_absent":true,"effective_capabilities":0,"effective_user_id":65534,"no_new_privileges":1,"nonloopback_network_absent":true,"root_read_only":true,"seccomp_mode":2,"workspace_only_writable":true}'
_STARTER = Path("/opt/prime-fixture/starter/solution.py")
_ORACLE = Path("/opt/prime-fixture/oracle/oracle.py")
_WORKSPACE_SOLUTION = Path("/workspace/solution.py")
_WRITABLE_KERNEL_MOUNTS = {"/dev", "/dev/mqueue", "/dev/pts", "/proc", "/sys"}
_CREDENTIAL_SENTINELS = (
    Path("/run/secrets"),
    Path("/root/.aws"),
    Path("/home/node/.aws"),
    Path("/home/node/.config/gcloud"),
    Path("/workspace/.env"),
)


def canonical(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def invalid_worker() -> NoReturn:
    raise RuntimeError("worker check failed")


def _parse_mounts() -> tuple[tuple[str, str, str, set[str]], ...]:
    try:
        mounts = []
        for line in Path("/proc/mounts").read_text(encoding="utf-8").splitlines():
            device, mount_point, kind, options, dump, pass_number = line.split(" ")
            if dump != "0" or pass_number != "0":
                invalid_worker()
            mounts.append((device, mount_point, kind, set(options.split(","))))
        return tuple(mounts)
    except (OSError, UnicodeError, ValueError):
        invalid_worker()


def _workspace_only_writable(mounts: tuple[tuple[str, str, str, set[str]], ...]) -> bool:
    root_read_only = False
    workspace_writable = False
    for device, mount_point, kind, options in mounts:
        if mount_point == "/":
            root_read_only = "ro" in options
        if mount_point == "/workspace":
            workspace_writable = (
                device == "tmpfs"
                and kind == "tmpfs"
                and {"rw", "nodev", "noexec", "nosuid"}.issubset(options)
            )
        if "rw" in options and mount_point != "/workspace" and mount_point not in _WRITABLE_KERNEL_MOUNTS:
            return False
    return root_read_only and workspace_writable


def require_closed_worker() -> None:
    try:
        status = Path("/proc/self/status").read_text(encoding="utf-8")
        devices = Path("/proc/net/dev").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        invalid_worker()
    expected = (
        "Uid:\t65534\t65534\t65534\t65534",
        "NoNewPrivs:\t1",
        "CapEff:\t0000000000000000",
        "Seccomp:\t2",
    )
    if (
        not all(value in status for value in expected)
        or not _workspace_only_writable(_parse_mounts())
        or any(path.exists() for path in _CREDENTIAL_SENTINELS)
        or any(
            ":" in line and not line.lstrip().startswith("lo:")
            for line in devices.splitlines()
        )
    ):
        invalid_worker()


def read_release() -> None:
    raw = sys.stdin.buffer.read(1025)
    if type(raw) is not bytes or len(raw) > 1024 or raw.count(b"\n") != 1 or not raw.endswith(b"\n"):
        invalid_worker()
    try:
        value = json.loads(raw[:-1].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        invalid_worker()
    if (
        type(value) is not dict
        or set(value) != {"release", "workload_digest"}
        or value["release"] is not True
        or value["workload_digest"] != WORKLOAD_DIGEST
        or canonical(value) != raw[:-1]
    ):
        invalid_worker()


def execute_fixture() -> None:
    try:
        fixture_source = _STARTER.read_text(encoding="utf-8")
        solution_source = fixture_source.replace("return 0", "return 42", 1)
        if solution_source == fixture_source:
            invalid_worker()
        _WORKSPACE_SOLUTION.write_text(solution_source, encoding="utf-8")
        sys.path.insert(0, "/workspace")
        shell = InteractiveShell.instance()
        shell.run_line_magic("run", str(_WORKSPACE_SOLUTION))
        shell.run_line_magic("run", str(_ORACLE))
    except (Exception, SystemExit):
        invalid_worker()


def emit_completion() -> None:
    result_bytes = canonical(RESULT)
    completion = {
        "result": RESULT,
        "result_digest": "sha256:" + hashlib.sha256(result_bytes).hexdigest(),
        "terminal": "completed",
        "workload_digest": WORKLOAD_DIGEST,
    }
    sys.stdout.buffer.write(canonical(completion) + b"\n")


def main() -> None:
    require_closed_worker()
    sys.stdout.buffer.write(_SELF_CHECK + b"\n")
    read_release()
    execute_fixture()
    emit_completion()


if __name__ == "__main__":
    main()
