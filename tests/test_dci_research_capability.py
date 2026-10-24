from __future__ import annotations

import json
import unittest
from collections.abc import AsyncIterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from asterion.capabilities.catalog import CapabilityRef
from asterion.capabilities.execution import (
    CapabilityExecutionError,
    CapabilityInvocation,
)
from asterion.runtime.host import RunEvent, RunRequest, RuntimeManifest
from asterion.runtime.working_directory import ProcessWorkingDirectory
from asterion.capabilities.dci.implementation.implementation import (
    DciLocalResearchImplementation,
)
from asterion.capabilities.dci.implementation._runtime import (
    RuntimeEventError,
    event_mappings,
)


PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "src/asterion"
MANIFEST_PATH = SOURCE / "capabilities/dci/payload/capabilities/dci-research.json"


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
        yield RunEvent(
            request.run_id,
            3,
            "artifact.created",
            {
                "artifact": {
                    "artifact_id": "locations",
                    "kind": "locations",
                    "media_type": "text/plain",
                    "uri": "doc.txt",
                }
            },
        )
        yield RunEvent(
            request.run_id,
            4,
            "artifact.created",
            {
                "artifact": {
                    "artifact_id": "trajectory",
                    "kind": "trajectory",
                    "media_type": "text/plain",
                    "uri": "bash",
                }
            },
        )
        yield RunEvent(request.run_id, 5, "run.completed", {"status": "completed"})


