#!/usr/bin/env python3
"""Serialize a caller-injected Prime release proposal to standard output only.

This deliberately has no output-path option.  It does not acquire data, write
an external work root, or grant authorization to materialize a release.
"""

from __future__ import annotations

import json
import sys

from asterion.applications.prime_agent.operator.release_spec_generation import (
    PrimeReleaseSpecGenerationError,
    canonical_release_spec_generation_json,
    generate_release_specification,
    release_spec_generation_request_from_dict,
)


def main() -> int:
    """Parse one injected JSON request from stdin and emit canonical JSON."""

    try:
        value = json.load(sys.stdin)
        request = release_spec_generation_request_from_dict(value)
        print(canonical_release_spec_generation_json(generate_release_specification(request)))
    except (json.JSONDecodeError, PrimeReleaseSpecGenerationError):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
