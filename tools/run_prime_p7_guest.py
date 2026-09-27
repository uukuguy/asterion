#!/usr/bin/env python3
"""Keep one Orb P7 attempt and every descendant in its own systemd cgroup."""
from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import re
import subprocess
import sys

_UNIT = re.compile(r"^asterion-p7-[0-9a-f]{32}\.service$")
_ENVIRONMENT = (
    "ASTERION_PRIME_OPERATOR_ROOT", "ASTERION_PRIME_ARC_ROOT",
    "ASTERION_PRIME_PI_ENTRY", "ASTERION_PRIME_NODE",
    "ASTERION_PRIME_PI_AGENT_DIR",
    "ASTERION_PRIME_P7_GAME_ID", "ASTERION_PRIME_P7_SEED",
    "ASTERION_PRIME_P7_RUN_MODE", "ASTERION_PRIME_P7_TARGET_LEVEL",
    "ASTERION_PRIME_P7_HISTORY_VARIANT",
    "ASTERION_PRIME_P7_RETRY_MODE",
    "ASTERION_PRIME_P7_UNBOUNDED_FIRST_ROUND", "OPERATION_MODE",
)
_UNBOUNDED_FIRST_ROUND_ENV = "ASTERION_PRIME_P7_UNBOUNDED_FIRST_ROUND"


def _unit(value: str) -> str:
    if not _UNIT.fullmatch(value):
        raise ValueError("invalid attempt identity")
    return value


def launch(unit: str, seconds: float | None, command: list[str]) -> int:
    _unit(unit)
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
    args = [
        "systemd-run", "--quiet", "--wait", "--pipe", "--collect",
        "--service-type=exec", f"--unit={unit}",
        "--property=KillMode=control-group", "--property=TimeoutStopSec=5s",
        "--property=SendSIGKILL=yes",
        "--property=WorkingDirectory=/tmp",
    ]
    if seconds is not None:
        args.append(f"--property=RuntimeMaxSec={seconds}s")
    for name in _ENVIRONMENT:
        value = os.environ.get(name)
        if value is None:
            continue
        if name in {_UNBOUNDED_FIRST_ROUND_ENV, "OPERATION_MODE"} and os.environ.get(_UNBOUNDED_FIRST_ROUND_ENV) != "1":
            continue
        args.append(f"--setenv={name}={value}")
    # systemd-run owns no private provider settings; the operator reads its .env.
    # Replace the Orb-managed process: no launcher child can outlive a killed
    # Orb session and submit a new service after cleanup has checked absence.
    os.execvp(args[0], [*args, "--", *command])
    return 1  # exec failure raises; retained for static return typing.


def cleanup(unit: str) -> bool:
    _unit(unit)
    stopped = subprocess.run(
        ["systemctl", "stop", unit], stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, timeout=12, check=False,
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
    parser.add_argument("mode", choices=("launch", "cleanup"))
    parser.add_argument("--unit", required=True)
    parser.add_argument("--seconds", type=float)
    argv = sys.argv[1:]
    split = argv.index("--") if "--" in argv else len(argv)
    args = parser.parse_args(argv[:split])
    command = argv[split + 1:]
    try:
        if args.mode == "cleanup":
            return 0 if cleanup(args.unit) else 1
        return launch(args.unit, args.seconds, command)
    except Exception:
        print("P7 guest containment unavailable", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
