"""Private canonical frame reducer for the sealed Prime P2 launcher.

This module consumes worker-emitted bytes only.  It deliberately exposes no
operation that accepts a program, prompt, source, command, path, or provider
configuration.
"""

from __future__ import annotations

import json
import re
import time
from typing import Callable, Final

from .programmatic_long_context_workload import (
    PROGRAMMATIC_LONG_CONTEXT_P2_ROLE_ID,
    PROGRAMMATIC_LONG_CONTEXT_P2_SCENARIO_ID,
    PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST,
)


PROGRAMMATIC_LONG_CONTEXT_MAX_FRAME_BYTES: Final = 4096
_DEADLINE_SECONDS: Final = 1.0
_DIGEST: Final = re.compile(r"sha256:[0-9a-f]{64}")
_SELF_CHECK: Final = {
    "credentials_absent": True,
    "effective_capabilities": 0,
    "effective_user_id": 65534,
    "no_new_privileges": 1,
    "nonloopback_network_absent": True,
    "root_read_only": True,
    "seccomp_mode": 2,
    "workspace_only_writable": True,
}
_KINDS: Final = (
    "self-check",
    "release",
    "model-response",
    "ipython",
    "oracle",
    "session-disposed",
    "completed",
)


class ProgrammaticLongContextReleaseError(ValueError):
    """Raised without exposing a private worker frame."""


def _invalid() -> ProgrammaticLongContextReleaseError:
    return ProgrammaticLongContextReleaseError("programmatic long-context release is invalid")


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_programmatic_long_context_frame(
    *, worker_id: str, run_id: str, challenge_digest: str, workload_digest: str,
    sequence: int, kind: str, payload: dict[str, object],
) -> bytes:
    """Construct canonical private test/transport bytes for the one P2 protocol."""
    value = {
        "challenge_digest": challenge_digest,
        "kind": kind,
        "payload": payload,
        "run_id": run_id,
        "sequence": sequence,
        "worker_id": worker_id,
        "workload_digest": workload_digest,
    }
    if (
        type(worker_id) is not str or not worker_id or type(run_id) is not str or not run_id
        or type(challenge_digest) is not str or _DIGEST.fullmatch(challenge_digest) is None
        or workload_digest != PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST
        or type(sequence) is not int or sequence < 0 or type(kind) is not str or kind not in _KINDS
        or type(payload) is not dict
    ):
        raise _invalid()
    return _canonical(value)


class ProgrammaticLongContextRelease:
    """One-use reducer for the fixed P2 launcher sequence."""

    def __init__(
        self, worker_id: str, run_id: str, challenge_digest: str,
        *, clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            type(worker_id) is not str or not worker_id or type(run_id) is not str or not run_id
            or type(challenge_digest) is not str or _DIGEST.fullmatch(challenge_digest) is None
            or not callable(clock)
        ):
            raise _invalid()
        self._worker_id = worker_id
        self._run_id = run_id
        self._challenge_digest = challenge_digest
        self._clock = clock
        self._started = clock()
        self._sequence = 0
        self._terminal = False
        self._response_sha256: str | None = None
        self._aggregate_sha256: str | None = None

    def __repr__(self) -> str:
        return "ProgrammaticLongContextRelease(redacted)"

    def consume(self, raw: object) -> dict[str, object]:
        """Accept exactly one next canonical frame; return only final safe facts."""
        if self._terminal or self._clock() - self._started > _DEADLINE_SECONDS:
            raise _invalid()
        value = self._parse(raw)
        if value["sequence"] != self._sequence or value["kind"] != _KINDS[self._sequence]:
            raise _invalid()
        payload = value["payload"]
        assert type(payload) is dict
        self._validate_payload(value["kind"], payload)
        self._sequence += 1
        if value["kind"] != "completed":
            return {}
        self._terminal = True
        assert self._response_sha256 is not None and self._aggregate_sha256 is not None
        return {
            "active_tool_names": ("ipython",),
            "aggregate_sha256": self._aggregate_sha256,
            "ipython_cell_executed": True,
            "oracle_passed": True,
            "program_sha256": self._response_sha256,
            "response_sha256": self._response_sha256,
            "session_disposed": True,
            "terminal": "completed",
            "tool_call_count": 1,
            "workload_digest": PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST,
        }

    def _parse(self, raw: object) -> dict[str, object]:
        if type(raw) is not bytes or not raw or len(raw) > PROGRAMMATIC_LONG_CONTEXT_MAX_FRAME_BYTES:
            raise _invalid()
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise _invalid() from None
        if (
            type(value) is not dict
            or set(value) != {"challenge_digest", "kind", "payload", "run_id", "sequence", "worker_id", "workload_digest"}
            or _canonical(value) != raw
            or value["worker_id"] != self._worker_id or value["run_id"] != self._run_id
            or value["challenge_digest"] != self._challenge_digest
            or value["workload_digest"] != PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST
            or type(value["sequence"]) is not int or value["sequence"] < 0
            or value["kind"] not in _KINDS or type(value["payload"]) is not dict
        ):
            raise _invalid()
        return value

    def _validate_payload(self, kind: object, payload: dict[str, object]) -> None:
        if kind == "self-check":
            valid = payload == _SELF_CHECK
        elif kind == "release":
            valid = payload == {"role_id": PROGRAMMATIC_LONG_CONTEXT_P2_ROLE_ID, "scenario_id": PROGRAMMATIC_LONG_CONTEXT_P2_SCENARIO_ID}
        elif kind == "model-response":
            response, program = payload.get("response_sha256"), payload.get("program_sha256")
            valid = set(payload) == {"program_sha256", "response_sha256"} and response == program and type(response) is str and _DIGEST.fullmatch(response) is not None
            if valid:
                assert type(response) is str
                self._response_sha256 = response
        elif kind == "ipython":
            valid = payload == {"active_tool_names": ["ipython"], "ipython_cell_executed": True, "tool_call_count": 1}
        elif kind == "oracle":
            aggregate = payload.get("aggregate_sha256")
            valid = set(payload) == {"aggregate_sha256", "oracle_passed"} and payload.get("oracle_passed") is True and type(aggregate) is str and _DIGEST.fullmatch(aggregate) is not None
            if valid:
                assert type(aggregate) is str
                self._aggregate_sha256 = aggregate
        elif kind == "session-disposed":
            valid = payload == {"session_disposed": True}
        elif kind == "completed":
            valid = payload == {
                "active_tool_names": ["ipython"], "aggregate_sha256": self._aggregate_sha256,
                "ipython_cell_executed": True, "oracle_passed": True,
                "program_sha256": self._response_sha256, "response_sha256": self._response_sha256,
                "session_disposed": True, "tool_call_count": 1,
            }
        else:
            valid = False
        if not valid:
            raise _invalid()
