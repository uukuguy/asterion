"""Metadata-only provider for native Asterion-prime applications."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from asterion.applications.first_party_packages import (
    PRIME_ARC_AGI_3_SOLVER_PACKAGE,
    PRIME_IPYTHON_CODING_NATIVE_PACKAGE,
)
from asterion.applications.provider import (
    APPLICATION_PROVIDER_PROTOCOL,
    InstalledApplication,
    InstalledApplicationProvider,
)
from asterion.applications.prime.runtime_binding import (
    asterion_prime_runtime_binding,
)


def _resource_root() -> Path:
    return Path(str(resources.files("asterion"))).resolve()


def prime_ipython_coding_application() -> InstalledApplication:
    """Return the exact P1 application record, published or not.

    P1's operator composes itself from this record instead of looking itself up
    in the published list. Running an application must not depend on whether it
    is advertised: if it does, the installed-route witness can only be produced
    after publication while publication is gated on that same witness, and the
    application's own route tests cannot build a fixture at all. ``create_provider``
    appends this record once the witness lands.
    """

    root = _resource_root()
    return InstalledApplication(
        application_id="prime.ipython-coding",
        version="1.0.0",
        assembly_paths=(
            root / "applications/prime/assemblies/prime-ipython-coding.json",
        ),
        capability_packages=(PRIME_IPYTHON_CODING_NATIVE_PACKAGE,),
        runtime_ids=("asterion.prime",),
    )


def create_prime_ipython_coding_provider() -> InstalledApplicationProvider:
    """Return the provider carrying P1's own record, published or not.

    P1's operator composes itself from this provider instead of from
    :func:`create_provider`, so running the application never depends on
    whether it is advertised in the public list. See
    :func:`prime_ipython_coding_application` for why that separation matters.
    """

    return InstalledApplicationProvider(
        protocol=APPLICATION_PROVIDER_PROTOCOL,
        provider_id="prime-applications",
        resource_root=_resource_root(),
        applications=(prime_ipython_coding_application(),),
        runtime_factory_bindings=(asterion_prime_runtime_binding(),),
    )


def create_provider() -> InstalledApplicationProvider:
    """Return sorted native Prime applications and one peer runtime binding."""

    root = _resource_root()
    return InstalledApplicationProvider(
        protocol=APPLICATION_PROVIDER_PROTOCOL,
        provider_id="prime-applications",
        resource_root=root,
        applications=(
            InstalledApplication(
                application_id="prime.arc-agi-3-solving",
                version="1.0.0",
                assembly_paths=(
                    root / "applications/prime/assemblies/prime-arc-agi-3-solving.json",
                ),
                capability_packages=(PRIME_ARC_AGI_3_SOLVER_PACKAGE,),
                runtime_ids=("asterion.prime",),
            ),
            # prime.ipython-coding is deliberately NOT published. It has no
            # installed-route witness yet, and the detachment spec requires an
            # unmigrated selector to be omitted so metadata lookup rejects it
            # before importing a runtime or starting a process. Publishing it
            # here also made resolution impossible for the P7 route: the closure
            # is validated for every published application, so a P7 run failed
            # unless P1's package was supplied too. Its record is defined by
            # :func:`prime_ipython_coding_application` and is appended here once
            # Phase 4 supplies the witness.
        ),
        runtime_factory_bindings=(asterion_prime_runtime_binding(),),
    )


__all__ = (
    "create_prime_ipython_coding_provider",
    "create_provider",
    "prime_ipython_coding_application",
)
