"""Internal descriptor-cwd exec shim for platforms without fd path tokens."""

from __future__ import annotations

import os
import json
import signal
import stat
import sys
from pathlib import Path


def trusted_script_path() -> Path:
    """Return this installed helper as one absolute package-owned script."""

    path = Path(__file__).resolve(strict=True)
    if not path.is_file():
        raise OSError("trusted cwd helper is unavailable")
    return path


def main() -> int:
    """Enter an inherited directory descriptor, then replace this process."""

    try:
        values = sys.argv[1:]
        if (
            len(values) < 6
            or values[0] != "--fd"
            or values[2] != "--env-fd"
            or values[4] != "--"
        ):
            raise ValueError
        raw_descriptor = values[1]
        descriptor = int(raw_descriptor)
        if descriptor < 0 or str(descriptor) != raw_descriptor:
            raise ValueError
        raw_environment_descriptor = values[3]
        environment_descriptor = int(raw_environment_descriptor)
        if (
            environment_descriptor < 0
            or str(environment_descriptor) != raw_environment_descriptor
            or environment_descriptor == descriptor
        ):
            raise ValueError
        command = values[5:]
        if not command or any(not item for item in command):
            raise ValueError
        details = os.fstat(descriptor)
        if not stat.S_ISDIR(details.st_mode):
            raise OSError
        os.fchdir(descriptor)
        os.close(descriptor)
        environment = _read_environment(environment_descriptor)
        _restore_direct_spawn_signals()
        os.execvpe(command[0], command, environment)
    except (
        AttributeError,
        json.JSONDecodeError,
        NotImplementedError,
        OSError,
        TypeError,
        UnicodeError,
        ValueError,
    ):
        return 126
    return 126


def _read_environment(descriptor: int) -> dict[str, str]:
    payload = bytearray()
    try:
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            payload.extend(chunk)
            if len(payload) > 4 * 1024 * 1024:
                raise ValueError
    finally:
        os.close(descriptor)
    pairs = json.loads(payload.decode("ascii"))
    if (
        not isinstance(pairs, list)
        or any(
            not isinstance(pair, list)
            or len(pair) != 2
            or type(pair[0]) is not str
            or type(pair[1]) is not str
            for pair in pairs
        )
    ):
        raise ValueError
    environment: dict[str, str] = {}
    for key, value in pairs:
        if key in environment:
            raise ValueError
        environment[key] = value
    return environment


def _restore_direct_spawn_signals() -> None:
    for name in ("SIGPIPE", "SIGXFZ", "SIGXFSZ"):
        signum = getattr(signal, name, None)
        if signum is not None:
            signal.signal(signum, signal.SIG_DFL)


if __name__ == "__main__":
    raise SystemExit(main())
