"""Metadata-only provider for native Asterion-prime applications."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from asterion.applications.first_party_packages import (
    PRIME_ARC_AGI_3_SOLVER_PACKAGE,
    PRIME_BOUNDED_AUTONOMY_NATIVE_PACKAGE,
    PRIME_CONTINUAL_IMPROVEMENT_NATIVE_PACKAGE,
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


def prime_bounded_autonomy_application() -> InstalledApplication:
    """Return the exact P5 application record.

    Mirrors :func:`prime_recursive_workflow_application`: P5's
    operator composes itself from this record instead of looking itself up
    in the published list. The selector stays unpublished until the
    installed-route witness passes (Phase 8, Task 16).
    """

    root = _resource_root()
    return InstalledApplication(
        application_id="prime.bounded-autonomy",
        version="1.0.0",
        assembly_paths=(
            root / "applications/prime/assemblies/prime-bounded-autonomy.json",
        ),
        capability_packages=(PRIME_BOUNDED_AUTONOMY_NATIVE_PACKAGE,),
        runtime_ids=("asterion.prime",),
    )


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

    root = _resource_root()
    return InstalledApplication(
        application_id="prime.continual-improvement",
        version="1.0.0",
        assembly_paths=(
            root / "applications/prime/assemblies/prime-continual-improvement.json",
        ),
        capability_packages=(PRIME_CONTINUAL_IMPROVEMENT_NATIVE_PACKAGE,),
        runtime_ids=("asterion.prime",),
    )


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
            # Phase 8, Task 16: published together with its installed-route
            # bounded-autonomy propose/verify/repair + limits witness (exit 0
            # from both ``make asterion-prime-p5-run`` and
            # ``make asterion-prime-p5-run-limits``; the limits witness
            # asserts iteration-cap-exceeded / duration-cap-exceeded /
            # no-progress refusals, each with a sealed ``receipt_sha256``).
            # The success witness asserts ``propose == 1``,
            # ``verify == 2``, ``repair == 1``, and ``terminal_reason ==
            # "success"`` over canonical-JSON of the bounded-turn transcript
            # (Phase 8: P5NativeOracle + P5NativeReceipt with sealed
            # ``receipt_sha256`` over canonical-JSON of the bounded turn).
            prime_bounded_autonomy_application(),
            # Phase 9, Task 16: published together with its installed-route
            # continual-improvement preserved + limits witness (exit 0 from
            # both ``make asterion-prime-p6-run`` and
            # ``make asterion-prime-p6-run-limits``; the limits witness
            # asserts rolled-back + global-rejected records, each with a
            # sealed ``receipt_sha256``). The preserved witness asserts
            # ``terminal_outcome == "preserved"``,
            # ``global_activation_approved == false``, ``rollback_invocation_count == 0``,
            # and a non-null ``task_b_result_digest`` over canonical-JSON of
            # the holdout evidence (Phase 9: P6NativeReceipt with closed
            # 2-element ``terminal_outcome`` enum + 10th ``failure_digest`` field;
            # D-2026-09-19-02: prime.candidate-store wraps framework-owned
            # HarnessCoordinator at src/asterion/control/harness.py:543).
            prime_continual_improvement_application(),
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
            # Phase 7, Task 16: published together with its recursive-workflow
            # depth + limits witness (exit 0 from both
            # ``make asterion-prime-p3-run`` and
            # ``make asterion-prime-p3-run-limits``; the limits witness
            # asserts depth-exceeded / concurrency-exceeded / budget-exceeded
            # / cancelled refusals, each with a sealed ``receipt_sha256``).
            # The depth witness asserts ``depth_reached == 2``,
            # ``child_generation == root_generation + 1``,
            # ``child_result_sha256 != root_result_sha256``, and a non-null
            # ``joined_result_sha256`` over canonical-JSON of the root+child
            # result pair (D-2026-09-18-02: in-process child session factory).
            prime_recursive_workflow_application(),
            # Phase 5, Task 4: published together with its installed-route
            # witness (``cac924edc5e12b9cb5d1d88e17ac547bd82ac00328dbab74de5157cc7217e0e5``).
            prime_programmatic_long_context_application(),
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
