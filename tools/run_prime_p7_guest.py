#!/usr/bin/env python3
"""Keep one Orb P7 attempt and every descendant in its own systemd cgroup."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

_UNIT = re.compile(r"^asterion-p7-[0-9a-f]{32}\.service$")
_ENVIRONMENT_FILE = Path(__file__).with_name("p7_guest_environment.txt")
_UNBOUNDED_FIRST_ROUND_ENV = "ASTERION_PRIME_P7_UNBOUNDED_FIRST_ROUND"
# Guest-only: Orb has already translated host loopback proxy addresses. Keep
# these out of the shared ORBENV contract so that translation remains owned by Orb.
_GUEST_PROXY_ENVIRONMENT = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "no_proxy",
)


def _environment_names() -> tuple[str, ...]:
    """Read the single non-sensitive guest environment contract."""

    try:
        names = tuple(
            line.strip()
            for line in _ENVIRONMENT_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    except (OSError, UnicodeError):
        raise ValueError("guest environment contract unavailable") from None
    if not names or len(names) != len(set(names)) or any(
        not re.fullmatch(r"[A-Z][A-Z0-9_]+", name) for name in names
    ):
        raise ValueError("guest environment contract invalid")
    return names


def _unit(value: str) -> str:
    if not _UNIT.fullmatch(value):
        raise ValueError("invalid attempt identity")
    return value


def launch(unit: str, seconds: float | None, command: list[str]) -> int:
    _unit(unit)
    console_id = os.environ.get("ASTERION_PRIME_P7_CONSOLE_RUN_ID")
    mode = os.environ.get("ASTERION_PRIME_P7_RUN_MODE")
    if console_id is not None or mode == "witness":
        if (
            mode != "witness"
            or console_id is None
            or re.fullmatch(r"p7-live-[0-9]{14}-[0-9a-f]{24}", console_id) is None
            or seconds != 900
            or os.environ.get("ASTERION_PRIME_P7_ATTEMPT_UNIT") != unit
            or os.environ.get("ASTERION_PRIME_P7_ATTEMPT_SECONDS") != "900"
            or _UNBOUNDED_FIRST_ROUND_ENV in os.environ
        ):
            raise ValueError("invalid console attempt")
    # The host-only sweep driver uses zero as an explicit wire sentinel for
    # its separately authorized unbounded first-round campaign.
    if type(seconds) not in (int, float) or isinstance(seconds, bool):
        raise ValueError("invalid attempt bounds")
    if seconds == 0:
        seconds = None
    if (seconds is not None and (not math.isfinite(seconds) or not 0 < seconds <= 4 * 60 * 60)) or not command:
        raise ValueError("invalid attempt bounds")
    if not Path("/sys/fs/cgroup/cgroup.controllers").is_file():
        raise ValueError("guest cgroup unavailable")
    # The fixed witness still cancels the entire solve at 900 seconds. Its
    # existing replay/seal/summary cleanup may outlast the generic 20s stop
    # grace, especially after restoring several completed levels. This is
    # cleanup time, not another model/gameplay interval or a caller knob.
    stop_seconds = 180 if mode == "witness" else 20
    args = [
        "systemd-run", "--quiet", "--wait", "--pipe", "--collect",
        "--service-type=exec", f"--unit={unit}",
        "--property=KillMode=control-group", f"--property=TimeoutStopSec={stop_seconds}s",
        "--property=SendSIGKILL=yes",
        "--property=WorkingDirectory=/tmp",
    ]
    if seconds is not None:
        args.append(f"--property=RuntimeMaxSec={seconds}s")
    if mode == "witness":
        # Both launcher and operator run in the Linux guest clock domain. Never
        # forward a caller/host timestamp through the shared environment list.
        args.append(f"--setenv=ASTERION_PRIME_P7_ATTEMPT_STARTED_MONOTONIC={time.monotonic()}")
    for name in _environment_names():
        value = os.environ.get(name)
        if value is None:
            continue
        if name in {_UNBOUNDED_FIRST_ROUND_ENV, "OPERATION_MODE"} and os.environ.get(_UNBOUNDED_FIRST_ROUND_ENV) != "1":
            continue
        args.append(f"--setenv={name}={value}")
    for name in _GUEST_PROXY_ENVIRONMENT:
        if name in os.environ:
            # NAME-only copies systemd-run's inherited guest value without
            # placing optional proxy credentials in the command arguments.
            args.append(f"--setenv={name}")
    # Model credentials remain operator-owned and are resolved from its .env/profile.
    # Replace the Orb-managed process: no launcher child can outlive a killed
    # Orb session and submit a new service after cleanup has checked absence.
    os.execvp(args[0], [*args, "--", *command])
    return 1  # exec failure raises; retained for static return typing.


def witness(command: list[str]) -> int:
    """The standard CLI preset owns its identity and fixed finite allowance."""
    if os.environ.get("ASTERION_PRIME_P7_RUN_MODE") != "witness":
        raise ValueError("invalid witness preset")
    fields = ("ASTERION_PRIME_P7_ATTEMPT_UNIT", "ASTERION_PRIME_P7_ATTEMPT_SECONDS",
              "ASTERION_PRIME_P7_CONSOLE_RUN_ID")
    if not any(name in os.environ for name in fields):
        os.environ[fields[0]] = f"asterion-p7-{uuid.uuid4().hex}.service"
        os.environ[fields[1]] = "900"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        os.environ[fields[2]] = f"p7-live-{stamp}-{uuid.uuid4().hex[:24]}"
    return launch(os.environ.get(fields[0], ""), 900, command)


def cleanup(unit: str) -> bool:
    _unit(unit)
    stopped = subprocess.run(
        ["systemctl", "stop", unit], stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, timeout=190, check=False,
    )
    state = subprocess.run(
        ["systemctl", "show", unit, "--property=LoadState,ActiveState,ControlGroup"],
        capture_output=True, text=True, timeout=5, check=False,
    )
    values = dict(line.split("=", 1) for line in state.stdout.splitlines() if "=" in line)
    # Missing units are expected when --collect unloads a stopped service.
    if values.get("LoadState") == "not-found":
        pass
    elif stopped.returncode != 0 or values.get("ActiveState") not in {"inactive", "failed"}:
        return False
    cgroup = values.get("ControlGroup")
    expected = Path("/sys/fs/cgroup/system.slice") / unit
    if cgroup and cgroup != f"/system.slice/{unit}":
        return False
    if expected.exists():
        events = dict(line.split() for line in (expected / "cgroup.events").read_text().splitlines())
        if events.get("populated") != "0":
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("launch", "cleanup", "witness"))
    parser.add_argument("--unit")
    parser.add_argument("--seconds", type=float)
    argv = sys.argv[1:]
    split = argv.index("--") if "--" in argv else len(argv)
    args = parser.parse_args(argv[:split])
    command = argv[split + 1:]
    try:
        if args.mode == "witness":
            if args.unit is not None or args.seconds is not None:
                raise ValueError("invalid witness preset")
            return witness(command)
        if args.unit is None:
            raise ValueError("missing attempt identity")
        if args.mode == "cleanup":
            return 0 if cleanup(args.unit) else 1
        return launch(args.unit, args.seconds, command)
    except Exception:
        print("P7 guest containment unavailable", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
