#!/usr/local/bin/python
"""Closed duplex launcher for the image-owned Prime IPython workload.

Only the host can advance this process. The worker requests one model turn,
accepts one canonical model response naming ``ipython``, and executes that
cell. Prompt and cell bodies stay on this private attach stream.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import NoReturn

from IPython.core.interactiveshell import InteractiveShell  # type: ignore[reportMissingImports]


WORKLOAD_DIGEST = "sha256:f4ebce1e8a4576db9235f6d8c67dffd9718931f64a07960e1d83b3809d3ce022"
PRIME_SDK_SESSION_PIN = "prime-agent@0.7.1"
_FRAME_LIMIT = 65536
_SELF_CHECK = b'{"credentials_absent":true,"effective_capabilities":0,"effective_user_id":65534,"no_new_privileges":1,"nonloopback_network_absent":true,"root_read_only":true,"seccomp_mode":2,"workspace_only_writable":true}'
_STARTER = Path("/opt/prime-fixture/starter/solution.py")
_ORACLE = Path("/opt/prime-fixture/oracle/oracle.py")
_WORKSPACE_SOLUTION = Path("/workspace/solution.py")
_WRITABLE_KERNEL_MOUNTS = {"/dev", "/dev/mqueue", "/dev/pts", "/proc", "/sys"}
_CREDENTIAL_SENTINELS = (Path("/run/secrets"), Path("/root/.aws"), Path("/home/node/.aws"), Path("/home/node/.config/gcloud"), Path("/workspace/.env"))


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
            workspace_writable = device == "tmpfs" and kind == "tmpfs" and {"rw", "nodev", "noexec", "nosuid"}.issubset(options)
        if "rw" in options and mount_point != "/workspace" and mount_point not in _WRITABLE_KERNEL_MOUNTS:
            return False
    return root_read_only and workspace_writable


def require_closed_worker() -> None:
    try:
        status = Path("/proc/self/status").read_text(encoding="utf-8")
        devices = Path("/proc/net/dev").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        invalid_worker()
    expected = ("Uid:\t65534\t65534\t65534\t65534", "NoNewPrivs:\t1", "CapEff:\t0000000000000000", "Seccomp:\t2")
    if not all(value in status for value in expected) or not _workspace_only_writable(_parse_mounts()) or any(path.exists() for path in _CREDENTIAL_SENTINELS) or any(":" in line and not line.lstrip().startswith("lo:") for line in devices.splitlines()):
        invalid_worker()


def _read_frame() -> dict[str, object]:
    raw = sys.stdin.buffer.readline(_FRAME_LIMIT + 1)
    if type(raw) is not bytes or not raw or len(raw) > _FRAME_LIMIT or raw.count(b"\n") != 1 or not raw.endswith(b"\n"):
        invalid_worker()
    try:
        value = json.loads(raw[:-1].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        invalid_worker()
    if type(value) is not dict or canonical(value) != raw[:-1]:
        invalid_worker()
    return value


def _emit_frame(value: dict[str, object]) -> None:
    raw = canonical(value)
    if len(raw) > _FRAME_LIMIT:
        invalid_worker()
    sys.stdout.buffer.write(raw + b"\n")
    sys.stdout.buffer.flush()


def read_control() -> None:
    value = _read_frame()
    if value.get("workload_digest") != WORKLOAD_DIGEST:
        invalid_worker()
    if set(value) != {"control", "prime_sdk_session", "workload_digest"} or value["control"] != "begin" or value["prime_sdk_session"] != PRIME_SDK_SESSION_PIN:
        invalid_worker()


def emit_model_request() -> None:
    _emit_frame({"kind": "model-request", "prime_sdk_session": PRIME_SDK_SESSION_PIN, "tools": ["ipython"], "workload_digest": WORKLOAD_DIGEST})


def read_model_response() -> str:
    value = _read_frame()
    if value.get("workload_digest") != WORKLOAD_DIGEST:
        invalid_worker()
    if set(value) != {"cell", "kind", "tool", "workload_digest"} or value["kind"] != "model-response" or value["tool"] != "ipython" or type(value["cell"]) is not str or not value["cell"]:
        invalid_worker()
    return value["cell"]


def _run_oracle(shell: InteractiveShell) -> bool:
    sys.modules.pop("solution", None)
    try:
        shell.run_line_magic("run", str(_ORACLE))
    except (AssertionError, Exception, SystemExit):
        return False
    return True


def initial_oracle_failure(shell: InteractiveShell) -> None:
    try:
        _WORKSPACE_SOLUTION.write_bytes(_STARTER.read_bytes())
    except OSError:
        invalid_worker()
    sys.path.insert(0, "/workspace")
    if _run_oracle(shell):
        invalid_worker()


def execute_model_ipython_cell(shell: InteractiveShell, cell: str) -> None:
    before = hashlib.sha256(_WORKSPACE_SOLUTION.read_bytes()).digest()
    result = shell.run_cell(cell, store_history=False)
    if result.error_in_exec is not None or result.error_before_exec is not None:
        invalid_worker()
    try:
        after = hashlib.sha256(_WORKSPACE_SOLUTION.read_bytes()).digest()
    except OSError:
        invalid_worker()
    if before == after:
        invalid_worker()


def final_oracle_success(shell: InteractiveShell) -> None:
    if not _run_oracle(shell):
        invalid_worker()


def emit_completion() -> None:
    result = {"fixture": "passed", "oracle": "passed", "tool": "ipython"}
    result_bytes = canonical(result)
    _emit_frame({"host_model_operations": 1, "model_caused_ipython_mutation": True, "oracle_eventually_passed": True, "oracle_initially_failed": True, "result": result, "result_digest": "sha256:" + hashlib.sha256(result_bytes).hexdigest(), "terminal": "completed", "tools": ["ipython"], "workload_digest": WORKLOAD_DIGEST})


def main() -> None:
    require_closed_worker()
    sys.stdout.buffer.write(_SELF_CHECK + b"\n")
    sys.stdout.buffer.flush()
    read_control()
    shell = InteractiveShell.instance()
    initial_oracle_failure(shell)
    emit_model_request()
    cell = read_model_response()
    execute_model_ipython_cell(shell, cell)
    final_oracle_success(shell)
    emit_completion()


if __name__ == "__main__":
    main()
