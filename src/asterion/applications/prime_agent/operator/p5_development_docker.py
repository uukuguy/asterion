"""P5's one-container worker ownership boundary.

The concrete transport remains P1-B's daemon-admitted persistent worker; P5
adds no image, mount, or executable selection surface.
"""

from __future__ import annotations

from .p1b_development_docker import (
    P1BDevelopmentSnapshotTransport as P5DevelopmentSnapshotTransport,
    P1BDockerPersistentWorkerService as P5DevelopmentDockerWorkerService,
)


class PrimeP5DevelopmentDockerError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P5 development docker worker is unavailable")


__all__ = (
    "P5DevelopmentDockerWorkerService",
    "P5DevelopmentSnapshotTransport",
    "PrimeP5DevelopmentDockerError",
)
