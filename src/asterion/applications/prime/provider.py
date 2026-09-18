"""Metadata-only provider for native Asterion-prime applications."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from asterion.applications.first_party_packages import (
    PRIME_ARC_AGI_3_SOLVER_PACKAGE,
    PRIME_IPYTHON_CODING_NATIVE_PACKAGE,
    PRIME_LONG_SESSION_CONTINUITY_NATIVE_PACKAGE,
    PRIME_PROGRAMMATIC_LONG_CONTEXT_NATIVE_PACKAGE,
    PRIME_RECURSIVE_WORKFLOW_NATIVE_PACKAGE,
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
    """Return the exact P1 application record.

    P1's operator composes itself from this record instead of looking itself up
    in the published list. Running an application must not depend on whether it
    is advertised: if it does, the installed-route witness can only be produced
    after publication while publication is gated on that same witness, and the
    application's own route tests cannot build a fixture at all. The record is
    also published by :func:`create_provider` now that the witness has passed.
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
    """Return the provider carrying P1's own record alone.

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


def prime_programmatic_long_context_application() -> InstalledApplication:
    """Return the exact P2 application record.

    Mirrors :func:`prime_ipython_coding_application`: P2's operator composes
    itself from this record instead of looking itself up in the published
    list. The selector stays unpublished until the installed-route witness
    passes, per the detachment spec's "the exact selector is added back
    only with its native package and installed-route witness" rule.
    """

    root = _resource_root()
    return InstalledApplication(
        application_id="prime.programmatic-long-context",
        version="1.0.0",
        assembly_paths=(
            root / "applications/prime/assemblies/prime-programmatic-long-context.json",
        ),
        capability_packages=(PRIME_PROGRAMMATIC_LONG_CONTEXT_NATIVE_PACKAGE,),
        runtime_ids=("asterion.prime",),
    )


def create_prime_programmatic_long_context_provider() -> InstalledApplicationProvider:
    """Return the provider carrying P2's own record alone.

    See :func:`prime_programmatic_long_context_application` for why the
    P2 operator composes itself from this provider rather than from the
    public :func:`create_provider`.
    """

    return InstalledApplicationProvider(
        protocol=APPLICATION_PROVIDER_PROTOCOL,
        provider_id="prime-applications",
        resource_root=_resource_root(),
        applications=(prime_programmatic_long_context_application(),),
        runtime_factory_bindings=(asterion_prime_runtime_binding(),),
    )


def prime_long_session_continuity_application() -> InstalledApplication:
    """Return the exact P4 application record.

    Mirrors :func:`prime_programmatic_long_context_application`: P4's
    operator composes itself from this record instead of looking itself up
    in the published list. The selector stays unpublished until the
    installed-route witness passes (Phase 6, Task 17).
    """

    root = _resource_root()
    return InstalledApplication(
        application_id="prime.long-session-continuity",
        version="1.0.0",
        assembly_paths=(
            root / "applications/prime/assemblies/prime-long-session-continuity.json",
        ),
        capability_packages=(PRIME_LONG_SESSION_CONTINUITY_NATIVE_PACKAGE,),
        runtime_ids=("asterion.prime",),
    )


def create_prime_long_session_continuity_provider() -> InstalledApplicationProvider:
    """Return the provider carrying P4's own record alone.

    See :func:`prime_long_session_continuity_application` for why the
    P4 operator composes itself from this provider rather than from the
    public :func:`create_provider`.
    """

    return InstalledApplicationProvider(
        protocol=APPLICATION_PROVIDER_PROTOCOL,
        provider_id="prime-applications",
        resource_root=_resource_root(),
        applications=(prime_long_session_continuity_application(),),
        runtime_factory_bindings=(asterion_prime_runtime_binding(),),
    )


def prime_recursive_workflow_application() -> InstalledApplication:
    """Return the exact P3 application record.

    Mirrors :func:`prime_long_session_continuity_application`: P3's
    operator composes itself from this record instead of looking itself up
    in the published list. The selector stays unpublished until the
    installed-route witness passes (Phase 7, Task 16).
    """

    root = _resource_root()
    return InstalledApplication(
        application_id="prime.recursive-workflow",
        version="1.0.0",
        assembly_paths=(
            root / "applications/prime/assemblies/prime-recursive-workflow.json",
        ),
        capability_packages=(PRIME_RECURSIVE_WORKFLOW_NATIVE_PACKAGE,),
        runtime_ids=("asterion.prime",),
    )


def create_prime_recursive_workflow_provider() -> InstalledApplicationProvider:
    """Return the provider carrying P3's own record alone.

    See :func:`prime_recursive_workflow_application` for why the
    P3 operator composes itself from this provider rather than from the
    public :func:`create_provider`.
    """

    return InstalledApplicationProvider(
        protocol=APPLICATION_PROVIDER_PROTOCOL,
        provider_id="prime-applications",
        resource_root=_resource_root(),
        applications=(prime_recursive_workflow_application(),),
        runtime_factory_bindings=(asterion_prime_runtime_binding(),),
    )


def create_provider() -> InstalledApplicationProvider:
    """Return sorted native Prime applications and one peer runtime binding.

    P2 is published together with its installed-route witness (Phase 5,
    Task 4): exit 0 + sealed receipt ``cac924edc5e12b9cb5d1d88e17ac547bd82ac00328dbab74de5157cc7217e0e5``
    from ``make asterion-prime-p2-run``. P4 is published together with its
    cross-generation continuity witness (Phase 6, Task 17): exit 0 + sealed
    receipt ``6b5a173d16d1d1a5382456284a7bbde1b0516120f13c1e9e4572e5f367757a0d``
    from ``make asterion-prime-p4-run``. The selector returns the exact
    application records those operators compose from via
    :func:`create_prime_programmatic_long_context_provider` and
    :func:`create_prime_long_session_continuity_provider`.
    """

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
            # Published together with its witness (Phase 4, D-2026-09-12-01):
            # the detachment spec requires an unmigrated selector to be omitted,
            # so the selector returns only once the installed-route witness
            # passes. Publishing it before that also made resolution impossible
            # for the P7 route, because the closure is validated for every
            # published application; the package it needs is now supplied.
            prime_ipython_coding_application(),
            # Phase 6, Task 17: published together with its installed-route
            # cross-generation continuity witness (sealed receipt
            # ``6b5a173d16d1d1a5382456284a7bbde1b0516120f13c1e9e4572e5f367757a0d``).
            # The recover-mode invocation opens the prior's private_root at
            # gen 2 and reads back the prior sealed checkpoint digest; the
            # witness asserts cross-process continuity under a fresh Orb
            # wheel build (D-2026-09-18-01).
            prime_long_session_continuity_application(),
            # Phase 5, Task 4: published together with its installed-route
            # witness (``cac924edc5e12b9cb5d1d88e17ac547bd82ac00328dbab74de5157cc7217e0e5``).
            prime_programmatic_long_context_application(),
        ),
        runtime_factory_bindings=(asterion_prime_runtime_binding(),),
    )


__all__ = (
    "create_prime_ipython_coding_provider",
    "create_prime_long_session_continuity_provider",
    "create_prime_programmatic_long_context_provider",
    "create_prime_recursive_workflow_provider",
    "create_provider",
    "prime_ipython_coding_application",
    "prime_long_session_continuity_application",
    "prime_programmatic_long_context_application",
    "prime_recursive_workflow_application",
)
