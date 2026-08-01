from __future__ import annotations

import hashlib
import json
import unittest
from collections.abc import AsyncIterator

from asterion.runtime.host import RunEvent, RunRequest, RuntimeManifest
from asterion.workflow_evidence import ObservedRuntimeClient


class CompletedRuntime:
    manifest = RuntimeManifest(runtime_id="fixture.runtime", capabilities=())

    async def run(
        self,
        request: RunRequest,
        *,
        signal: object | None = None,
    ) -> AsyncIterator[RunEvent]:
        del signal
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
                    "uri": "file:///private/SENTINEL_ARTIFACT",
                    "sha256": "b" * 64,
                }
            },
        )
        yield RunEvent(
            request.run_id,
            3,
            "usage.reported",
            {"input_tokens": 3, "output_tokens": 5},
        )
        yield RunEvent(request.run_id, 4, "run.completed", {"status": "completed"})


class FailingRuntime:
    manifest = RuntimeManifest(runtime_id="fixture.runtime", capabilities=())

    async def run(
        self,
        request: RunRequest,
        *,
        signal: object | None = None,
    ) -> AsyncIterator[RunEvent]:
        del request, signal
        raise RuntimeError("SENTINEL_PRIVATE_FAILURE")
        yield RunEvent("unreachable", 1, "run.started", {})


class WorkflowEvidenceRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_records_a_validated_runtime_stream_without_input_or_uri(self) -> None:
        observed = ObservedRuntimeClient(CompletedRuntime())

        events = [
            event
            async for event in observed.run(
                RunRequest(run_id="run-1", input_text="SENTINEL_SECRET_INPUT")
            )
        ]

        self.assertEqual(events[-1].type, "run.completed")
        self.assertEqual(observed.manifest.runtime_id, "fixture.runtime")
        self.assertEqual(len(observed.records), 1)
        record = observed.records[0]
        self.assertEqual(record["schema"], "asterion.workflow-evidence/v1")
        self.assertEqual(record["run_id"], "run-1")
        self.assertEqual(
            record["input_digest"],
            hashlib.sha256(b"SENTINEL_SECRET_INPUT").hexdigest(),
        )
        rendered = json.dumps(dict(record), sort_keys=True)
        self.assertNotIn("SENTINEL_SECRET_INPUT", rendered)
        self.assertNotIn("SENTINEL_ARTIFACT", rendered)

    async def test_records_fixed_failure_class_without_exception_text(self) -> None:
        observed = ObservedRuntimeClient(FailingRuntime())

        with self.assertRaises(RuntimeError):
            _ = [
                event
                async for event in observed.run(
                    RunRequest(run_id="run-2", input_text="SENTINEL_SECRET_INPUT")
                )
            ]

        self.assertEqual(observed.records, ())
        self.assertEqual(observed.failed_attempts, (
            {
                "schema": "asterion.workflow-observation/v1",
                "run_id": "run-2",
                "input_digest": hashlib.sha256(b"SENTINEL_SECRET_INPUT").hexdigest(),
                "status": "failed",
                "failure_class": "runtime-invocation-failed",
            },
        ))
        self.assertNotIn(
            "SENTINEL_PRIVATE_FAILURE",
            json.dumps([dict(item) for item in observed.failed_attempts]),
        )


if __name__ == "__main__":
    unittest.main()
