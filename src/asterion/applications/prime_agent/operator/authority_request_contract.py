"""Fixed, non-authoritative Prime P1 request-contract bytes."""

from __future__ import annotations

import hashlib
import json


def canonical_prime_p1_request_contract_bytes() -> bytes:
    """Return the closed P1 request contract without consulting host state."""
    value = {
        "format": "asterion.prime-p1-request-contract/v1",
        "controls": {
            "deadline_milliseconds": 60_000,
            "max_cost_microunits": 10_000,
            "max_input_bytes": 4096,
            "max_output_bytes": 4096,
            "max_input_tokens": 1024,
            "max_output_tokens": 1024,
            "max_requests": 1,
        },
        "identity": {
            "provider_id": "prime-agent",
            "application_id": "prime.ipython-coding",
            "application_version": "1.0.0",
            "assembly_ref": "prime.ipython-coding@1.0.0",
            "implementation_ref": "prime.ipython-coding@1.0.0",
            "package_ref": "prime-agent@1.0.0",
            "prime_sdk_ref": "prime-agent@0.7.1",
            "runtime_id": "prime.agent",
        },
        "model_tools": ["ipython"],
        "workload_sha256": "f4ebce1e8a4576db9235f6d8c67dffd9718931f64a07960e1d83b3809d3ce022",
        "oracle_sha256": "85ee4060b19a5ee375e4c6258f45b1df722f53efd8310f56603b31639fa3c4eb",
    }
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def prime_p1_request_contract_sha256() -> str:
    """Return the SHA-256 of the fixed canonical request-contract bytes."""
    return hashlib.sha256(canonical_prime_p1_request_contract_bytes()).hexdigest()
