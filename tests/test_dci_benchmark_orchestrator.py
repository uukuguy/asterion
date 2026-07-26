from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

from tools.dci_benchmark_orchestrator import (
    OrchestratorError,
    RunOptions,
    build_plan,
    render_plan,
    select_tasks,
)


class BenchmarkInventoryTests(unittest.TestCase):
    def test_suites_have_stable_ordered_membership(self) -> None:
        github = select_tasks("github")
        paper = select_tasks("paper-main")
        combined = select_tasks("all")

        self.assertEqual(len(github), 12)
        self.assertEqual(len(paper), 13)
        self.assertEqual(len(combined), 15)
        self.assertEqual(len({task.task_id for task in combined}), 15)
        self.assertEqual(
            tuple(task.task_id for task in combined),
            (
                "bcplus.level3",
                "bcplus.main",
                "beir.arguana",
                "beir.scifact",
                "bright.biology",
                "bright.earth-science",
                "bright.economics",
                "bright.robotics",
                "qa.2wikimultihopqa",
                "qa.bamboogle.github-sample50",
                "qa.bamboogle.paper-full125",
                "qa.hotpotqa",
                "qa.musique",
                "qa.nq",
                "qa.triviaqa",
            ),
        )

    def test_bamboogle_variants_are_not_deduplicated(self) -> None:
        tasks = {task.task_id: task for task in select_tasks("all")}
        github = tasks["qa.bamboogle.github-sample50"]
        paper = tasks["qa.bamboogle.paper-full125"]

        self.assertEqual(github.selection_variant, "github-sample50")
        self.assertEqual(paper.selection_variant, "paper-full125")
        self.assertIsNotNone(github.launcher)
        self.assertIsNone(paper.launcher)
        self.assertEqual(
            paper.dataset, "paper-full/data/bamboogle/test-125.jsonl"
        )

    def test_paper_ir_tasks_label_asterion_metric_semantics(self) -> None:
        ir_tasks = (
            task
            for task in select_tasks("paper-main")
            if task.profile.startswith(("beir.", "bright."))
        )
        for task in ir_tasks:
            with self.subTest(task=task.task_id):
                self.assertIn("Asterion-defined", task.note)


class BenchmarkPlanTests(unittest.TestCase):
    def test_default_plan_is_bounded_body_free_and_creates_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env_file = root / ".env"
            output = root / "private-output"
            env_file.write_text(
                "ASTERION_DCI_RESOURCE_ROOT=resources\n"
                "ASTERION_DCI_OUTPUT_ROOT=private-output\n"
                "DEEPSEEK_API_KEY=sentinel-secret\n",
                encoding="utf-8",
            )
            stream = io.StringIO()
            plan = build_plan(
                RunOptions(env_file=env_file),
                process_environment={"PATH": os.environ.get("PATH", "")},
                invocation_cwd=root,
                run_label="fixture-run",
            )
            render_plan(plan, stream)
            text = stream.getvalue()

            self.assertEqual(plan.options.suite, "all")
            self.assertEqual(plan.options.limit, 1)
            self.assertEqual(plan.options.max_concurrency, 1)
            self.assertFalse(plan.options.execute)
            self.assertEqual(len(plan.tasks), 15)
            self.assertFalse(output.exists())
            self.assertIn("mode=PLAN", text)
            self.assertIn("tasks=15", text)
            self.assertIn("no USD ledger", text)
            self.assertNotIn("sentinel-secret", text)
            self.assertNotIn(str(root), text)

    def test_process_environment_overrides_dotenv_without_logging_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env_file = root / "operator.env"
            env_file.write_text(
                "DCI_MODEL=dotenv-model\nASTERION_DCI_RESOURCE_ROOT=dotenv-root\n",
                encoding="utf-8",
            )
            plan = build_plan(
                RunOptions(env_file=env_file),
                process_environment={
                    "DCI_MODEL": "process-model",
                    "ASTERION_DCI_RESOURCE_ROOT": str(root / "process-root"),
                },
                invocation_cwd=root,
                run_label="fixture-run",
            )
            self.assertEqual(plan.environment["DCI_MODEL"], "process-model")
            self.assertEqual(plan.resource_root, (root / "process-root").resolve())

    def test_invalid_positive_integer_and_missing_env_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            missing = root / "missing.env"
            with self.assertRaisesRegex(
                OrchestratorError, "^DCI benchmark env file is unavailable$"
            ):
                build_plan(
                    RunOptions(env_file=missing),
                    process_environment={},
                    invocation_cwd=root,
                    run_label="fixture-run",
                )
            for value in (0, -1):
                with self.subTest(value=value), self.assertRaisesRegex(
                    OrchestratorError, "^DCI benchmark limit is invalid$"
                ):
                    RunOptions(limit=value).validate()

    def test_private_values_have_a_total_deterministic_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env_file = root / "operator.env"
            env_file.write_text(
                "ALPHA_KEY=bbbb\nBETA_TOKEN=aaaa\n", encoding="utf-8"
            )
            plan = build_plan(
                RunOptions(env_file=env_file),
                process_environment={},
                invocation_cwd=root,
                run_label="fixture-run",
            )

            self.assertEqual(plan.private_values, ("aaaa", "bbbb"))

    def test_invalid_max_concurrency_fails_closed(self) -> None:
        for value in (0, -1):
            with self.subTest(value=value), self.assertRaisesRegex(
                OrchestratorError, "^DCI benchmark concurrency is invalid$"
            ):
                RunOptions(max_concurrency=value).validate()


class BenchmarkCliTests(unittest.TestCase):
    def test_cli_defaults_to_a_bounded_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env_file = Path(temporary) / "operator.env"
            env_file.write_text("", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    "tools/run_dci_benchmarks.py",
                    "--env-file",
                    str(env_file),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0)
            self.assertIn(
                "suite=all tasks=15 limit=1 concurrency=1 mode=PLAN",
                result.stdout,
            )

    def test_cli_help_exposes_no_monetary_inputs(self) -> None:
        result = subprocess.run(
            [sys.executable, "tools/run_dci_benchmarks.py", "--help"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0)
        for option in (
            "--suite",
            "--limit",
            "--max-concurrency",
            "--output-root",
            "--env-file",
            "--execute",
        ):
            with self.subTest(option=option):
                self.assertIn(option, result.stdout)
        self.assertNotIn("--cost", result.stdout)
        self.assertNotIn("--usd", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
