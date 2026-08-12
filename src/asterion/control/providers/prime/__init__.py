"""Prime exact control-provider binding."""

from __future__ import annotations

from asterion.control.providers.prime.client import (
    MAX_PRIVATE_ATTACHMENT_BYTES,
    PrimeControlError,
    PrimeControlPlaneClient,
)
from asterion.control.private_store import (
    PrivateAttachmentResolver,
    PrivateContentResolver,
)
from asterion.control.providers.prime.factory import (
    PRIME_CONTROL_PLANE_ID,
    PRIME_CONTROL_PLANE_VERSION,
    PRIME_NATIVE_RLM_MAX_DEPTH,
    build_prime_control_plane_client,
    derive_prime_child_control_options,
    prime_control_plane_binding,
)
from asterion.control.providers.prime.process import (
    PrimeSidecarLaunchOptions,
    PrimeSidecarProcess,
    PrimeSidecarProcessError,
    PrimeSidecarSpawnPlan,
    build_prime_sidecar_spawn_plan,
)
from asterion.control.providers.prime.system_actions import PrimeSystemActionService
from asterion.control.providers.prime.rlm import PrimeRlmAdmissionPreparer

__all__ = (
    "PRIME_CONTROL_PLANE_ID",
    "PRIME_CONTROL_PLANE_VERSION",
    "PRIME_NATIVE_RLM_MAX_DEPTH",
    "MAX_PRIVATE_ATTACHMENT_BYTES",
    "PrivateAttachmentResolver",
    "PrimeControlError",
    "PrimeControlPlaneClient",
    "PrimeSidecarLaunchOptions",
    "PrimeSidecarProcess",
    "PrimeSidecarProcessError",
    "PrimeSidecarSpawnPlan",
    "PrimeSystemActionService",
    "PrimeRlmAdmissionPreparer",
    "PrivateContentResolver",
    "build_prime_control_plane_client",
    "derive_prime_child_control_options",
    "build_prime_sidecar_spawn_plan",
    "prime_control_plane_binding",
)
