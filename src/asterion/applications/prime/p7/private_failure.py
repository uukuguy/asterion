"""Operator-owned bounded Pi failure store; no public path or provider body."""

from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import threading
import stat

from asterion.services.diagnostics import (
    PRIVATE_FAILURE_EVENT_BYTES, PRIVATE_FAILURE_TOTAL_BYTES, PrivateFailureDiagnostic,
)


class P7PrivateFailureSink:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return "<P7PrivateFailureSink redacted>"

    def record(self, diagnostic: PrivateFailureDiagnostic) -> None:
        if type(diagnostic) is not PrivateFailureDiagnostic:
            raise TypeError("private failure diagnostic is invalid")
        with self._lock:
            descriptor = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
            try:
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise OSError("private failure destination is invalid")
                os.fchmod(descriptor, 0o600)
                remaining = PRIVATE_FAILURE_TOTAL_BYTES - os.fstat(descriptor).st_size
                limit = min(remaining, PRIVATE_FAILURE_EVENT_BYTES)
                retained = diagnostic.error_bytes.decode("utf-8", "ignore")
                while True:
                    record = {
                        "metadata": asdict(diagnostic.metadata),
                        "error_text": retained,
                        "observed_bytes": diagnostic.observed_bytes,
                        "retained_bytes": len(retained.encode("utf-8")),
                        "truncated": diagnostic.truncated or len(retained.encode("utf-8")) < diagnostic.retained_bytes,
                    }
                    encoded = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
                    if len(encoded) <= limit:
                        break
                    if not retained:
                        raise OSError("private failure destination is full")
                    retained = retained.encode("utf-8")[:max(0, len(retained.encode("utf-8")) - (len(encoded) - limit))].decode("utf-8", "ignore")
                # A regular append is one bounded record; partial writes are a sink failure.
                if os.write(descriptor, encoded) != len(encoded):
                    raise OSError("private failure write was incomplete")
            finally:
                os.close(descriptor)
