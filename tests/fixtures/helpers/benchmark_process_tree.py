"""Synthetic process tree used by benchmark cancellation tests."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    pid_file = Path(sys.argv[1])
    grandchild = subprocess.Popen(
        (
            sys.executable,
            "-c",
            (
                "import signal,time;"
                "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                "time.sleep(60)"
            ),
        )
    )
    pid_file.write_text(
        f"{os.getpid()}\n{grandchild.pid}\n",
        encoding="utf-8",
    )
    while True:
        time.sleep(1)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    raise SystemExit(main())
