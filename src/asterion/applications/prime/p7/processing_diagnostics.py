"""Safe, persistent-status projections for application processing failures.

This module accepts diagnostic fields, never exceptions or private error text.
It does not authorize execution, recover a game, or own animation storage.
"""

from datetime import datetime, timezone
import re
import json
from pathlib import Path
from threading import RLock

_FIELDS = frozenset({
    "diagnostic_id", "code", "severity", "stage", "action_sequence",
    "outcome_known", "durable", "observed", "limit", "unit", "recovery",
})
_AGGREGATE = frozenset({"first_seen", "last_seen", "count", "status", "recovered_at"})
_STAGES = frozenset({
    "not-dispatched", "dispatched-no-reply", "reply-received-invalid",
    "validated-not-durable", "durably-committed", "derived-failed",
    "reply-received-unvalidated",
})
PROCESSING_CODES = frozenset({
    "evidence-write-failed", "evidence-read-failed", "evidence-hash-failed", "observation-validation-failed",
    "derived-projection-failed", "console-publication-failed", "research-read-failed",
    "research-response-budget-exceeded", "engine-no-reply", "engine-response-invalid", "action-not-dispatched",
    "evidence-cancelled", "evidence-deadline-exceeded",
})
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,159}\Z")
_RECOVERY = frozenset({
    "pause-and-rebuild", "read-only-rebuild", "stop-without-redispatch",
    "fix-request", "retry-read", "operator-recovery", "none",
})


def _timestamp(value=None):
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if type(value) is not str or len(value) > 64:
        raise ValueError("processing diagnostic unavailable")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("processing diagnostic unavailable") from None
    if parsed.tzinfo is None:
        raise ValueError("processing diagnostic unavailable")
    return value


def public_diagnostic(value):
    """Validate a closed public warning without copying private exception text."""
    if type(value) is not dict or not _FIELDS <= value.keys() or value.keys() - (_FIELDS | _AGGREGATE):
        raise ValueError("processing diagnostic unavailable")
    if (type(value["diagnostic_id"]) is not str or not _ID.fullmatch(value["diagnostic_id"])
            or type(value["code"]) is not str or value["code"] not in PROCESSING_CODES
            or type(value["severity"]) is not str or value["severity"] not in {"info", "warning", "error"}
            or type(value["stage"]) is not str or value["stage"] not in _STAGES
            or type(value["recovery"]) is not str or value["recovery"] not in _RECOVERY
            or type(value["action_sequence"]) is not int or value["action_sequence"] < 0
            or type(value["outcome_known"]) is not bool or type(value["durable"]) is not bool
            or (value["unit"] is not None and (type(value["unit"]) is not str
                or value["unit"] not in {"bytes", "cells", "frames", "rows", "events"}))):
        raise ValueError("processing diagnostic unavailable")
    for key in ("observed", "limit"):
        if value[key] is not None and (type(value[key]) is not int or value[key] < 0):
            raise ValueError("processing diagnostic unavailable")
    if value["durable"] and not value["outcome_known"]:
        raise ValueError("processing diagnostic unavailable")
    aggregate = value.keys() & _AGGREGATE
    if aggregate:
        if aggregate != _AGGREGATE:
            raise ValueError("processing diagnostic unavailable")
        _timestamp(value["first_seen"])
        _timestamp(value["last_seen"])
        if (type(value["count"]) is not int or value["count"] < 1
                or type(value["status"]) is not str or value["status"] not in {"active", "recovered"}
                or (value["status"] == "active") != (value["recovered_at"] is None)):
            raise ValueError("processing diagnostic unavailable")
        if value["recovered_at"] is not None:
            _timestamp(value["recovered_at"])
    return dict(value)


class DiagnosticLog:
    """Merge repeated failures while keeping resolved diagnostic history."""

    def __init__(self, path: Path | None = None):
        self._records = {}
        self._lock = RLock()
        self._path = path.parent.resolve() / path.name if path is not None else None

    def _persist(self):
        if self._path is None:
            return
        from .run_story.storage import write_atomic_file
        try:
            if any(part.is_symlink() for part in (self._path, *self._path.parents)):
                raise OSError
            self._path.parent.mkdir(parents=True, exist_ok=True)
            write_atomic_file(self._path, json.dumps(self.projection(), ensure_ascii=True,
                                                    separators=(',', ':')).encode())
        except OSError:
            # Preserve the original warning in memory/summary when its own
            # derivative file cannot be written. Do not recurse through the sink.
            sequence = max((value['action_sequence'] for value in self._records.values()), default=0)
            value = dict(diagnostic_id=f'evidence-write-failed:derived-failed:{sequence}',
                         code='evidence-write-failed', severity='warning', stage='derived-failed',
                         action_sequence=sequence, outcome_known=True, durable=False,
                         observed=None, limit=None, unit=None, recovery='read-only-rebuild')
            previous = self._records.get(value['diagnostic_id'])
            now = _timestamp()
            value.update(first_seen=previous['first_seen'] if previous else now, last_seen=now,
                         count=previous['count'] + 1 if previous else 1, status='active', recovered_at=None)
            self._records[value['diagnostic_id']] = value

    def record(self, diagnostic, *, timestamp=None):
        value = public_diagnostic(diagnostic)
        value = {key: value[key] for key in _FIELDS}
        timestamp = _timestamp(timestamp)
        with self._lock:
            previous = self._records.get(value["diagnostic_id"])
            if previous is not None:
                # One identity describes one fault. A changed stage/code gets
                # its own identity instead of rewriting historical evidence.
                if any(previous[key] != value[key] for key in ("code", "stage", "action_sequence")):
                    raise ValueError("processing diagnostic identity changed")
            value.update(
                first_seen=previous["first_seen"] if previous else timestamp,
                last_seen=timestamp, count=previous["count"] + 1 if previous else 1,
                status="active", recovered_at=None,
            )
            self._records[value["diagnostic_id"]] = value
            self._persist()
            return dict(value)

    def resolve(self, diagnostic_id, *, timestamp=None):
        timestamp = _timestamp(timestamp)
        with self._lock:
            record = self._records[diagnostic_id]
            record.update(status="recovered", recovered_at=timestamp)
            self._persist()
            return dict(record)

    def projection(self):
        with self._lock:
            return [dict(record) for record in self._records.values()]