class ToolStreamRuntime(FixtureRuntime):
    def __init__(
        self,
        tools: tuple[tuple[str, dict[str, object], object, bool], ...],
        *,
        labeled: tuple[tuple[str, str], ...] = (),
    ) -> None:
        super().__init__()
        self.tools = tools
        self.labeled = labeled

    async def run(
        self,
        request: RunRequest,
        *,
        signal: object | None = None,
    ) -> AsyncIterator[RunEvent]:
        self.requests.append(request)
        self.signals.append(signal)
        sequence = 1
        yield RunEvent(request.run_id, sequence, "run.started", {"capabilities": []})
        for index, (name, arguments, output, is_error) in enumerate(
            self.tools, start=1
        ):
            call_id = f"c{index}"
            sequence += 1
            yield RunEvent(
                request.run_id,
                sequence,
                "tool.call",
                {"call_id": call_id, "name": name, "arguments": arguments},
            )
            sequence += 1
            yield RunEvent(
                request.run_id,
                sequence,
                "tool.result",
                {"call_id": call_id, "output": output, "is_error": is_error},
            )
        sequence += 1
        yield RunEvent(
            request.run_id,
            sequence,
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
        for kind, uri in self.labeled:
            sequence += 1
            yield RunEvent(
                request.run_id,
                sequence,
                "artifact.created",
                {
                    "artifact": {
                        "artifact_id": kind,
                        "kind": kind,
                        "media_type": "text/plain",
                        "uri": uri,
                    }
                },
            )
        sequence += 1
        yield RunEvent(
            request.run_id, sequence, "run.completed", {"status": "completed"}
        )


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
    return CapabilityInvocation(
        capability_ref=CapabilityRef("dci.research", "1.0.0"),
        manifest=json.loads(MANIFEST_PATH.read_text()),
        run_id="research-run",
        input_text="SECRET-APPLICATION-INPUT",
        upstream_artifacts=(
            {
                "artifact_id": "question",
                "media_type": "text/plain",
                "value": {"text": "Read the corpus"},
            },
        ),
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
            ("filesystem.read", "shell"),
        )
        self.assertIs(runtime.signals[0], signal)
        self.assertEqual(result.events[0]["type"], "research.completed")
        self.assertEqual(
            [artifact["media_type"] for artifact in result.artifacts],
            [
                "application/vnd.dci.research.answer+json",
                "application/vnd.dci.research.locations+json",
                "application/vnd.dci.research.trajectory+json",
            ],
        )
        self.assertEqual(
            result.artifacts[0]["value"]["answer_artifact_uri"], "final.txt"
        )
        self.assertEqual(result.artifacts[1]["value"]["paths"], ("doc.txt",))
        self.assertEqual(result.artifacts[2]["value"]["calls"], ("bash",))

    async def test_launched_tools_supply_locations_and_trajectory(self) -> None:
        runtime = ToolStreamRuntime(
            (
                ("read", {"path": "doc.txt"}, "SECRET-TOOL-OUTPUT", False),
                ("grep", {"pattern": "clause"}, "SECRET-GREP-OUTPUT", False),
                (
                    "grep",
                    {"path": "notes/a.md", "pattern": "clause"},
                    "SECRET-GREP-FILE",
                    False,
                ),
                (
                    "bash",
                    {"command": "cat /Users/sujiangwen/secret"},
                    "SECRET-BASH",
                    False,
                ),
                ("Read", {"file": "other.md"}, "SECRET-READ", False),
            ),
            labeled=(("locations", "ignored.txt"), ("trajectory", "ignored")),
        )

        result = await DciLocalResearchImplementation().execute(invocation(runtime))

        self.assertEqual(
            result.artifacts[1]["value"]["paths"],
            ("doc.txt", ".", "notes/a.md", "other.md"),
        )
        self.assertEqual(
            result.artifacts[2]["value"]["calls"],
            ("read", "grep", "grep", "bash", "Read"),
        )
        self.assertEqual(
            result.artifacts[0]["value"]["answer_artifact_uri"], "final.txt"
        )
        rendered = repr(result)
        for secret in (
            "SECRET-TOOL-OUTPUT",
            "SECRET-GREP-OUTPUT",
            "SECRET-GREP-FILE",
            "SECRET-BASH",
            "SECRET-READ",
            "/Users/sujiangwen/secret",
            "ignored.txt",
            "cat ",
        ):
            self.assertNotIn(secret, rendered)

    async def test_errored_read_still_records_its_location(self) -> None:
        runtime = ToolStreamRuntime(
            (("read", {"file_path": "doc.txt"}, "SECRET-ERR", True),)
        )

        result = await DciLocalResearchImplementation().execute(invocation(runtime))

        self.assertEqual(result.artifacts[1]["value"]["paths"], ("doc.txt",))
        self.assertEqual(result.artifacts[2]["value"]["calls"], ("read",))
        self.assertNotIn("SECRET-ERR", repr(result))

    async def test_unsafe_tool_locations_fail_closed(self) -> None:
        cases = (
            ("read", {}),
            ("read", {"path": "/Users/sujiangwen/secret"}),
            ("read", {"path": "../secret"}),
            ("read", {"path": ["SECRET-LIST"]}),
            ("bash", {"command": "ls SECRET-ONLY-BASH"}),
        )
        for name, arguments in cases:
            with self.subTest(name=name, arguments=arguments):
                runtime = ToolStreamRuntime(((name, arguments, "SECRET-OUT", False),))
                with self.assertRaises(CapabilityExecutionError) as raised:
                    await DciLocalResearchImplementation().execute(invocation(runtime))
                message = str(raised.exception)
                self.assertEqual(message, "research runtime execution failed")
                self.assertNotIn("SECRET", message)
                self.assertNotIn("/Users", message)

    async def test_missing_corpus_service_fails_before_runtime_invocation(
        self,
    ) -> None:
        runtime = FixtureRuntime()

        with self.assertRaises(CapabilityExecutionError) as raised:
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
        with self.assertRaises(CapabilityExecutionError) as raised:
            await DciLocalResearchImplementation().execute(invocation(FailingRuntime()))
        message = str(raised.exception)
        self.assertNotIn("SECRET-APPLICATION-INPUT", message)
        self.assertNotIn("SECRET-PROVIDER-PAYLOAD", message)

    async def test_pi_invocation_uses_exactly_the_selected_runtime(self) -> None:
        runtime = FixtureRuntime("pi.reference")

        with (
            patch(
                "asterion.capabilities.dci.implementation.runtime.application_executor.EnvironmentDciRunExecutor.run",
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
    def test_application_and_capability_sources_do_not_import_batch_orchestration(
        self,
    ) -> None:
        roots = (
            SOURCE / "applications",
            SOURCE / "capabilities",
        )
        offenders = tuple(
            path.relative_to(SOURCE).as_posix()
            for root in roots
            if root.exists()
            for path in root.rglob("*.py")
            if (
                "from asterion.capabilities.dci.implementation.evaluation."
                "benchmark import"
            )
            in path.read_text()
        )
        self.assertEqual(
            offenders,
            ("applications/dci_agent_lite/benchmark_executor.py",),
        )

    def test_package_runtime_artifact_event_accepts_only_canonical_keys_and_sha256(
        self,
    ) -> None:
        base_artifact = {
            "artifact_id": "answer",
            "kind": "answer",
            "media_type": "text/plain",
            "uri": "final.txt",
            "sha256": "a" * 64,
        }
        events = (
            {
                "protocol": "asterion.agent-runtime/v1",
                "run_id": "run",
                "sequence": 1,
                "type": "run.started",
                "payload": {"capabilities": []},
            },
            {
                "protocol": "asterion.agent-runtime/v1",
                "run_id": "run",
                "sequence": 2,
                "type": "artifact.created",
                "payload": {"artifact": base_artifact},
            },
            {
                "protocol": "asterion.agent-runtime/v1",
                "run_id": "run",
                "sequence": 3,
                "type": "run.completed",
                "payload": {"status": "completed"},
            },
        )

        self.assertEqual(event_mappings(events), events)

        for artifact in (
            {**base_artifact, "private_path": "/secret"},
            {**base_artifact, "sha256": "A" * 64},
            {**base_artifact, "sha256": "a" * 63},
            {**base_artifact, "uri": ""},
        ):
            with self.subTest(artifact=artifact):
                mutated = (
                    events[0],
                    {**events[1], "payload": {"artifact": artifact}},
                    events[2],
                )
                with self.assertRaises(RuntimeEventError):
                    event_mappings(mutated)


if __name__ == "__main__":
    unittest.main()
