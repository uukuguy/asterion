"""Metadata-only provider for native Asterion-prime applications."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from asterion.applications.provider import (
    APPLICATION_PROVIDER_PROTOCOL,
    InstalledApplication,
    InstalledApplicationProvider,
)
from asterion.applications.prime.inventory import (
    PRIME_RELEASE_INVENTORY,
    PrimeReleaseApplication,
    prime_release_application,
)
from asterion.applications.prime.runtime_binding import (
    asterion_prime_runtime_binding,
)


def _resource_root() -> Path:
    return Path(str(resources.files("asterion"))).resolve()


def _installed_application(
    item: PrimeReleaseApplication, root: Path
) -> InstalledApplication:
    return InstalledApplication(
        application_id=item.application_id,
        version=item.version,
        assembly_paths=(root / item.assembly_identity,),
        capability_packages=(item.capability_package,),
        runtime_ids=("asterion.prime",),
    )


def _declared_application(application_id: str) -> InstalledApplication:
    return _installed_application(
        prime_release_application(application_id), _resource_root()
    )


def prime_ipython_coding_application() -> InstalledApplication:
    """Return the exact P1 application record.

    P1's operator composes itself from this record instead of looking itself up
    in the published list. Running an application must not depend on whether it
    is advertised: if it does, the installed-route witness can only be produced
    after publication while publication is gated on that same witness, and the
    application's own route tests cannot build a fixture at all. The record is
    also published by :func:`create_provider` now that the witness has passed.
    """

    return _declared_application("prime.ipython-coding")


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

    return _declared_application("prime.programmatic-long-context")


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

    return _declared_application("prime.long-session-continuity")


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

    return _declared_application("prime.recursive-workflow")


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


def prime_bounded_autonomy_application() -> InstalledApplication:
    """Return the exact P5 application record.

    Mirrors :func:`prime_recursive_workflow_application`: P5's
    operator composes itself from this record instead of looking itself up
    in the published list. The selector stays unpublished until the
    installed-route witness passes (Phase 8, Task 16).
    """

    return _declared_application("prime.bounded-autonomy")


def create_prime_bounded_autonomy_provider() -> InstalledApplicationProvider:
    """Return the provider carrying P5's own record alone.

    See :func:`prime_bounded_autonomy_application` for why the
    P5 operator composes itself from this provider rather than from the
    public :func:`create_provider`.
    """

    return InstalledApplicationProvider(
        protocol=APPLICATION_PROVIDER_PROTOCOL,
        provider_id="prime-applications",
        resource_root=_resource_root(),
        applications=(prime_bounded_autonomy_application(),),
        runtime_factory_bindings=(asterion_prime_runtime_binding(),),
    )


def prime_continual_improvement_application() -> InstalledApplication:
    """Return the exact P6 application record.

    Mirrors :func:`prime_bounded_autonomy_application`: P6's
    operator composes itself from this record instead of looking itself up
    in the published list. The selector stays unpublished until the
    installed-route witness passes (Phase 9, Task 16).
    """

    return _declared_application("prime.continual-improvement")


def create_prime_continual_improvement_provider() -> InstalledApplicationProvider:
    """Return the provider carrying P6's own record alone.

    See :func:`prime_continual_improvement_application` for why the
    P6 operator composes itself from this provider rather than from the
    public :func:`create_provider`. The public :func:`create_provider`
    still returns the six Phase 8 apps (P7 + P1 + P2 + P3 + P4 + P5)
    until the witness passes (Phase 9, Task 16).
    """

    return InstalledApplicationProvider(
        protocol=APPLICATION_PROVIDER_PROTOCOL,
        provider_id="prime-applications",
        resource_root=_resource_root(),
        applications=(prime_continual_improvement_application(),),
        runtime_factory_bindings=(asterion_prime_runtime_binding(),),
    )


def create_provider() -> InstalledApplicationProvider:
    """Return sorted native Prime applications and one peer runtime binding.

    P2 is published together with its installed-route witness (Phase 5,
    Task 4): exit 0 + sealed receipt ``cac924edc5e12b9cb5d1d88e17ac547bd82ac00328dbab74de5157cc7217e0e5``
    from ``make asterion-prime-p2-run``. P4 is published together with its
    cross-generation continuity witness (Phase 6, Task 17): exit 0 + sealed
    receipt ``6b5a173d16d1d1a5382456284a7bbde1b0516120f13c1e9e4572e5f367757a0d``
    from ``make asterion-prime-p4-run``. P3 is published together with its
    recursive-workflow depth + limits witness (Phase 7, Task 16): exit 0
    from both ``make asterion-prime-p3-run`` and
    ``make asterion-prime-p3-run-limits`` (depth-exceeded /
    concurrency-exceeded / budget-exceeded / cancelled refusals each with
    a sealed ``receipt_sha256``). P5 is published together with its
    bounded-autonomy propose/verify/repair + limits witness (Phase 8,
    Task 16): exit 0 from both ``make asterion-prime-p5-run`` and
    ``make asterion-prime-p5-run-limits`` (iteration-cap-exceeded /
    duration-cap-exceeded / no-progress refusals each with a sealed
    ``receipt_sha256``). The selector returns the exact application
    records those operators compose from via
    :func:`create_prime_programmatic_long_context_provider`,
    :func:`create_prime_long_session_continuity_provider`,
    :func:`create_prime_recursive_workflow_provider`, and
    :func:`create_prime_bounded_autonomy_provider`.
    """

    root = _resource_root()
    return InstalledApplicationProvider(
        protocol=APPLICATION_PROVIDER_PROTOCOL,
        provider_id="prime-applications",
        resource_root=root,
        applications=tuple(
            _installed_application(item, root)
            for item in PRIME_RELEASE_INVENTORY
        ),
        runtime_factory_bindings=(asterion_prime_runtime_binding(),),
    )


__all__ = (
    "create_prime_bounded_autonomy_provider",
    "create_prime_continual_improvement_provider",
    "create_prime_ipython_coding_provider",
    "create_prime_long_session_continuity_provider",
    "create_prime_programmatic_long_context_provider",
    "create_prime_recursive_workflow_provider",
    "create_provider",
    "prime_bounded_autonomy_application",
    "prime_continual_improvement_application",
    "prime_ipython_coding_application",
    "prime_long_session_continuity_application",
    "prime_programmatic_long_context_application",
    "prime_recursive_workflow_application",
)
