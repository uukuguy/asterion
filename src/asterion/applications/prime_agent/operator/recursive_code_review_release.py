"""Private canonical frame reducer for the sealed Prime P3 launcher."""

from __future__ import annotations

import json
import re
import time
from typing import Callable, Final

from asterion.applications.prime_agent.recursive_workflow_receipt import RecursiveWorkflowTrace

from .recursive_code_review_workload import (
    RECURSIVE_CODE_REVIEW_P3_CHILD_ROLE_IDS,
    RECURSIVE_CODE_REVIEW_P3_FOLLOW_UP_ROLE_ID,
    RECURSIVE_CODE_REVIEW_P3_ROLE_ID,
    RECURSIVE_CODE_REVIEW_P3_SCENARIO_ID,
    RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST,
)


RECURSIVE_CODE_REVIEW_MAX_FRAME_BYTES: Final = 4096
_DEADLINE_SECONDS: Final = 1.0
_DIGEST: Final = re.compile(r"sha256:[0-9a-f]{64}")
_KINDS: Final = (
    "self-check", "release", "root-artifact", "child-admitted", "child-result",
    "child-admitted", "child-result", "follow-up", "follow-up-result", "aggregation",
    "child-deleted", "child-deleted", "completed",
)
_SELF_CHECK: Final = {
    "credentials_absent": True, "effective_capabilities": 0, "effective_user_id": 65534,
    "no_new_privileges": 1, "nonloopback_network_absent": True, "root_read_only": True,
    "seccomp_mode": 2, "workspace_only_writable": True,
}


class RecursiveCodeReviewReleaseError(ValueError):
    """Raised without disclosing a private P3 launcher frame."""


def _invalid() -> RecursiveCodeReviewReleaseError:
    return RecursiveCodeReviewReleaseError("recursive code-review release is invalid")


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: object) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def canonical_recursive_code_review_frame(
    *, worker_id: str, run_id: str, challenge_digest: str, workload_digest: str,
    sequence: int, kind: str, payload: dict[str, object],
) -> bytes:
    """Construct canonical private P3 transport bytes for tests and image code."""
    value = {"challenge_digest": challenge_digest, "kind": kind, "payload": payload,
             "run_id": run_id, "sequence": sequence, "worker_id": worker_id,
             "workload_digest": workload_digest}
    if (
        type(worker_id) is not str or not worker_id or type(run_id) is not str or not run_id
        or not _digest(challenge_digest) or workload_digest != RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST
        or type(sequence) is not int or sequence < 0 or kind not in _KINDS or type(payload) is not dict
    ):
        raise _invalid()
    return _canonical(value)


