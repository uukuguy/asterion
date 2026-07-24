"""Explicit host composition for the bundled controlled-code application."""

from __future__ import annotations

import json

from asterion.applications.controlled_code import create_provider
from asterion.assembly.protocol import resolve_assembly
from asterion.packages.catalog import discover_packages
from asterion.runner.composed import run_composed_application
from asterion.runtime.host import AgentRuntimeClient, CancellationSignal
from asterion.services.controlled_executor import ControlledExecutorService


async def run_controlled_code_application(
    *,
    runtime: AgentRuntimeClient,
    executor: ControlledExecutorService,
    run_id: str,
    target: str,
    signal: CancellationSignal | None = None,
):
    """Run the exact bundled graph with an explicitly authorized service."""

    provider = create_provider()
    application = provider.applications[0]
    assembly = json.loads(application.assembly_paths[0].read_text())
    plan = resolve_assembly(
        assembly,
        catalog=discover_packages(application.catalog_roots),
        runtime_manifest=runtime.manifest.to_mapping(),
    )
    return await run_composed_application(
        plan,
        implementations=application.implementations,
        runtime=runtime,
        run_id=run_id,
        input_text=target,
        host_services={"executor.controlled": executor},
        signal=signal,
    )
