"""Internal descriptor-cwd exec shim for platforms without fd path tokens."""

from __future__ import annotations

import os
import stat
import sys


def main() -> int:
    """Enter an inherited directory descriptor, then replace this process."""

    try:
        values = sys.argv[1:]
        if len(values) < 4 or values[0] != "--fd" or values[2] != "--":
            raise ValueError
        raw_descriptor = values[1]
        descriptor = int(raw_descriptor)
        if descriptor < 0 or str(descriptor) != raw_descriptor:
            raise ValueError
        command = values[3:]
        if not command or any(not item for item in command):
            raise ValueError
        details = os.fstat(descriptor)
        if not stat.S_ISDIR(details.st_mode):
            raise OSError
        os.fchdir(descriptor)
        os.close(descriptor)
        os.execvpe(command[0], command, dict(os.environ))
    except (AttributeError, NotImplementedError, OSError, TypeError, ValueError):
        return 126
    return 126


if __name__ == "__main__":
    raise SystemExit(main())