class _RecursiveCodeReviewRelease:
    def __init__(self, worker_id: str, run_id: str, challenge_digest: str, *, clock: Callable[[], float]) -> None:
        if type(worker_id) is not str or not worker_id or type(run_id) is not str or not run_id or not _digest(challenge_digest) or not callable(clock):
            raise _invalid()
        self._worker_id, self._run_id, self._challenge_digest, self._clock = worker_id, run_id, challenge_digest, clock
        self._started, self._sequence = clock(), 0
        self._admissions: dict[str, tuple[str, str]] = {}
        self._results: dict[str, str] = {}
        self._root_artifact: str | None = None
        self._follow_up: str | None = None
        self._aggregate: tuple[str, str, str, str] | None = None
        self._deleted: set[str] = set()

    def consume(self, raw: object) -> None:
        if self._clock() - self._started > _DEADLINE_SECONDS:
            raise _invalid()
        value = self._parse(raw)
        if value["sequence"] != self._sequence or value["kind"] != _KINDS[self._sequence]:
            raise _invalid()
        self._validate(value["kind"], value["payload"])
        self._sequence += 1

    def trace(self) -> RecursiveWorkflowTrace:
        if self._sequence != len(_KINDS) or self._root_artifact is None or self._follow_up is None or self._aggregate is None:
            raise _invalid()
        if set(self._admissions) != set(RECURSIVE_CODE_REVIEW_P3_CHILD_ROLE_IDS) or set(self._results) != set(RECURSIVE_CODE_REVIEW_P3_CHILD_ROLE_IDS) or self._deleted != set(RECURSIVE_CODE_REVIEW_P3_CHILD_ROLE_IDS):
            raise _invalid()
        first, second = RECURSIVE_CODE_REVIEW_P3_CHILD_ROLE_IDS
        oracle, model, usage, aggregation = self._aggregate
        return RecursiveWorkflowTrace(
            workload_sha256=RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST,
            root_artifact_sha256=self._root_artifact,
            first_child_role_digests=(self._admissions[first][0], self._admissions[second][0]),
            first_child_result_digests=(self._results[first], self._results[second]),
            first_child_usage_digests=(self._admissions[first][1], self._admissions[second][1]),
            follow_up_digest=self._follow_up, aggregation_sha256=aggregation, oracle_sha256=oracle,
            model_sha256=model, usage_sha256=usage, root_to_child_message_count=2,
            child_to_root_result_count=3, follow_up_count=1, root_deleted_child_count=2,
            root_continued_locally=True, root_work_before_children=True,
            child_tool_names=(("ipython",), ("ipython",)), child_ipython_action_counts=(1, 1),
            revoked=True, disposed=True, reaped=True,
        )

    def _parse(self, raw: object) -> dict[str, object]:
        if type(raw) is not bytes or not raw or len(raw) > RECURSIVE_CODE_REVIEW_MAX_FRAME_BYTES:
            raise _invalid()
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise _invalid() from None
        if (
            type(value) is not dict or set(value) != {"challenge_digest", "kind", "payload", "run_id", "sequence", "worker_id", "workload_digest"}
            or _canonical(value) != raw or value["worker_id"] != self._worker_id or value["run_id"] != self._run_id
            or value["challenge_digest"] != self._challenge_digest or value["workload_digest"] != RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST
            or type(value["sequence"]) is not int or value["sequence"] < 0 or type(value["kind"]) is not str
            or type(value["payload"]) is not dict
        ):
            raise _invalid()
        return value

    def _validate(self, kind: object, payload: object) -> None:
        if type(payload) is not dict:
            raise _invalid()
        expected_child = RECURSIVE_CODE_REVIEW_P3_CHILD_ROLE_IDS[
            0 if self._sequence in (3, 4, 10) else 1
        ]
        if kind == "self-check":
            valid = payload == _SELF_CHECK
        elif kind == "release":
            valid = payload == {"child_role_ids": list(RECURSIVE_CODE_REVIEW_P3_CHILD_ROLE_IDS), "role_id": RECURSIVE_CODE_REVIEW_P3_ROLE_ID, "scenario_id": RECURSIVE_CODE_REVIEW_P3_SCENARIO_ID}
        elif kind == "root-artifact":
            valid = set(payload) == {"root_artifact_sha256", "root_work_before_children"} and _digest(payload.get("root_artifact_sha256")) and payload.get("root_work_before_children") is True
            if valid:
                self._root_artifact = payload["root_artifact_sha256"]  # type: ignore[assignment]
        elif kind == "child-admitted":
            role, role_digest, usage = payload.get("child_role_id"), payload.get("child_role_sha256"), payload.get("child_usage_sha256")
            valid = set(payload) == {"child_role_id", "child_role_sha256", "child_usage_sha256"} and role == expected_child and _digest(role_digest) and _digest(usage) and role not in self._admissions
            if valid:
                self._admissions[role] = (role_digest, usage)  # type: ignore[index,assignment]
        elif kind == "child-result":
            role, result = payload.get("child_role_id"), payload.get("child_result_sha256")
            valid = set(payload) == {"child_role_id", "child_result_sha256", "ipython_action_count"} and role == expected_child and role in self._admissions and role not in self._results and _digest(result) and payload.get("ipython_action_count") == 1
            if valid:
                self._results[role] = result  # type: ignore[index,assignment]
        elif kind == "follow-up":
            follow_up = payload.get("follow_up_digest")
            valid = set(payload) == {"follow_up_digest", "target_role_id"} and payload.get("target_role_id") == RECURSIVE_CODE_REVIEW_P3_FOLLOW_UP_ROLE_ID and _digest(follow_up) and self._results.keys() == set(RECURSIVE_CODE_REVIEW_P3_CHILD_ROLE_IDS)
            if valid:
                self._follow_up = follow_up  # type: ignore[assignment]
        elif kind == "follow-up-result":
            valid = payload == {"child_role_id": RECURSIVE_CODE_REVIEW_P3_FOLLOW_UP_ROLE_ID, "follow_up_digest": self._follow_up}
        elif kind == "aggregation":
            values = tuple(payload.get(name) for name in ("oracle_sha256", "model_sha256", "usage_sha256", "aggregation_sha256"))
            valid = set(payload) == {"oracle_sha256", "model_sha256", "usage_sha256", "aggregation_sha256"} and all(_digest(item) for item in values)
            if valid:
                self._aggregate = values  # type: ignore[assignment]
        elif kind == "child-deleted":
            role = payload.get("child_role_id")
            valid = payload == {"child_role_id": expected_child} and role not in self._deleted
            if valid:
                self._deleted.add(role)  # type: ignore[arg-type]
        elif kind == "completed":
            valid = payload == {"disposed": True, "reaped": True, "revoked": True} and self._deleted == set(RECURSIVE_CODE_REVIEW_P3_CHILD_ROLE_IDS)
        else:
            valid = False
        if not valid:
            raise _invalid()


def parse_recursive_code_review_frames(data: bytes, *, clock: Callable[[], float] = time.monotonic) -> RecursiveWorkflowTrace:
    """Reduce one sealed P3 image stream to its private normalized trace."""
    if type(data) is not bytes or not data or len(data) > len(_KINDS) * (RECURSIVE_CODE_REVIEW_MAX_FRAME_BYTES + 1):
        raise _invalid()
    frames = data.splitlines()
    if len(frames) != len(_KINDS):
        raise _invalid()
    first = frames[0]
    try:
        identity = json.loads(first.decode("utf-8"))
        worker_id, run_id, challenge = identity["worker_id"], identity["run_id"], identity["challenge_digest"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        raise _invalid() from None
    release = _RecursiveCodeReviewRelease(worker_id, run_id, challenge, clock=clock)
    for frame in frames:
        release.consume(frame)
    return release.trace()
