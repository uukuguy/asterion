"""Metadata-only installed application provider for the Prime program."""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from dataclasses import dataclass
from typing import Literal, Protocol

from asterion.applications.provider import (
    APPLICATION_PROVIDER_PROTOCOL,
    InstalledApplication,
    InstalledApplicationProvider,
)
from asterion.capability_packages import CapabilityPackageRef
from asterion.applications.prime_agent.operator.arc_agi_3_worker import ArcAgi3Worker
from asterion.applications.prime_agent.operator.restricted_scenario_worker import (
    RestrictedScenarioEngine,
)
from asterion.applications.prime_agent.restricted_worker import (
    PrimeRestrictedWorkerProfile,
)
from asterion.applications.prime_agent.preflight import prime_preflight
from asterion.applications.prime_agent.product import create_prime_product
from asterion.applications.prime_agent.source_lock import PrimeSourceLock
from asterion.applications.prime_agent.runtime_binding import prime_runtime_binding


class ArcAgi3WorkerFactory(Protocol):
    def __call__(self, *, engine: RestrictedScenarioEngine) -> ArcAgi3Worker: ...


@dataclass(frozen=True, repr=False)
class ArcAgi3WorkerPreflight:
    status: Literal["PASS", "worker-invalid", "worker-unavailable", "source-invalid"]
    factory: ArcAgi3WorkerFactory | None


def preflight_arc_agi_3_worker_factory(
    *,
    profile: PrimeRestrictedWorkerProfile | None,
    expected_source_lock: PrimeSourceLock,
    source_root: Path,
) -> ArcAgi3WorkerPreflight:
    """Return P7's inert fixed worker factory only after provider-free preflight."""
    result = prime_preflight(profile, expected_source_lock, source_root)
    if result.status != "PASS" or profile is None:
        return ArcAgi3WorkerPreflight(result.status, None)
    if profile.max_runtime_seconds != 300 or profile.max_output_bytes != 4096:
        return ArcAgi3WorkerPreflight("worker-invalid", None)
    image_digest = profile.image_digest

    def factory(*, engine: RestrictedScenarioEngine) -> ArcAgi3Worker:
        return ArcAgi3Worker(image_digest=image_digest, engine=engine)

    return ArcAgi3WorkerPreflight("PASS", factory)


def create_provider() -> InstalledApplicationProvider:
    """Return the Prime capability-program metadata binding."""

    root = Path(str(resources.files("asterion"))).resolve()
    return InstalledApplicationProvider(
        protocol=APPLICATION_PROVIDER_PROTOCOL,
        provider_id="prime-agent",
        resource_root=root,
        applications=(
            InstalledApplication(
                application_id="prime.arc-agi-3",
                version="1.0.0",
                assembly_paths=(
                    root / "applications/prime_agent/assemblies/prime-arc-agi-3.json",
                ),
                capability_packages=(CapabilityPackageRef("prime-agent", "1.0.0"),),
                runtime_ids=("prime.agent",),
            ),
            InstalledApplication(
                application_id="prime.capability-program",
                version="1.0.0",
                assembly_paths=(
                    root
                    / "applications/prime_agent/assemblies/prime-capability-program.json",
                ),
                capability_packages=(CapabilityPackageRef("prime-agent", "1.0.0"),),
                runtime_ids=("prime.agent",),
            ),
            InstalledApplication(
                application_id="prime.bounded-autonomy",
                version="1.0.0",
                assembly_paths=(
                    root
                    / "applications/prime_agent/assemblies/prime-bounded-autonomy.json",
                ),
                capability_packages=(CapabilityPackageRef("prime-agent", "1.0.0"),),
                runtime_ids=("prime.agent",),
            ),
            InstalledApplication(
                application_id="prime.continual-improvement",
                version="1.0.0",
                assembly_paths=(
                    root
                    / "applications/prime_agent/assemblies/prime-continual-improvement.json",
                ),
                capability_packages=(CapabilityPackageRef("prime-agent", "1.0.0"),),
                runtime_ids=("prime.agent",),
            ),
            InstalledApplication(
                application_id="prime.ipython-coding",
                version="1.0.0",
                assembly_paths=(
                    root
                    / "applications/prime_agent/assemblies/prime-ipython-coding.json",
                ),
                capability_packages=(CapabilityPackageRef("prime-agent", "1.0.0"),),
                runtime_ids=("prime.agent",),
            ),
            InstalledApplication(
                application_id="prime.long-session-continuity",
                version="1.0.0",
                assembly_paths=(
                    root
                    / "applications/prime_agent/assemblies/prime-long-session-continuity.json",
                ),
                capability_packages=(CapabilityPackageRef("prime-agent", "1.0.0"),),
                runtime_ids=("prime.agent",),
            ),
            InstalledApplication(
                application_id="prime.programmatic-long-context",
                version="1.0.0",
                assembly_paths=(
                    root
                    / "applications/prime_agent/assemblies/prime-programmatic-long-context.json",
                ),
                capability_packages=(CapabilityPackageRef("prime-agent", "1.0.0"),),
                runtime_ids=("prime.agent",),
            ),
            InstalledApplication(
                application_id="prime.recursive-workflow",
                version="1.0.0",
                assembly_paths=(
                    root
                    / "applications/prime_agent/assemblies/prime-recursive-workflow.json",
                ),
                capability_packages=(CapabilityPackageRef("prime-agent", "1.0.0"),),
                runtime_ids=("prime.agent",),
            ),
        ),
        product=create_prime_product(),
        runtime_factory_bindings=(prime_runtime_binding(),),
    )
