from __future__ import annotations

import json
import unittest
from collections.abc import AsyncIterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from asterion.packages.catalog import PackageRef
from asterion.packages.execution import PackageExecutionError, PackageInvocation
from asterion.runtime.host import RunEvent, RunRequest, RuntimeManifest
from asterion.runtime.working_directory import ProcessWorkingDirectory
from asterion.capabilities.dci_research import DciLocalResearchImplementation


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


class FixtureCorpusService:
    root = PROJECT
    directory_path = PROJECT
    identity_sha256 = "a" * 64

    @contextmanager
    def open_process_working_directory(self):
        yield ProcessWorkingDirectory(
            identity_path=PROJECT,
            cwd=str(PROJECT),
            pass_fds=(),
        )


def invocation(
    runtime: FixtureRuntime,
    *,
    signal: object | None = None,
    host_services: dict[str, object] | None = None,
):
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
        host_services=(
            {"corpus.local-root": FixtureCorpusService()}
            if host_services is None
            else host_services
        ),
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

    async def test_missing_corpus_service_fails_before_runtime_invocation(
        self,
    ) -> None:
        runtime = FixtureRuntime()

        with self.assertRaises(PackageExecutionError) as raised:
            await DciLocalResearchImplementation().execute(
                invocation(runtime, host_services={})
            )

        self.assertEqual(runtime.requests, [])
        self.assertNotIn("SECRET", str(raised.exception))

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

    async def test_pi_invocation_uses_exactly_the_selected_runtime(self) -> None:
        runtime = FixtureRuntime("pi.reference")

        with (
            patch(
                "asterion.dci.application_executor.EnvironmentDciRunExecutor.run",
                side_effect=AssertionError("native bypass"),
            ),
            patch.object(Path, "cwd", side_effect=AssertionError("cwd access")),
        ):
            result = await DciLocalResearchImplementation().execute(invocation(runtime))

        self.assertEqual(len(runtime.requests), 1)
        self.assertEqual(runtime.requests[0].run_id, "research-run")
        self.assertEqual(runtime.requests[0].input_text, "SECRET-APPLICATION-INPUT")
        self.assertEqual(
            result.artifacts[0]["value"]["answer_artifact_uri"], "final.txt"
        )


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
