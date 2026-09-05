"""Closed workload identity for the Prime IPython coding worker."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Final


_WORKLOAD_PATH: Final = Path(__file__).with_name("image") / "fixture/workload.json"
PRIME_IPYTHON_CODING_EXPECTED_RESULT_SHA256: Final = (
    "f4ebce1e8a4576db9235f6d8c67dffd9718931f64a07960e1d83b3809d3ce022"
)
_WORKLOAD: Final = {
    "capability_ref": "prime.ipython-coding@1.0.0",
    "expected_result_sha256": PRIME_IPYTHON_CODING_EXPECTED_RESULT_SHA256,
    "final_oracle_passed": True,
    "format": "asterion.prime-ipython-coding-workload/v1",
    "initial_oracle_passed": False,
    "ipython_tool_call_count": 1,
    "model_request_count": 1,
    "model_tools": ["ipython"],
    "oracle_sha256": "85ee4060b19a5ee375e4c6258f45b1df722f53efd8310f56603b31639fa3c4eb",
    "prime_sdk_ref": "prime-agent@0.7.1",
    "starter_sha256": "4f8e0bca0f70582bad96caa292823ac29577633bebd9f76257617dc92ab6832f",
    "version": "1.0.0",
    "workload_id": "prime.ipython-coding",
    "workspace_mutation_required": True,
}


def _parse_prime_ipython_coding_workload(value: object) -> None:
    """Reject anything other than the exact canonical P1 workload bytes."""

    if type(value) is not bytes:
        raise ValueError("Prime IPython workload is invalid")
    try:
        decoded = value.decode("utf-8")
        parsed = json.loads(decoded)
        canonical = json.dumps(
            parsed,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
    except (UnicodeDecodeError, ValueError, TypeError):
        raise ValueError("Prime IPython workload is invalid") from None
    if canonical != value or parsed != _WORKLOAD:
        raise ValueError("Prime IPython workload is invalid")


_WORKLOAD_BYTES: Final = _WORKLOAD_PATH.read_bytes()
_parse_prime_ipython_coding_workload(_WORKLOAD_BYTES)
PRIME_IPYTHON_CODING_WORKLOAD_DIGEST: Final = "sha256:" + sha256(
    _WORKLOAD_BYTES
).hexdigest()


def prime_ipython_coding_workload_bytes() -> bytes:
    """Return the exact image-resident P1 workload declaration."""

    return _WORKLOAD_BYTES


def is_prime_ipython_coding_workload(value: object) -> bool:
    """Return whether *value* is the only admitted Prime worker workload."""
    return type(value) is str and value == PRIME_IPYTHON_CODING_WORKLOAD_DIGEST
