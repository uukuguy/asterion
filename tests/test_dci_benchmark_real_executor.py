from __future__ import annotations

import asyncio
import tempfile
import threading
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from asterion.applications.dci_agent_lite.benchmark_executor import (
    DciBenchmarkExecutorError,
    RealDciBenchmarkExecutor,
)
from asterion.benchmarks import BenchmarkTaskInvocation
from asterion.capabilities.dci.implementation.benchmark_bindings import (
    DciBenchmarkInvocationPayload,
)
from asterion.capabilities.dci.implementation.config import (
    DciPaths,
    DciPiPaths,
    DciRuntimeOptions,
)
from asterion.capabilities.dci.implementation.evaluation.benchmark import (
    BenchmarkResult,
)
from asterion.capabilities.dci.implementation.evaluation.judge import JudgeConfig


class MutableCancellation:
    def __init__(self) -> None:
        self.cancelled = False


def _paths(root: Path) -> DciPaths:
    return DciPaths(
        repo_root=root,
        pi=DciPiPaths(
            repo_dir=root / "pi",
            package_dir=root / "pi" / "packages" / "coding-agent",
            agent_dir=root / "agent",
        ),
        output_root=root / "native-output",
    )


def _invocation(root: Path, **changes: object) -> BenchmarkTaskInvocation:
    task_id = changes.pop("task_id", "qa.bamboogle.github-sample50")
    binding_id = changes.pop("binding_id", task_id)
    values = {
        "profile_id": "qa.bamboogle",
        "selection_variant": "github-sample50",
        "dataset": root / "dataset.jsonl",
        "corpus": root / "corpus",
        "output_directory": root / "output",
        "private_environment": {"DCI_TOKEN": "SENTINEL-SECRET"},
        "amount": None,
        "case_limit": 1,
        "max_concurrency": 1,
        "resume_policy": "compatible",
        "runtime_context_level": "level3",
    }
    values.update(changes)
    return BenchmarkTaskInvocation(
        task_id=task_id,
        binding_id=binding_id,
        public_arguments=("qa.bamboogle", "github-sample50", "limit-1"),
        private_payload=DciBenchmarkInvocationPayload(**values),
    )


