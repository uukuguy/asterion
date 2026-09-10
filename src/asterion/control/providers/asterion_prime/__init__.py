"""Native Asterion Prime control-provider surface."""

from asterion.control.providers.asterion_prime.client import (
    AsterionPrimeControlError,
    AsterionPrimeControlPlaneClient,
)
from asterion.control.providers.asterion_prime.factory import (
    ASTERION_PRIME_CONTROL_PLANE_ID,
    ASTERION_PRIME_CONTROL_PLANE_VERSION,
    ASTERION_PRIME_SESSION_BACKEND_SERVICE,
    asterion_prime_control_plane_binding,
    build_asterion_prime_control_plane_client,
)


__all__ = (
    "ASTERION_PRIME_CONTROL_PLANE_ID",
    "ASTERION_PRIME_CONTROL_PLANE_VERSION",
    "ASTERION_PRIME_SESSION_BACKEND_SERVICE",
    "AsterionPrimeControlError",
    "AsterionPrimeControlPlaneClient",
    "asterion_prime_control_plane_binding",
    "build_asterion_prime_control_plane_client",
)
