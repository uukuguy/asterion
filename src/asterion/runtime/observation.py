"""Durable, public-safe lifecycle observations for long-running runs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import MappingProxyType
from collections.abc import Mapping


class RunObservationError(ValueError):
    """Raised when an observation would violate the public log boundary."""


_PAYLOADS = {
    "run.started": frozenset(),
    "run.phase": frozenset({"phase"}),
    "run.terminal": frozenset({"status", "reason"}),
}
_TERMINAL = frozenset({"completed", "failed", "cancelled", "external-limited"})


class RunObservationLog:
    """Append-only JSONL events plus one atomically replaced public snapshot."""

    def __init__(self, root: Path, run_id: str) -> None:
        if not isinstance(root, Path) or not isinstance(run_id, str) or not run_id:
            raise RunObservationError("run observation is invalid")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not root.is_dir() or root.is_symlink():
            raise RunObservationError("run observation is invalid")
        self._root, self._run_id, self._sequence = root, run_id, 0
        self._events = root / f"{run_id}.events.jsonl"
        self._status = root / f"{run_id}.status.json"

    def record(self, event_type: str, payload: Mapping[str, str] | None = None) -> Mapping[str, object]:
        payload = {} if payload is None else dict(payload)
        allowed = _PAYLOADS.get(event_type)
        if allowed is None or set(payload) != allowed or any(not isinstance(v, str) or not v for v in payload.values()):
            raise RunObservationError("run observation is unsafe")
        self._sequence += 1
        event = {"run_id": self._run_id, "sequence": self._sequence, "type": event_type, "payload": payload}
        with self._events.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
        return MappingProxyType(event)

    def terminal(self, status: str, reason: str) -> Mapping[str, object]:
        if status not in _TERMINAL or not isinstance(reason, str) or not reason:
            raise RunObservationError("run terminal is invalid")
        self.record("run.terminal", {"status": status, "reason": reason})
        snapshot = {"run_id": self._run_id, "status": status, "reason": reason, "last_sequence": self._sequence}
        temporary = self._status.with_name(f".{self._status.name}.tmp")
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(snapshot, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self._status)
        return MappingProxyType(snapshot)
