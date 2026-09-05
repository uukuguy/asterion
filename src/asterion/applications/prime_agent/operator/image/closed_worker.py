"""P1-B imports the P1-A closed-worker check without duplicating its policy."""

from __future__ import annotations

try:  # Package import in tests and development tooling.
    from .launcher import require_closed_worker
except ImportError:  # pragma: no cover - copied beside the Docker entrypoint.
    from launcher import require_closed_worker


__all__ = ("require_closed_worker",)
