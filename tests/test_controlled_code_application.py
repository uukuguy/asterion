from __future__ import annotations

import json
import unittest
from collections.abc import AsyncIterator
from pathlib import Path

from asterion.assembly.protocol import resolve_assembly
from asterion.capabilities.controlled_code import controlled_code_bindings
from asterion.packages.catalog import discover_packages
from asterion.runner.application import ApplicationRunError
from asterion.runner.composed import run_composed_application
from asterion.runtime.host import RunEvent, RunRequest, RuntimeManifest
from asterion.services.controlled_executor import (
    ControlledExecutionRequest,
    ControlledExecutionResult,
)


PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "src/asterion"
MANIFESTS = SOURCE / "capabilities/controlled_code/manifests"
ASSEMBLY = (
    SOURCE
    / "applications/controlled_code/assemblies/controlled-code-validation.json"
)


class FixtureRuntime:
    manifest = RuntimeManifest(
        runtime_id="pi.reference", capabilities=("filesystem.read",)
    )

    async def run(
        self, request: RunRequest, *, signal: object | None = None
    ) -> AsyncIterator[RunEvent]:
        del request, signal
        if False:
            yield RunEvent("", 0, "", {})


class FixtureExecutor:
    def __init__(self) -> None:
        self.requests: list[ControlledExecutionRequest] = []

    async def execute(self, request, *, signal=None):
        del signal
        self.requests.append(request)
        return ControlledExecutionResult(
            status="succeeded",
            exit_code=0,
            stdout_bytes=21,
            stderr_bytes=0,
            stdout_truncated=False,
            stderr_truncated=False,
            duration_ms=7,
            failure_class=None,
        )


def plan():
    assembly = json.loads(ASSEMBLY.read_text())
    return resolve_assembly(
        assembly,
        catalog=discover_packages((MANIFESTS,)),
        runtime_manifest=FixtureRuntime.manifest.to_mapping(),
    )


class ControlledCodeApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_three_implementations_make_one_executor_call(self) -> None:
        executor = FixtureExecutor()
        result = await run_composed_application(
            plan(),
            implementations=controlled_code_bindings(),
            runtime=FixtureRuntime(),
            run_id="controlled-run",
            input_text="src/example.py",
            host_services={"executor.controlled": executor},
        )

        self.assertEqual(executor.requests, [ControlledExecutionRequest("src/example.py")])
        self.assertEqual(
            [artifact["media_type"] for artifact in result.artifacts],
            [
                "application/vnd.dci.code-quality+json",
                "application/vnd.dci.code-quality-verdict+json",
                "application/vnd.dci.execution-audit+json",
            ],
        )
        self.assertEqual(
            [event["type"] for event in result.events],
            ["workflow.code-quality.completed", "audit.execution-recorded"],
        )

    async def test_missing_service_fails_before_executor_or_package_work(self) -> None:
        with self.assertRaises(ApplicationRunError):
            await run_composed_application(
                plan(),
                implementations=controlled_code_bindings(),
                runtime=FixtureRuntime(),
                run_id="controlled-run",
                input_text="src/example.py",
                host_services={},
            )

    async def test_command_like_or_escaping_input_fails_without_echo(self) -> None:
        executor = FixtureExecutor()
        for value in ("../SECRET.py", "/SECRET.py"):
            with self.subTest(value=value):
                with self.assertRaises(ApplicationRunError) as caught:
                    await run_composed_application(
                        plan(),
                        implementations=controlled_code_bindings(),
                        runtime=FixtureRuntime(),
                        run_id="controlled-run",
                        input_text=value,
                        host_services={"executor.controlled": executor},
                    )
                self.assertNotIn("SECRET", str(caught.exception))
        self.assertEqual(executor.requests, [])


if __name__ == "__main__":
    unittest.main()
