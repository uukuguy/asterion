from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from asterion.applications.dci_agent_lite.benchmark_executor import (
    LocalDciBenchmarkExecutor,
)
from asterion.benchmarks import BenchmarkTaskInvocation
from asterion.capabilities.dci.implementation.benchmark_bindings import (
    DciBenchmarkInvocationPayload,
)


class MutableCancellation:
    def __init__(self, cancelled: bool = False) -> None:
        self.cancelled = cancelled


class LocalDciBenchmarkExecutorTests(unittest.TestCase):
    def test_completes_exact_cases_without_reading_private_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            invocation = BenchmarkTaskInvocation(
                task_id="qa.bamboogle.github-sample50",
                binding_id="qa.bamboogle.github-sample50",
                public_arguments=("qa.bamboogle", "github-sample50", "limit-1"),
                private_payload=DciBenchmarkInvocationPayload(
                    profile_id="qa.bamboogle",
                    selection_variant="github-sample50",
                    dataset=root / "missing-dataset.jsonl",
                    corpus=root / "missing-corpus",
                    output_directory=root / "output",
                    private_environment={"DCI_TOKEN": "SECRET"},
                    amount=None,
                    case_limit=1,
                    max_concurrency=1,
                    resume_policy="compatible",
                    runtime_context_level=None,
                ),
            )
            progress = []

            result = LocalDciBenchmarkExecutor().execute(
                invocation,
                cancellation=MutableCancellation(),
                on_progress=progress.append,
            )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.case_count, 1)
        self.assertEqual(
            result.artifact_ids,
            ("qa.bamboogle.github-sample50.fixture-result",),
        )
        self.assertEqual(
            tuple(event.status for event in progress),
            ("task.fixture.validated",),
        )
        self.assertNotIn("SECRET", repr(result))

    def test_cancelled_before_work_returns_no_case(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            payload = DciBenchmarkInvocationPayload(
                profile_id="fixture",
                selection_variant="fixture",
                dataset=root / "dataset",
                corpus=root / "corpus",
                output_directory=root / "output",
                private_environment={},
                amount=None,
                case_limit=1,
                max_concurrency=1,
                resume_policy="compatible",
                runtime_context_level=None,
            )
            result = LocalDciBenchmarkExecutor().execute(
                BenchmarkTaskInvocation(
                    task_id="bcplus.level3",
                    binding_id="bcplus.level3",
                    public_arguments=("fixture",),
                    private_payload=payload,
                ),
                cancellation=MutableCancellation(cancelled=True),
                on_progress=lambda event: self.fail(str(event)),
            )

        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.case_count, 0)

    def test_cancellation_after_progress_prevents_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            cancellation = MutableCancellation()
            payload = DciBenchmarkInvocationPayload(
                profile_id="fixture",
                selection_variant="fixture",
                dataset=root / "dataset",
                corpus=root / "corpus",
                output_directory=root / "output",
                private_environment={},
                amount=None,
                case_limit=1,
                max_concurrency=1,
                resume_policy="compatible",
                runtime_context_level=None,
            )

            result = LocalDciBenchmarkExecutor().execute(
                BenchmarkTaskInvocation(
                    task_id="bcplus.level3",
                    binding_id="bcplus.level3",
                    public_arguments=("fixture",),
                    private_payload=payload,
                ),
                cancellation=cancellation,
                on_progress=lambda event: setattr(
                    cancellation,
                    "cancelled",
                    event.status == "task.fixture.validated",
                ),
            )

        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.case_count, 0)


if __name__ == "__main__":
    unittest.main()
