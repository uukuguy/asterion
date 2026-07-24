"""Explicit composition root for the Asterion DCI research application."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from asterion.assembly.protocol import resolve_assembly
from asterion.packages.catalog import PackageRef, discover_packages
from asterion.runner.application import ApplicationRunResult
from asterion.runner.composed import run_composed_application
from asterion.runtime.host import AgentRuntimeClient, CancellationSignal
from asterion.capabilities.dci_research import DciLocalResearchImplementation


async def run_dci_research_application(
    *,
    assembly_path: Path,
    catalog_roots: Iterable[Path],
    runtime: AgentRuntimeClient,
    run_id: str,
    input_text: str,
    signal: CancellationSignal | None = None,
) -> ApplicationRunResult:
    """Resolve and run DCI research through explicit implementation binding."""

    assembly = json.loads(Path(assembly_path).read_text())
    if not isinstance(assembly, dict):
        raise ValueError("DCI research assembly must be an object")
    plan = resolve_assembly(
        assembly,
        catalog=discover_packages(catalog_roots),
        runtime_manifest=runtime.manifest.to_mapping(),
    )
    return await run_composed_application(
        plan,
        implementations=(
            (
                PackageRef("dci.research", "1.0.0"),
                DciLocalResearchImplementation(),
            ),
        ),
        runtime=runtime,
        run_id=run_id,
        input_text=input_text,
        host_services={},
        signal=signal,
    )
