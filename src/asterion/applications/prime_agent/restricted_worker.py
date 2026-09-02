"""Closed sandbox profile required by Prime restricted workers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


_IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_PROFILE_FIELDS = frozenset(
    {
        "image_digest",
        "network_mode",
        "workspace_mode",
        "credential_mode",
        "max_runtime_seconds",
        "max_output_bytes",
    }
)


class PrimeRestrictedWorkerError(ValueError):
    """Raised when a Prime restricted-worker sandbox profile is unsafe."""


@dataclass(frozen=True)
class PrimeRestrictedWorkerProfile:
    """The only permitted execution environment for a restricted worker."""

    image_digest: str
    network_mode: Literal["none"]
    workspace_mode: Literal["disposable"]
    credential_mode: Literal["absent"]
    max_runtime_seconds: int
    max_output_bytes: int


def validate_prime_restricted_worker(
    profile: PrimeRestrictedWorkerProfile,
) -> PrimeRestrictedWorkerProfile:
    """Fail closed unless *profile* specifies the complete sandbox boundary."""

    if (
        type(profile) is not PrimeRestrictedWorkerProfile
        or frozenset(vars(profile)) != _PROFILE_FIELDS
        or type(profile.image_digest) is not str
        or _IMAGE_DIGEST.fullmatch(profile.image_digest) is None
        or type(profile.network_mode) is not str
        or profile.network_mode != "none"
        or type(profile.workspace_mode) is not str
        or profile.workspace_mode != "disposable"
        or type(profile.credential_mode) is not str
        or profile.credential_mode != "absent"
        or type(profile.max_runtime_seconds) is not int
        or profile.max_runtime_seconds <= 0
        or type(profile.max_output_bytes) is not int
        or profile.max_output_bytes <= 0
    ):
        raise PrimeRestrictedWorkerError("restricted worker profile is invalid")
    return profile