class RealDciBenchmarkExecutorTests(unittest.TestCase):
    def test_executes_paper_full125_contract(self) -> None:
        calls = []

        async def runner(request, *, paths):
            calls.append((request, paths))
            return BenchmarkResult(
                output_root=request.output_root,
                counts={"total": 125, "completed": 125, "failed": 0},
            )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / "dataset.jsonl").write_text("{}\n", encoding="utf-8")
            result = RealDciBenchmarkExecutor(
                paths=_paths(root),
                runtime_options=DciRuntimeOptions(),
                judge_config=JudgeConfig(api_key="PRIVATE-JUDGE-KEY"),
                benchmark_runner=runner,
                readiness_probe=lambda *_args: None,
            ).execute(
                _invocation(
                    root,
                    task_id="qa.bamboogle.paper-full125",
                    selection_variant="paper-full125",
                    case_limit=125,
                    amount=Decimal("10"),
                ),
                cancellation=MutableCancellation(),
                on_progress=lambda _event: None,
            )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.case_count, 125)
        self.assertEqual(calls[0][0].limit, 125)
        self.assertEqual(calls[0][0].max_concurrency, 1)
        self.assertIsNotNone(calls[0][0].full_execution_authorization)
        self.assertEqual(
            calls[0][0].experiment_scope_id,
            "qa.bamboogle.main.full",
        )

    def test_translates_bounded_bamboogle_into_existing_engine(self) -> None:
        calls = []

        async def runner(request, *, paths):
            calls.append((request, paths))
            return BenchmarkResult(
                output_root=request.output_root,
                counts={"total": 1, "completed": 1, "failed": 0},
            )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / "dataset.jsonl").write_text(
                '{"id":"one","query":"PRIVATE","answer":"PRIVATE"}\n',
                encoding="utf-8",
            )
            (root / "corpus").mkdir()
            runtime = DciRuntimeOptions(
                tools="read,bash",
                runtime_context_level="level3",
                thinking_level="high",
            )
            judge = JudgeConfig(api_key="PRIVATE-JUDGE-KEY")
            progress = []
            result = RealDciBenchmarkExecutor(
                paths=_paths(root),
                runtime_options=runtime,
                judge_config=judge,
                benchmark_runner=runner,
                readiness_probe=lambda *_args: None,
            ).execute(
                _invocation(root),
                cancellation=MutableCancellation(),
                on_progress=progress.append,
            )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.case_count, 1)
        self.assertEqual(
            result.artifact_ids,
            ("qa.bamboogle.github-sample50.native-result",),
        )
        self.assertEqual(len(calls), 1)
        request, selected_paths = calls[0]
        self.assertEqual(selected_paths, _paths(root))
        self.assertEqual(request.dataset, root / "dataset.jsonl")
        self.assertEqual(request.output_root, root / "output")
        self.assertEqual(request.cwd, root)
        self.assertIs(request.judge_config, judge)
        self.assertEqual(request.runtime_options.tools, "read,grep")
        self.assertEqual(request.limit, 1)
        self.assertEqual(request.mode, "qa")
        self.assertEqual(
            request.profile,
            "asterion-safe/pi",
        )
        self.assertEqual(request.corpus, root / "corpus")
        self.assertEqual(request.max_concurrency, 1)
        self.assertEqual(request.max_turns, 100)
        self.assertEqual(request.resume_policy, "compatible")
        self.assertEqual(
            tuple(event.status for event in progress),
            ("task.real.started", "task.real.completed"),
        )
        self.assertNotIn("SENTINEL-SECRET", repr(result))

    def test_translates_bounded_bcplus_level3_into_existing_engine(self) -> None:
        calls = []

        async def runner(request, *, paths):
            calls.append((request, paths))
            return BenchmarkResult(
                output_root=request.output_root,
                counts={"total": 50, "completed": 50, "failed": 0},
            )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            result = RealDciBenchmarkExecutor(
                paths=_paths(root),
                runtime_options=DciRuntimeOptions(),
                judge_config=JudgeConfig(api_key="PRIVATE-JUDGE-KEY"),
                benchmark_runner=runner,
                readiness_probe=lambda *_args: None,
            ).execute(
                _invocation(
                    root,
                    task_id="bcplus.level3",
                    profile_id="bcplus.level3",
                    selection_variant="github-level3",
                    case_limit=50,
                ),
                cancellation=MutableCancellation(),
                on_progress=lambda _event: None,
            )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.case_count, 50)
        self.assertEqual(result.artifact_ids, ("bcplus.level3.native-result",))
        self.assertEqual(calls[0][0].limit, 50)
        self.assertEqual(calls[0][0].max_turns, 300)
        self.assertEqual(calls[0][0].max_concurrency, 10)

    def test_translates_bounded_bcplus_main_into_existing_engine(self) -> None:
        calls = []

        async def runner(request, *, paths):
            calls.append((request, paths))
            return BenchmarkResult(
                output_root=request.output_root,
                counts={"total": 50, "completed": 50, "failed": 0},
            )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            result = RealDciBenchmarkExecutor(
                paths=_paths(root),
                runtime_options=DciRuntimeOptions(),
                judge_config=JudgeConfig(api_key="PRIVATE-JUDGE-KEY"),
                benchmark_runner=runner,
                readiness_probe=lambda *_args: None,
            ).execute(
                _invocation(
                    root,
                    task_id="bcplus.main",
                    profile_id="bcplus.openai",
                    selection_variant="main",
                    case_limit=50,
                    runtime_context_level="level3",
                ),
                cancellation=MutableCancellation(),
                on_progress=lambda _event: None,
            )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.case_count, 50)
        self.assertEqual(result.artifact_ids, ("bcplus.main.native-result",))
        self.assertEqual(calls[0][0].limit, 50)
        self.assertEqual(calls[0][0].max_turns, 100)
        self.assertEqual(calls[0][0].max_concurrency, 10)

    def test_translates_bounded_arguana_into_ir_engine(self) -> None:
        calls = []

        async def runner(request, *, paths):
            calls.append((request, paths))
            return BenchmarkResult(
                output_root=request.output_root,
                counts={"total": 50, "completed": 50, "failed": 0},
            )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            result = RealDciBenchmarkExecutor(
                paths=_paths(root),
                runtime_options=DciRuntimeOptions(),
                judge_config=JudgeConfig(api_key="PRIVATE-JUDGE-KEY"),
                benchmark_runner=runner,
                readiness_probe=lambda *_args: None,
            ).execute(
                _invocation(
                    root,
                    task_id="beir.arguana",
                    profile_id="beir.arguana",
                    selection_variant="paper-main",
                    case_limit=50,
                ),
                cancellation=MutableCancellation(),
                on_progress=lambda _event: None,
            )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.case_count, 50)
        self.assertEqual(calls[0][0].mode, "ir")
        self.assertEqual(calls[0][0].dataset_profile, "beir.arguana")
        self.assertEqual(calls[0][0].max_turns, 300)
        self.assertEqual(calls[0][0].max_concurrency, 10)
        self.assertEqual(calls[0][0].max_native_attempts, 2)

    def test_translates_bounded_scifact_into_ir_engine(self) -> None:
        calls = []

        async def runner(request, *, paths):
            calls.append((request, paths))
            return BenchmarkResult(
                output_root=request.output_root,
                counts={"total": 50, "completed": 50, "failed": 0},
            )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            result = RealDciBenchmarkExecutor(
                paths=_paths(root),
                runtime_options=DciRuntimeOptions(),
                judge_config=JudgeConfig(api_key="PRIVATE-JUDGE-KEY"),
                benchmark_runner=runner,
                readiness_probe=lambda *_args: None,
            ).execute(
                _invocation(
                    root,
                    task_id="beir.scifact",
                    profile_id="beir.scifact",
                    selection_variant="paper-main",
                    case_limit=50,
                ),
                cancellation=MutableCancellation(),
                on_progress=lambda _event: None,
            )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.case_count, 50)
        self.assertEqual(calls[0][0].mode, "ir")
        self.assertEqual(calls[0][0].dataset_profile, "beir.scifact")
        self.assertEqual(calls[0][0].max_turns, 300)
        self.assertEqual(calls[0][0].max_concurrency, 10)
        self.assertEqual(calls[0][0].max_native_attempts, 3)

    def test_translates_bounded_bright_biology_into_ir_engine(self) -> None:
        calls = []

        async def runner(request, *, paths):
            calls.append((request, paths))
            return BenchmarkResult(
                output_root=request.output_root,
                counts={"total": 50, "completed": 50, "failed": 0},
            )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            result = RealDciBenchmarkExecutor(
                paths=_paths(root), runtime_options=DciRuntimeOptions(),
                judge_config=JudgeConfig(api_key="PRIVATE-JUDGE-KEY"),
                benchmark_runner=runner, readiness_probe=lambda *_args: None,
            ).execute(
                _invocation(
                    root, task_id="bright.biology", profile_id="bright.biology",
                    selection_variant="main", case_limit=50,
                ), cancellation=MutableCancellation(), on_progress=lambda _event: None,
            )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.case_count, 50)
        self.assertEqual(calls[0][0].mode, "ir")
        self.assertEqual(calls[0][0].dataset_profile, "bright.biology")
        self.assertEqual(calls[0][0].max_turns, 300)
        self.assertEqual(calls[0][0].max_concurrency, 10)
        self.assertEqual(calls[0][0].max_native_attempts, 3)

    def test_translates_bounded_bright_earth_science_into_ir_engine(self) -> None:
        calls = []

        async def runner(request, *, paths):
            calls.append((request, paths))
            return BenchmarkResult(
                output_root=request.output_root,
                counts={"total": 50, "completed": 50, "failed": 0},
            )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            result = RealDciBenchmarkExecutor(
                paths=_paths(root), runtime_options=DciRuntimeOptions(),
                judge_config=JudgeConfig(api_key="PRIVATE-JUDGE-KEY"),
                benchmark_runner=runner, readiness_probe=lambda *_args: None,
            ).execute(
                _invocation(
                    root, task_id="bright.earth-science",
                    profile_id="bright.earth-science", selection_variant="main",
                    case_limit=50,
                ), cancellation=MutableCancellation(), on_progress=lambda _event: None,
            )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.case_count, 50)
        self.assertEqual(calls[0][0].mode, "ir")
        self.assertEqual(calls[0][0].dataset_profile, "bright.earth-science")
        self.assertEqual(calls[0][0].max_turns, 300)
        self.assertEqual(calls[0][0].max_concurrency, 10)
        self.assertEqual(calls[0][0].max_native_attempts, 3)

    def test_translates_bounded_bright_economics_into_ir_engine(self) -> None:
        calls = []

        async def runner(request, *, paths):
            calls.append((request, paths))
            return BenchmarkResult(output_root=request.output_root, counts={"total": 50, "completed": 50, "failed": 0})

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            result = RealDciBenchmarkExecutor(
                paths=_paths(root), runtime_options=DciRuntimeOptions(),
                judge_config=JudgeConfig(api_key="PRIVATE-JUDGE-KEY"),
                benchmark_runner=runner, readiness_probe=lambda *_args: None,
            ).execute(
                _invocation(root, task_id="bright.economics", profile_id="bright.economics", selection_variant="main", case_limit=50),
                cancellation=MutableCancellation(), on_progress=lambda _event: None,
            )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.case_count, 50)
        self.assertEqual(calls[0][0].mode, "ir")
        self.assertEqual(calls[0][0].dataset_profile, "bright.economics")
        self.assertEqual(calls[0][0].max_turns, 300)
        self.assertEqual(calls[0][0].max_concurrency, 10)
        self.assertEqual(calls[0][0].max_native_attempts, 3)

    def test_translates_bounded_bright_robotics_into_ir_engine(self) -> None:
        calls = []

        async def runner(request, *, paths):
            calls.append((request, paths))
            return BenchmarkResult(output_root=request.output_root, counts={"total": 50, "completed": 50, "failed": 0})

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            result = RealDciBenchmarkExecutor(
                paths=_paths(root), runtime_options=DciRuntimeOptions(),
                judge_config=JudgeConfig(api_key="PRIVATE-JUDGE-KEY"),
                benchmark_runner=runner, readiness_probe=lambda *_args: None,
            ).execute(
                _invocation(root, task_id="bright.robotics", profile_id="bright.robotics", selection_variant="main", case_limit=50),
                cancellation=MutableCancellation(), on_progress=lambda _event: None,
            )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.case_count, 50)
        self.assertEqual(calls[0][0].mode, "ir")
        self.assertEqual(calls[0][0].dataset_profile, "bright.robotics")
        self.assertEqual(calls[0][0].max_turns, 300)
        self.assertEqual(calls[0][0].max_concurrency, 10)
        self.assertEqual(calls[0][0].max_native_attempts, 3)

    def test_translates_bounded_2wikimultihopqa_into_qa_engine(self) -> None:
        calls = []

        async def runner(request, *, paths):
            calls.append((request, paths))
            return BenchmarkResult(output_root=request.output_root, counts={"total": 50, "completed": 50, "failed": 0})

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            result = RealDciBenchmarkExecutor(
                paths=_paths(root), runtime_options=DciRuntimeOptions(),
                judge_config=JudgeConfig(api_key="PRIVATE-JUDGE-KEY"),
                benchmark_runner=runner, readiness_probe=lambda *_args: None,
            ).execute(
                _invocation(root, task_id="qa.2wikimultihopqa", profile_id="qa.2wikimultihopqa", selection_variant="main", case_limit=50),
                cancellation=MutableCancellation(), on_progress=lambda _event: None,
            )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.case_count, 50)
        self.assertEqual(calls[0][0].mode, "qa")
        self.assertIsNone(calls[0][0].dataset_profile)
        self.assertEqual(calls[0][0].max_turns, 100)
        self.assertEqual(calls[0][0].max_concurrency, 1)
        self.assertEqual(calls[0][0].max_native_attempts, 2)

    def test_translates_bounded_hotpotqa_into_qa_engine(self) -> None:
        calls = []

        async def runner(request, *, paths):
            calls.append((request, paths))
            return BenchmarkResult(output_root=request.output_root, counts={"total": 50, "completed": 50, "failed": 0})

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            result = RealDciBenchmarkExecutor(
                paths=_paths(root), runtime_options=DciRuntimeOptions(),
                judge_config=JudgeConfig(api_key="PRIVATE-JUDGE-KEY"),
                benchmark_runner=runner, readiness_probe=lambda *_args: None,
            ).execute(
                _invocation(root, task_id="qa.hotpotqa", profile_id="qa.hotpotqa", selection_variant="main", case_limit=50),
                cancellation=MutableCancellation(), on_progress=lambda _event: None,
            )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.case_count, 50)
        self.assertEqual(calls[0][0].mode, "qa")
        self.assertIsNone(calls[0][0].dataset_profile)
        self.assertEqual(calls[0][0].max_turns, 100)
        self.assertEqual(calls[0][0].max_concurrency, 1)
        self.assertEqual(calls[0][0].max_native_attempts, 2)

    def test_translates_bounded_musique_into_qa_engine(self) -> None:
        calls = []

        async def runner(request, *, paths):
            calls.append((request, paths))
            return BenchmarkResult(output_root=request.output_root, counts={"total": 50, "completed": 50, "failed": 0})

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            result = RealDciBenchmarkExecutor(
                paths=_paths(root), runtime_options=DciRuntimeOptions(),
                judge_config=JudgeConfig(api_key="PRIVATE-JUDGE-KEY"),
                benchmark_runner=runner, readiness_probe=lambda *_args: None,
            ).execute(
                _invocation(root, task_id="qa.musique", profile_id="qa.musique", selection_variant="main", case_limit=50),
                cancellation=MutableCancellation(), on_progress=lambda _event: None,
            )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.case_count, 50)
        self.assertEqual(calls[0][0].mode, "qa")
        self.assertIsNone(calls[0][0].dataset_profile)
        self.assertEqual(calls[0][0].max_turns, 100)
        self.assertEqual(calls[0][0].max_concurrency, 1)
        self.assertEqual(calls[0][0].max_native_attempts, 2)

    def test_uses_explicit_upstream_profile_and_turn_limit(self) -> None:
        calls = []

        async def runner(request, *, paths):
            calls.append((request, paths))
            return BenchmarkResult(
                output_root=request.output_root,
                counts={"total": 1, "correct": 1, "failed": 0},
            )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            result = RealDciBenchmarkExecutor(
                paths=_paths(root),
                runtime_options=DciRuntimeOptions(
                    runtime="pi",
                    provider="openai-codex",
                    model="gpt-5.6-luna",
                ),
                judge_config=JudgeConfig(api_key="PRIVATE-JUDGE-KEY"),
                experiment_profile=(
                    "upstream-github/"
                    "271f37e71f053bf0c99c05ce6d2fb53b841d922e/pi"
                ),
                max_turns=300,
                benchmark_runner=runner,
                readiness_probe=lambda *_args: None,
            ).execute(
                _invocation(root),
                cancellation=MutableCancellation(),
                on_progress=lambda _event: None,
            )

        self.assertEqual(result.status, "completed")
        self.assertEqual(
            calls[0][0].profile,
            "upstream-github/271f37e71f053bf0c99c05ce6d2fb53b841d922e/pi",
        )
        self.assertEqual(calls[0][0].max_turns, 300)

    def test_rejects_profile_without_a_native_executor(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            with self.assertRaises(DciBenchmarkExecutorError):
                RealDciBenchmarkExecutor(
                    paths=_paths(root),
                    runtime_options=DciRuntimeOptions(runtime="claude-code"),
                    judge_config=JudgeConfig(api_key="PRIVATE-JUDGE-KEY"),
                    experiment_profile="asterion-safe/claude-subscription",
                )

    def test_rejects_wrong_contract_before_runner(self) -> None:
        cases = (
            {"profile_id": "qa.other"},
            {"selection_variant": "paper-full125"},
            {"case_limit": 51},
            {"case_limit": 0},
            {"max_concurrency": 2},
            {"resume_policy": "fresh"},
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            for changes in cases:
                with self.subTest(changes=changes):
                    with self.assertRaises(DciBenchmarkExecutorError):
                        RealDciBenchmarkExecutor(
                            paths=_paths(root),
                            runtime_options=DciRuntimeOptions(),
                            judge_config=JudgeConfig(api_key="key"),
                            benchmark_runner=lambda *_args, **_kwargs: self.fail(
                                "runner called"
                            ),
                            readiness_probe=lambda *_args: None,
                        ).execute(
                            _invocation(root, **changes),
                            cancellation=MutableCancellation(),
                            on_progress=lambda _event: None,
                        )

    def test_cancellation_cancels_and_drains_async_engine(self) -> None:
        started = threading.Event()
        drained = threading.Event()

        async def runner(_request, *, paths):
            del paths
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                drained.set()

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / "dataset.jsonl").write_text("{}\n", encoding="utf-8")
            (root / "corpus").mkdir()
            cancellation = MutableCancellation()

            def cancel() -> None:
                self.assertTrue(started.wait(2))
                cancellation.cancelled = True

            thread = threading.Thread(target=cancel)
            thread.start()
            result = RealDciBenchmarkExecutor(
                paths=_paths(root),
                runtime_options=DciRuntimeOptions(),
                judge_config=JudgeConfig(api_key="key"),
                benchmark_runner=runner,
                readiness_probe=lambda *_args: None,
            ).execute(
                _invocation(root),
                cancellation=cancellation,
                on_progress=lambda _event: None,
            )
            thread.join(2)

        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.case_count, 0)
        self.assertTrue(drained.is_set())

    def test_default_preflight_checks_resources_agent_and_judge(self) -> None:
        async def runner(request, *, paths):
            del paths
            return BenchmarkResult(
                output_root=request.output_root,
                counts={"total": 1, "correct": 1, "failed": 0},
            )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            paths = _paths(root)
            (root / "dataset.jsonl").write_text("{}\n", encoding="utf-8")
            (root / "corpus").mkdir()
            paths.pi.package_dir.mkdir(parents=True)
            (paths.pi.package_dir / "package.json").write_text("{}\n", encoding="utf-8")
            (paths.pi.package_dir / "dist").mkdir()
            (paths.pi.package_dir / "dist" / "cli.js").write_text(
                "fixture\n", encoding="utf-8"
            )
            paths.pi.agent_dir.mkdir()
            (paths.pi.agent_dir / "auth.json").write_text("{}\n", encoding="utf-8")
            executor = RealDciBenchmarkExecutor(
                paths=paths,
                runtime_options=DciRuntimeOptions(
                    provider="openai",
                    model="gpt-5.4-nano",
                ),
                judge_config=JudgeConfig(api_key="judge-key"),
                benchmark_runner=runner,
            )
            with patch(
                "asterion.applications.dci_agent_lite.benchmark_executor.resolve_node_bin",
                return_value="/fixture/node",
            ):
                ready = executor.execute(
                    _invocation(root),
                    cancellation=MutableCancellation(),
                    on_progress=lambda _event: None,
                )

                (root / "dataset.jsonl").write_text("", encoding="utf-8")
                with self.assertRaises(DciBenchmarkExecutorError):
                    executor.execute(
                        _invocation(root),
                        cancellation=MutableCancellation(),
                        on_progress=lambda _event: None,
                    )
                (root / "dataset.jsonl").write_text("{}\n", encoding="utf-8")

                (paths.pi.package_dir / "dist" / "cli.js").unlink()
                with self.assertRaises(DciBenchmarkExecutorError):
                    executor.execute(
                        _invocation(root),
                        cancellation=MutableCancellation(),
                        on_progress=lambda _event: None,
                    )

                (paths.pi.package_dir / "dist" / "cli.js").write_text(
                    "fixture\n", encoding="utf-8"
                )
                no_judge = RealDciBenchmarkExecutor(
                    paths=paths,
                    runtime_options=DciRuntimeOptions(
                        provider="openai",
                        model="gpt-5.4-nano",
                    ),
                    judge_config=JudgeConfig(),
                    benchmark_runner=runner,
                )
                with self.assertRaises(DciBenchmarkExecutorError):
                    no_judge.execute(
                        _invocation(root),
                        cancellation=MutableCancellation(),
                        on_progress=lambda _event: None,
                    )

        self.assertEqual(ready.status, "completed")

    def test_default_preflight_rejects_symlink_dataset_and_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            target = root / "target.jsonl"
            target.write_text("{}\n", encoding="utf-8")
            (root / "dataset.jsonl").symlink_to(target)
            real_corpus = root / "real-corpus"
            real_corpus.mkdir()
            (root / "corpus").symlink_to(real_corpus, target_is_directory=True)
            executor = RealDciBenchmarkExecutor(
                paths=_paths(root),
                runtime_options=DciRuntimeOptions(
                    provider="openai",
                    model="gpt-5.4-nano",
                ),
                judge_config=JudgeConfig(api_key="judge-key"),
                benchmark_runner=lambda *_args, **_kwargs: self.fail("runner called"),
            )
            with self.assertRaises(DciBenchmarkExecutorError):
                executor.execute(
                    _invocation(root),
                    cancellation=MutableCancellation(),
                    on_progress=lambda _event: None,
                )


if __name__ == "__main__":
    unittest.main()
