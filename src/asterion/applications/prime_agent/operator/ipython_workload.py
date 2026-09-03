"""Closed workload identity for the Prime IPython coding worker."""

from __future__ import annotations

from typing import Final


PRIME_IPYTHON_CODING_WORKLOAD_DIGEST: Final = (
    "sha256:f4ebce1e8a4576db9235f6d8c67dffd9718931f64a07960e1d83b3809d3ce022"
)


def is_prime_ipython_coding_workload(value: object) -> bool:
    """Return whether *value* is the only admitted Prime worker workload."""
    return value == PRIME_IPYTHON_CODING_WORKLOAD_DIGEST
