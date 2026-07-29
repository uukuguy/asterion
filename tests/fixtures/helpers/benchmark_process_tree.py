from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    state_path = Path(sys.argv[1])
    state_path.parent.mkdir(parents=True, exist_ok=True)

    child_pid = os.getpid()
    grandchild = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import signal, time; "
                "signal.signal(signal.SIGTERM, lambda *_: None); "
                "time.sleep(60)"
            ),
        ],
        env={},
    )
    state_path.write_text(
        json.dumps(
            {
                "child_pid": child_pid,
                "grandchild_pid": grandchild.pid,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    signal.signal(signal.SIGTERM, lambda *_: None)
    try:
        grandchild.wait()
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
