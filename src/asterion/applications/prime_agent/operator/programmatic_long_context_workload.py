"""Sealed workload and completion facts for the Prime P2 worker.

This module deliberately owns the P2 identity.  It is not a configurable
workload registry and it contains neither corpus nor program contents.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Final


_DIGEST: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_WORKLOAD_MANIFEST: Final = {
    "built_in_tools": ["ipython"],
    "corpus_record_count": 8,
    "corpus_sha256": "sha256:" + "e" * 64,
    "format": "asterion.prime-programmatic-long-context-workload/v1",
    "oracle_sha256": "sha256:" + "f" * 64,
    "role_id": "prime.programmatic-long-context",
    "scenario_id": "prime.programmatic-long-context/v1",
    "selected_record_count": 3,
}

PROGRAMMATIC_LONG_CONTEXT_P2_CORPUS_SHA256: Final = _WORKLOAD_MANIFEST["corpus_sha256"]
PROGRAMMATIC_LONG_CONTEXT_P2_ORACLE_SHA256: Final = _WORKLOAD_MANIFEST["oracle_sha256"]
PROGRAMMATIC_LONG_CONTEXT_P2_ROLE_ID: Final = _WORKLOAD_MANIFEST["role_id"]
PROGRAMMATIC_LONG_CONTEXT_P2_SCENARIO_ID: Final = _WORKLOAD_MANIFEST["scenario_id"]
PROGRAMMATIC_LONG_CONTEXT_P2_CORPUS_RECORD_COUNT: Final = _WORKLOAD_MANIFEST[
    "corpus_record_count"
]
PROGRAMMATIC_LONG_CONTEXT_P2_SELECTED_RECORD_COUNT: Final = _WORKLOAD_MANIFEST[
    "selected_record_count"
]


class ProgrammaticLongContextWorkloadError(ValueError):
    """Raised when a value cannot belong to the sealed P2 contract."""


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


_WORKLOAD_MANIFEST_BYTES: Final = _canonical_json_bytes(_WORKLOAD_MANIFEST)
PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST: Final = (
    "sha256:" + sha256(_WORKLOAD_MANIFEST_BYTES).hexdigest()
)


def programmatic_long_context_workload_manifest_bytes() -> bytes:
    """Return the sole canonical P2 workload manifest; callers cannot select it."""
    return _WORKLOAD_MANIFEST_BYTES


def is_programmatic_long_context_workload(value: object) -> bool:
    """Return whether *value* is the exact P2 workload identity."""
    return type(value) is str and value == PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST


def _digest(value: object) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


@dataclass(frozen=True, repr=False)
class ProgrammaticLongContextCompletion:
    """Private dynamic digests admitted into the fixed P2 completion schema."""

    response_sha256: str
    program_sha256: str
    aggregate_sha256: str
    active_tool_names: tuple[str, ...] = ("ipython",)
    ipython_cell_executed: bool = True
    oracle_passed: bool = True
    session_disposed: bool = True

    def __repr__(self) -> str:
        return "ProgrammaticLongContextCompletion(redacted)"


def verify_programmatic_long_context_completion(completion: object) -> None:
    """Fail closed unless dynamic facts fit the one P2 completion schema."""
    if (
        type(completion) is not ProgrammaticLongContextCompletion
        or completion.active_tool_names != ("ipython",)
        or completion.ipython_cell_executed is not True
        or completion.oracle_passed is not True
        or completion.session_disposed is not True
        or not all(
            _digest(value)
            for value in (
                completion.response_sha256,
                completion.program_sha256,
                completion.aggregate_sha256,
            )
        )
        or completion.response_sha256 != completion.program_sha256
    ):
        raise ProgrammaticLongContextWorkloadError(
            "programmatic long-context completion is invalid"
        )


def canonical_programmatic_long_context_completion_bytes(completion: object) -> bytes:
    """Encode the one public-safe completion shape after strict admission."""
    try:
        verify_programmatic_long_context_completion(completion)
    except ProgrammaticLongContextWorkloadError:
        raise ProgrammaticLongContextWorkloadError(
            "programmatic long-context completion is invalid"
        ) from None
    assert type(completion) is ProgrammaticLongContextCompletion
    return _canonical_json_bytes(
        {
            "active_tool_names": ["ipython"],
            "aggregate_sha256": completion.aggregate_sha256,
            "corpus_record_count": PROGRAMMATIC_LONG_CONTEXT_P2_CORPUS_RECORD_COUNT,
            "corpus_sha256": PROGRAMMATIC_LONG_CONTEXT_P2_CORPUS_SHA256,
            "format": "asterion.prime-programmatic-long-context-result/v1",
            "ipython_cell_executed": True,
            "oracle_passed": True,
            "oracle_sha256": PROGRAMMATIC_LONG_CONTEXT_P2_ORACLE_SHA256,
            "program_sha256": completion.program_sha256,
            "response_sha256": completion.response_sha256,
            "role_id": PROGRAMMATIC_LONG_CONTEXT_P2_ROLE_ID,
            "scenario_id": PROGRAMMATIC_LONG_CONTEXT_P2_SCENARIO_ID,
            "selected_record_count": PROGRAMMATIC_LONG_CONTEXT_P2_SELECTED_RECORD_COUNT,
            "session_disposed": True,
            "workload_digest": PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST,
        }
    )
