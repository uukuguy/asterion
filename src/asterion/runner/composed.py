"""Execute resolved package implementations in deterministic order."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from asterion.assembly.protocol import AssemblyPlan
from asterion.packages.catalog import PackageRef
from asterion.packages.execution import (
    EXECUTABLE_PACKAGE_KINDS,
    PackageExecutionError,
    PackageImplementation,
    PackageInvocation,
    validate_implementation_bindings,
    validate_package_result,
)
from asterion.runner.application import (
    ApplicationRunError,
    ApplicationRunResult,
)
from asterion.runtime.host import (
    AgentRuntimeClient,
    CancellationSignal,
    RunRequest,
)
from asterion.runtime.protocol import ProtocolError


async def run_composed_application(
    plan: AssemblyPlan,
    *,
    implementations: Iterable[tuple[PackageRef, PackageImplementation]],
    runtime: AgentRuntimeClient,
    run_id: str,
    input_text: str,
    host_services: Mapping[str, object],
    signal: CancellationSignal | None = None,
) -> ApplicationRunResult:
    """Run explicitly bound package implementations sequentially."""

    _preflight(
        plan,
        runtime=runtime,
        run_id=run_id,
        input_text=input_text,
        host_services=host_services,
        signal=signal,
    )
    try:
        bindings = validate_implementation_bindings(plan, implementations)
    except PackageExecutionError:
        raise ApplicationRunError("application package binding is invalid") from None

    events: list[Mapping[str, object]] = []
    artifacts: list[Mapping[str, object]] = []
    for manifest in plan.package_manifests:
        if manifest["kind"] not in EXECUTABLE_PACKAGE_KINDS:
            continue
        if signal is not None and signal.cancelled:
            raise ApplicationRunError("application package execution was cancelled")
        package_ref = PackageRef(
            str(manifest["package_id"]), str(manifest["version"])
        )
        consumed = manifest["consumes_artifacts"]
        assert isinstance(consumed, tuple)
        upstream = tuple(
            artifact
            for artifact in artifacts
            if artifact.get("media_type") in consumed
        )
        invocation = PackageInvocation(
            package_ref=package_ref,
            manifest=manifest,
            run_id=run_id,
            input_text=input_text,
            upstream_artifacts=upstream,
            runtime=runtime,
            host_services=host_services,
            signal=signal,
        )
        try:
            result = await bindings[package_ref].execute(invocation)
            validate_package_result(manifest, result)
        except Exception:
            raise ApplicationRunError("application package execution failed") from None
        events.extend(result.events)
        artifacts.extend(result.artifacts)

    return ApplicationRunResult(
        application_id=plan.application_id,
        runtime_id=plan.runtime_id,
        run_id=run_id,
        events=tuple(events),
        artifacts=tuple(artifacts),
    )


def _preflight(
    plan: AssemblyPlan,
    *,
    runtime: AgentRuntimeClient,
    run_id: str,
    input_text: str,
    host_services: Mapping[str, object],
    signal: CancellationSignal | None,
) -> None:
    if runtime.manifest.runtime_id != plan.runtime_id:
        raise ApplicationRunError("application runtime identity does not match")
    if any(
        capability not in runtime.manifest.capabilities
        for capability in plan.runtime_capabilities
    ):
        raise ApplicationRunError("application runtime capability is unavailable")
    if any(capability not in host_services for capability in plan.host_capabilities):
        raise ApplicationRunError("application host service is unavailable")
    if signal is not None and signal.cancelled:
        raise ApplicationRunError("application run was cancelled before invocation")
    try:
        RunRequest(run_id=run_id, input_text=input_text).to_mapping()
    except (ProtocolError, TypeError, ValueError):
        raise ApplicationRunError("application request is invalid") from None
