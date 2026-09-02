"""Installed DCI application closure checks owned by the application adapter."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from asterion.applications.discovery import load_application_provider
from asterion.applications.product import VerificationCheckResult
from asterion.applications.provider import (
    ApplicationProviderError,
    compose_installed_provider,
)
from asterion.capabilities.builtin import (
    create_controlled_code_package,
)
from asterion.capabilities.dci.provider import (
    create_dci_package as create_dci_package_for_source,
)
from asterion.capabilities.catalog import (
    CapabilityCatalogError,
    discover_capabilities,
)
from asterion.capabilities.dci.implementation.reproduction.paper_benchmarks import (
    paper_benchmark_ids,
    paper_benchmark_inventory_sha256,
    paper_experiment_scope_ids,
    paper_experiment_scopes_sha256,
    resolve_paper_benchmark,
    resolve_paper_experiment_scope,
)
from asterion.capabilities.dci.implementation.research.context_profiles import (
    context_profile_names,
    resolve_context_profile,
)
from asterion.capabilities.execution import (
    CapabilityExecutionError,
    validate_implementation_bindings,
)
from asterion.runtime.defaults import default_runtime_factory_registry
from asterion.runtime.factory import RuntimeFactoryError
from asterion.runtime.protocol import ProtocolError


_EXPECTED_PACKAGED_ASSEMBLIES = (
    "applications/controlled_code/assemblies/controlled-code-validation.json",
    "applications/dci_agent_lite/assemblies/"
    "dci-complete-application-claude.json",
    "applications/dci_agent_lite/assemblies/dci-complete-application-pi.json",
    "applications/dci_agent_lite/assemblies/"
    "dci-local-benchmark-application-claude.json",
    "applications/dci_agent_lite/assemblies/"
    "dci-local-benchmark-application-pi.json",
    "applications/dci_agent_lite/assemblies/dci-local-research.json",
    "applications/dci_agent_lite/assemblies/"
    "dci-research-capability-claude.json",
    "applications/dci_agent_lite/assemblies/dci-research-capability.json",
    "applications/prime_agent/assemblies/prime-capability-program.json",
)
_EXPECTED_UNBOUND_ASSEMBLIES = (
    "applications/dci_agent_lite/assemblies/dci-local-research.json",
    "applications/prime_agent/assemblies/prime-capability-program.json",
)
_EXPECTED_BOUND_ASSEMBLIES = tuple(
    identity
    for identity in _EXPECTED_PACKAGED_ASSEMBLIES
    if identity not in _EXPECTED_UNBOUND_ASSEMBLIES
)
_EXPECTED_CONTEXT_PROFILES = ("level0", "level1", "level2", "level3", "level4")
_EXPECTED_PAPER_BENCHMARK_IDS = (
    "beir.arguana",
    "beir.scifact",
    "bright.biology",
    "bright.earth-science",
    "bright.economics",
    "bright.robotics",
    "browsecomp-plus",
    "qa.2wikimultihopqa",
    "qa.bamboogle",
    "qa.hotpotqa",
    "qa.musique",
    "qa.nq",
    "qa.triviaqa",
)
_EXPECTED_PAPER_SCOPE_IDS = (
    "beir.arguana.main.random50",
    "beir.scifact.main.random50",
    "beir.scifact.main.full",
    "bright.biology.main.full",
    "bright.earth-science.main.full",
    "bright.economics.main.full",
    "bright.robotics.main.full",
    "browsecomp-plus.analysis.n100",
    "browsecomp-plus.appendix-a1.random50",
    "browsecomp-plus.context-ablation.random100",
    "browsecomp-plus.main.all830",
    "qa.2wikimultihopqa.main.random50",
    "qa.bamboogle.main.full",
    "qa.hotpotqa.main.random50",
    "qa.musique.main.random50",
    "qa.nq.main.random50",
    "qa.triviaqa.main.random50",
)
_EXPECTED_PAPER_BENCHMARK_SHA256 = (
    "bfe279f25452b37eab5ffd33f39e4ee405c2f9c8226c6456eea33c3d0c8191af"
)
_EXPECTED_PAPER_SCOPES_SHA256 = (
    "862c8fc711962f507c1f57bec00b68028047f3cd51ac95818ed8f1868077be13"
)


def create_dci_package():
    """Load the exact packaged DCI built-in selected by acceptance."""

    root = Path(str(resources.files("asterion.capabilities.dci"))).resolve()
    return create_dci_package_for_source(
        payload_root=root / "payload",
        source_id="dci.builtin",
        source_kind="builtin",
    )


def _acceptance_check(
    check_id: str,
    summary: str,
    *,
    actual: int,
    expected: int,
    exact: bool = True,
    unbound_resources: tuple[str, ...] = (),
) -> VerificationCheckResult:
    passed = actual == expected and exact
    return VerificationCheckResult(
        check_id=check_id,
        summary=summary if passed else f"{summary} is invalid",
        status="PASS" if passed else "FAIL",
        counts=(("actual", actual), ("expected", expected)),
        unbound_resources=unbound_resources,
    )


def installed_acceptance_checks() -> tuple[VerificationCheckResult, ...]:
    """Validate the exact installed provider and packaged-resource closure."""

    controlled_package = create_controlled_code_package()
    dci_package = create_dci_package()
    providers = (
        load_application_provider("controlled-code"),
        load_application_provider("dci-agent-lite"),
    )
    installed_packages_by_provider = {
        "controlled-code": (controlled_package,),
        "dci-agent-lite": (dci_package,),
    }
    installed_packages = (controlled_package, dci_package)
    applications = tuple(
        application
        for provider in providers
        for application in provider.applications
    )
    package_root = Path(str(resources.files("asterion"))).resolve()

    def package_identity(path: Path) -> str | None:
        if path.is_symlink():
            return None
        try:
            relative = path.resolve(strict=True).relative_to(package_root)
        except (OSError, ValueError):
            return None
        identity = relative.as_posix()
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not identity.startswith("applications/")
        ):
            return None
        return identity

    bound_assemblies = tuple(
        sorted(
            identity
            for application in applications
            for path in application.assembly_paths
            if (identity := package_identity(path)) is not None
        )
    )

    composed_providers = []
    try:
        runtime_factories = default_runtime_factory_registry()
    except (ProtocolError, RuntimeFactoryError):
        pass
    else:
        for provider in providers:
            try:
                composed_providers.append(
                    compose_installed_provider(
                        provider,
                        runtime_factories=runtime_factories,
                        installed_packages=installed_packages_by_provider[
                            provider.provider_id
                        ],
                    )
                )
            except ApplicationProviderError:
                continue
    composed_assemblies = tuple(
        sorted(
            identity
            for provider in composed_providers
            for application in provider.applications
            for assembly in application.assemblies
            if (identity := package_identity(assembly.path)) is not None
        )
    )

    executable_identities: list[str] = []
    for provider in composed_providers:
        for application in provider.applications:
            for assembly in application.assemblies:
                try:
                    validate_implementation_bindings(
                        assembly.plan, application.implementations
                    )
                except (CapabilityExecutionError, TypeError, ValueError):
                    continue
                identity = package_identity(assembly.path)
                if identity is not None:
                    executable_identities.append(identity)
    executable_assemblies = tuple(sorted(executable_identities))

    catalog_roots = tuple(
        sorted(
            {
                root
                for package in installed_packages
                for root in package.catalog_roots
            }
        )
    )
    try:
        manifests = discover_capabilities(catalog_roots).entries
    except (OSError, TypeError, ValueError, CapabilityCatalogError):
        manifests = ()
    try:
        packaged_assemblies = tuple(
            sorted(
                identity
                for path in (package_root / "applications").glob(
                    "*/assemblies/*.json"
                )
                if (identity := package_identity(path)) is not None
            )
        )
    except OSError:
        packaged_assemblies = ()
    unbound_resources = tuple(
        sorted(set(packaged_assemblies) - set(bound_assemblies))
    )

    try:
        profiles = tuple(context_profile_names())
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        profiles = ()
    profiles_exact = profiles == _EXPECTED_CONTEXT_PROFILES
    if profiles_exact:
        for profile_name in profiles:
            try:
                profile = resolve_context_profile(profile_name)
            except (KeyError, OSError, RuntimeError, TypeError, ValueError):
                profiles_exact = False
                break
            if getattr(profile, "name", None) != profile_name:
                profiles_exact = False
                break

    try:
        datasets = tuple(paper_benchmark_ids())
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        datasets = ()
    datasets_exact = datasets == _EXPECTED_PAPER_BENCHMARK_IDS
    if datasets_exact:
        for dataset_id in datasets:
            try:
                dataset = resolve_paper_benchmark(dataset_id)
            except (KeyError, OSError, RuntimeError, TypeError, ValueError):
                datasets_exact = False
                break
            if getattr(dataset, "dataset_id", None) != dataset_id:
                datasets_exact = False
                break
    try:
        benchmark_sha256 = paper_benchmark_inventory_sha256()
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        benchmark_sha256 = None
    datasets_exact = (
        datasets_exact
        and benchmark_sha256 == _EXPECTED_PAPER_BENCHMARK_SHA256
    )

    try:
        scopes = tuple(paper_experiment_scope_ids())
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        scopes = ()
    scopes_exact = scopes == _EXPECTED_PAPER_SCOPE_IDS
    if scopes_exact:
        for scope_id in scopes:
            try:
                scope = resolve_paper_experiment_scope(scope_id)
            except (KeyError, OSError, RuntimeError, TypeError, ValueError):
                scopes_exact = False
                break
            if getattr(scope, "scope_id", None) != scope_id:
                scopes_exact = False
                break
    try:
        scopes_sha256 = paper_experiment_scopes_sha256()
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        scopes_sha256 = None
    scopes_exact = (
        scopes_exact and scopes_sha256 == _EXPECTED_PAPER_SCOPES_SHA256
    )

    return tuple(
        sorted(
            (
                _acceptance_check(
                    "application-providers",
                    "Installed provider closure is valid",
                    actual=len(providers),
                    expected=2,
                    exact=tuple(provider.provider_id for provider in providers)
                    == ("controlled-code", "dci-agent-lite"),
                ),
                _acceptance_check(
                    "bound-assemblies",
                    "Provider-bound assembly closure is valid",
                    actual=len(bound_assemblies),
                    expected=len(_EXPECTED_BOUND_ASSEMBLIES),
                    exact=bound_assemblies == _EXPECTED_BOUND_ASSEMBLIES,
                ),
                _acceptance_check(
                    "capability-manifests",
                    "Capability manifest closure is valid",
                    actual=len(manifests),
                    expected=11,
                ),
                _acceptance_check(
                    "composed-assemblies",
                    "Resolved assembly composition closure is valid",
                    actual=len(composed_assemblies),
                    expected=len(_EXPECTED_BOUND_ASSEMBLIES),
                    exact=composed_assemblies
                    == _EXPECTED_BOUND_ASSEMBLIES,
                ),
                _acceptance_check(
                    "context-profiles",
                    "Context profile closure is valid",
                    actual=len(profiles),
                    expected=5,
                    exact=profiles_exact,
                ),
                _acceptance_check(
                    "executable-assemblies",
                    "Executable binding closure is valid",
                    actual=len(executable_assemblies),
                    expected=len(_EXPECTED_BOUND_ASSEMBLIES),
                    exact=executable_assemblies
                    == _EXPECTED_BOUND_ASSEMBLIES,
                ),
                _acceptance_check(
                    "packaged-assemblies",
                    "Capabilityd assembly inventory is valid",
                    actual=len(packaged_assemblies),
                    expected=len(_EXPECTED_PACKAGED_ASSEMBLIES),
                    exact=packaged_assemblies
                    == _EXPECTED_PACKAGED_ASSEMBLIES,
                    unbound_resources=unbound_resources,
                ),
                _acceptance_check(
                    "paper-benchmarks",
                    "Paper benchmark identity closure is valid",
                    actual=len(datasets),
                    expected=13,
                    exact=datasets_exact,
                ),
                _acceptance_check(
                    "paper-scopes",
                    "Paper scope identity closure is valid",
                    actual=len(scopes),
                    expected=17,
                    exact=scopes_exact,
                ),
                _acceptance_check(
                    "provider-requests",
                    "Installed acceptance made no provider requests",
                    actual=0,
                    expected=0,
                ),
            ),
            key=lambda check: check.check_id,
        )
    )


__all__ = ("create_dci_package", "installed_acceptance_checks")
