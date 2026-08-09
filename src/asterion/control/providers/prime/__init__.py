"""Prime exact control-provider binding."""

from __future__ import annotations

from asterion.control.providers.prime.client import (
    PrimeControlError,
    PrimeControlPlaneClient,
    PrivateContentResolver,
)
from asterion.control.providers.prime.factory import (
    PRIME_CONTROL_PLANE_ID,
    PRIME_CONTROL_PLANE_VERSION,
    build_prime_control_plane_client,
    prime_control_plane_binding,
)
from asterion.control.providers.prime.process import (
    PrimeSidecarLaunchOptions,
    PrimeSidecarProcess,
    PrimeSidecarProcessError,
    PrimeSidecarSpawnPlan,
    build_prime_sidecar_spawn_plan,
)

__all__ = (
    "PRIME_CONTROL_PLANE_ID",
    "PRIME_CONTROL_PLANE_VERSION",
    "PrimeControlError",
    "PrimeControlPlaneClient",
    "PrimeSidecarLaunchOptions",
    "PrimeSidecarProcess",
    "PrimeSidecarProcessError",
    "PrimeSidecarSpawnPlan",
    "PrivateContentResolver",
    "build_prime_control_plane_client",
    "build_prime_sidecar_spawn_plan",
    "prime_control_plane_binding",
)
