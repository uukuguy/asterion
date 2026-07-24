from __future__ import annotations

import json
import unittest
from collections.abc import AsyncIterator
from pathlib import Path

from asterion.packages.catalog import PackageRef
from asterion.packages.execution import PackageExecutionError, PackageInvocation
from asterion.runtime.host import RunEvent, RunRequest, RuntimeManifest
from asterion.capabilities.dci_research import DciLocalResearchImplementation
from asterion.dci.run import DciRunRequest, DciRunResult


PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "src/asterion"
MANIFEST_PATH = (
    SOURCE / "capabilities/dci_research/manifests/dci-research.json"
)


class FixtureRuntime:
    def __init__(self, runtime_id: str = "pi.reference") -> None:
        self.manifest = RuntimeManifest(
            runtime_id=runtime_id,
            capabilities=("filesystem.read", "shell"),
        )
        self.requests: list[RunRequest] = []
        self.signals: list[object | None] = []

    async def run(
        self,
        request: RunRequest,
        *,
        signal: object | None = None,
    ) -> AsyncIterator[RunEvent]:
        self.requests.append(request)
        self.signals.append(signal)
        yield RunEvent(request.run_id, 1, "run.started", {"capabilities": []})
        yield RunEvent(
            request.run_id,
            2,
            "artifact.created",
            {
                "artifact": {
                    "artifact_id": "answer",
                    "kind": "answer",
                    "media_type": "text/plain",
                    "uri": "final.txt",
                }
            },
        )
        yield RunEvent(request.run_id, 3, "run.completed", {"status": "completed"})


class FailingRuntime(FixtureRuntime):
    async def run(
        self,
        request: RunRequest,
        *,
        signal: object | None = None,
    ) -> AsyncIterator[RunEvent]:
        del request, signal
        if False:
            yield RunEvent("", 0, "", {})
        raise RuntimeError("SECRET-PROVIDER-PAYLOAD")


class RecordingNativeExecutor:
    def __init__(self, result: DciRunResult) -> None:
        self.result = result
        self.requests: list[DciRunRequest] = []

    def run(self, request: DciRunRequest) -> DciRunResult:
        self.requests.append(request)
        return self.result


def invocation(runtime: FixtureRuntime, *, signal: object | None = None):
    return PackageInvocation(
        package_ref=PackageRef("dci.research", "1.0.0"),
        manifest=json.loads(MANIFEST_PATH.read_text()),
        run_id="research-run",
        input_text="SECRET-APPLICATION-INPUT",
        upstream_artifacts=({
            "artifact_id": "question",
            "media_type": "text/plain",
            "value": {"text": "Read the corpus"},
        },),
        runtime=runtime,
        host_services={},
        signal=signal,
    )


class DciResearchCapabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_executes_one_runtime_neutral_research_request(self) -> None:
        runtime = FixtureRuntime()
        signal = object()

        result = await DciLocalResearchImplementation().execute(
            invocation(runtime, signal=signal)
        )

        self.assertEqual(len(runtime.requests), 1)
        self.assertEqual(runtime.requests[0].input_text, "SECRET-APPLICATION-INPUT")
        self.assertEqual(
            runtime.requests[0].requested_capabilities,
            ("filesystem.read",),
        )
        self.assertIs(runtime.signals[0], signal)
        self.assertEqual(result.events[0]["type"], "research.completed")
        self.assertEqual(
            result.artifacts[0]["media_type"],
            "application/vnd.dci.research+json",
        )
        self.assertEqual(
            result.artifacts[0]["value"]["answer_artifact_uri"], "final.txt"
        )

    async def test_pi_and_claude_fixtures_share_the_same_package_behavior(self) -> None:
        results = []
        for runtime_id in ("pi.reference", "claude-code.reference"):
            results.append(
                await DciLocalResearchImplementation().execute(
                    invocation(FixtureRuntime(runtime_id))
                )
            )
        self.assertEqual(results[0], results[1])

    async def test_runtime_failures_are_redacted(self) -> None:
        with self.assertRaises(PackageExecutionError) as raised:
            await DciLocalResearchImplementation().execute(invocation(FailingRuntime()))
        message = str(raised.exception)
        self.assertNotIn("SECRET-APPLICATION-INPUT", message)
        self.assertNotIn("SECRET-PROVIDER-PAYLOAD", message)

    async def test_completed_native_run_uses_the_explicit_projection_seam(self) -> None:
        result = DciRunResult(
            output_dir=Path("run"),
            final_text="SECRET-NATIVE-ANSWER",
            events=(
                RunEvent("run", 1, "run.started", {"capabilities": []}),
                RunEvent(
                    "run",
                    2,
                    "artifact.created",
                    {
                        "artifact": {
                            "artifact_id": "answer",
                            "kind": "answer",
                            "media_type": "text/plain",
                            "uri": "final.txt",
                        }
                    },
                ),
                RunEvent("run", 3, "run.completed", {"status": "completed"}),
            ),
            status="completed",
        )

        projection = DciLocalResearchImplementation().execute_completed_native_run(result)

        self.assertEqual(projection.artifacts[0]["value"]["events_artifact_uri"], "events.jsonl")
        self.assertNotIn("SECRET-NATIVE-ANSWER", repr(projection))

    async def test_pi_invocation_uses_the_bound_native_executor(self) -> None:
        native = RecordingNativeExecutor(
            DciRunResult(
                output_dir=Path("run"),
                final_text="SECRET-NATIVE-ANSWER",
                events=(
                    RunEvent("research-run", 1, "run.started", {"capabilities": []}),
                    RunEvent(
                        "research-run",
                        2,
                        "artifact.created",
                        {
                            "artifact": {
                                "artifact_id": "answer",
                                "kind": "answer",
                                "media_type": "text/plain",
                                "uri": "final.txt",
                            }
                        },
                    ),
                    RunEvent("research-run", 3, "run.completed", {"status": "completed"}),
                ),
                status="completed",
            )
        )
        runtime = FixtureRuntime("pi.reference")

        result = await DciLocalResearchImplementation(native_executor=native).execute(
            invocation(runtime)
        )

        self.assertEqual(runtime.requests, [])
        self.assertEqual(native.requests[0].run_id, "research-run")
        self.assertEqual(native.requests[0].question, "SECRET-APPLICATION-INPUT")
        self.assertEqual(result.artifacts[0]["value"]["state_artifact_uri"], "state.json")
        self.assertNotIn("SECRET-NATIVE-ANSWER", repr(result))


class DciResearchCapabilityBoundaryTests(unittest.TestCase):
    def test_application_and_capability_sources_do_not_import_batch_orchestration(self) -> None:
        roots = (
            SOURCE / "applications",
            SOURCE / "capabilities",
        )
        source = "\n".join(
            path.read_text()
            for root in roots
            if root.exists()
            for path in root.rglob("*.py")
        )
        self.assertNotIn("from asterion.dci.benchmark import", source)


if __name__ == "__main__":
    unittest.main()
