"""Static, authority-only admission of a promoted Prime P1 image input."""

from __future__ import annotations

from .authority_config import PrimeP1OperatorConfig
from .image_input_lock import (
    ImageInputLock,
    ImagePlatformDescriptor,
    resolve_promoted_image_input_lock,
)


class PrimeP1AuthorityResourceError(ValueError):
    """Single public-safe image-resource admission failure category."""

    def __init__(self, *_: object) -> None:
        super().__init__("prime P1 authority resource is unavailable")


def admit_static_image_resource(config: object) -> ImageInputLock:
    """Resolve only the operator-selected platform from the promoted catalog.

    The config is already a descriptor-only, authority-owned value.  This
    boundary neither discovers host state nor performs Docker, network,
    execution, receipt, or readiness work.
    """
    if type(config) is not PrimeP1OperatorConfig:
        raise PrimeP1AuthorityResourceError() from None
    resource: ImageInputLock | None = None
    try:
        values = config._values
        variant = values["ASTERION_PRIME_P1_IMAGE_PLATFORM_VARIANT"]
        platform = ImagePlatformDescriptor(
            values["ASTERION_PRIME_P1_IMAGE_PLATFORM_OS"],
            values["ASTERION_PRIME_P1_IMAGE_PLATFORM_ARCHITECTURE"],
            None if variant == "none" else variant,
        )
        resource = resolve_promoted_image_input_lock(platform)
    except Exception:
        pass
    if resource is None:
        raise PrimeP1AuthorityResourceError() from None
    return resource
