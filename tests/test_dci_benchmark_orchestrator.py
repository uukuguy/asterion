from __future__ import annotations

import io
import json
import os
import stat
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
import unittest

from tools.dci_benchmark_orchestrator import (
    BenchmarkTask,
    OrchestratorError,
    RunOptions,
    build_plan,
    build_task_command,
    execute_plan,
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


class FakeExecutor:
    def __init__(self, outcomes: list[int | BaseException] | None = None) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.outcomes = list(outcomes or ())

    def __call__(self, command, *, cwd, environment, on_line):
        self.commands.append(tuple(command))
        on_line("child sentinel-secret private-root-value\n")
        outcome = self.outcomes.pop(0) if self.outcomes else 0
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class BenchmarkExecutionTests(unittest.TestCase):
    def _plan(self, root: Path, **changes):
        env_file = root / ".env"
        env_file.write_text(
            f"ASTERION_DCI_RESOURCE_ROOT={root / 'resources'}\n"
            f"ASTERION_DCI_OUTPUT_ROOT={root / 'outputs'}\n"
            "DEEPSEEK_API_KEY=sentinel-secret\n"
            "PRIVATE_PATH=private-root-value\n",
            encoding="utf-8",
        )
        options = RunOptions(
            suite="github",
            env_file=env_file,
            output_root=root / "run",
            execute=True,
        )
        options = replace(options, **changes)
        return build_plan(
            options,
            process_environment={},
            invocation_cwd=root,
            run_label="fixture-run",
        )

    def test_commands_are_bounded_and_task_roots_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root, limit=2, max_concurrency=1)
            first, second = plan.tasks[:2]
            one = build_task_command(plan, first, root / "one")
            two = build_task_command(plan, second, root / "two")
            for command, output in ((one, root / "one"), (two, root / "two")):
                self.assertIn("--limit", command)
                self.assertEqual(command[command.index("--limit") + 1], "2")
                self.assertEqual(
                    command[command.index("--max-concurrency") + 1], "1"
                )
                self.assertEqual(
                    command[command.index("--resume-policy") + 1], "compatible"
                )
                self.assertEqual(
                    command[command.index("--output-root") + 1], str(output)
                )
            self.assertNotEqual(one[-1], two[-1])

    def test_paper_bamboogle_command_uses_full_125_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root, suite="all")
            task = next(
                task
                for task in plan.tasks
                if task.task_id == "qa.bamboogle.paper-full125"
            )
            command = build_task_command(plan, task, root / "paper-bamboogle")
            self.assertEqual(
                command[0:5],
                (
                    "uv",
                    "run",
                    "--project",
                    str(Path(__file__).resolve().parents[1]),
                    "asterion-dci",
                ),
            )
            self.assertEqual(
                command[command.index("--dataset") + 1],
                str(
                    plan.resource_root
                    / "paper-full/data/bamboogle/test-125.jsonl"
                ),
            )

    def test_resource_check_precedes_sequential_tasks_and_failure_stops(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            executor = FakeExecutor([0, 0, 7])
            stream = io.StringIO()
            result = execute_plan(plan, stream=stream, executor=executor)

            self.assertEqual(result, 7)
            self.assertIn("setup_resources.py", " ".join(executor.commands[0]))
            self.assertEqual(len(executor.commands), 3)
            self.assertIn("[1/12]", stream.getvalue())
            self.assertIn("DONE", stream.getvalue())
            self.assertIn("FAILED exit=7", stream.getvalue())
            self.assertIn("elapsed=", stream.getvalue())
            self.assertRegex(
                stream.getvalue(),
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00",
            )
            self.assertNotIn("sentinel-secret", stream.getvalue())
            self.assertNotIn("private-root-value", stream.getvalue())

            summary = json.loads((root / "run" / "summary.json").read_text())
            self.assertEqual(
                stat.S_IMODE((root / "run" / "summary.json").stat().st_mode),
                0o600,
            )
            self.assertEqual(
                stat.S_IMODE(
                    (root / "run" / "bcplus.level3" / "runner.log").stat().st_mode
                ),
                0o600,
            )
            runner_log = (
                root / "run" / "bcplus.level3" / "runner.log"
            ).read_text(encoding="utf-8")
            self.assertIn("<redacted>", runner_log)
            self.assertNotIn("sentinel-secret", runner_log)
            self.assertNotIn("private-root-value", runner_log)
            self.assertEqual(summary["tasks"][0]["status"], "DONE")
            self.assertEqual(summary["tasks"][1]["status"], "FAILED")
            self.assertTrue(
                all(item["status"] == "NOT_RUN" for item in summary["tasks"][2:])
            )
            encoded = json.dumps(summary, sort_keys=True)
            self.assertNotIn(str(root), encoded)
            self.assertNotIn("sentinel-secret", encoded)
            self.assertNotIn("private-root-value", encoded)

    def test_failed_resource_check_creates_no_run_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            executor = FakeExecutor([4])
            self.assertEqual(
                execute_plan(plan, stream=io.StringIO(), executor=executor), 4
            )
            self.assertEqual(len(executor.commands), 1)
            self.assertFalse(plan.output_base.exists())

    def test_missing_task_binding_fails_before_resource_or_provider_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            missing = replace(
                plan.tasks[0], launcher="scripts/missing-launcher.sh"
            )
            plan = replace(plan, tasks=(missing,))
            executor = FakeExecutor()
            with self.assertRaisesRegex(
                OrchestratorError,
                "^DCI benchmark task binding is unavailable$",
            ):
                execute_plan(plan, stream=io.StringIO(), executor=executor)
            self.assertEqual(executor.commands, [])
            self.assertFalse(plan.output_base.exists())

    def test_skip_is_nonfatal_and_never_reported_done(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            skipped = BenchmarkTask(
                "paper.ablation.missing", ("paper-main",), "unused", None,
                None, None, "method-incomplete", "",
                skip_reason="method-incomplete",
            )
            plan = replace(plan, tasks=(skipped, plan.tasks[0]))
            executor = FakeExecutor([0, 0])
            stream = io.StringIO()
            self.assertEqual(
                execute_plan(plan, stream=stream, executor=executor), 0
            )
            self.assertIn("SKIP reason=method-incomplete", stream.getvalue())
            self.assertNotIn("paper.ablation.missing DONE", stream.getvalue())
            self.assertEqual(len(executor.commands), 2)

    def test_interrupt_finalizes_body_free_failure_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            executor = FakeExecutor([0, KeyboardInterrupt()])
            self.assertEqual(
                execute_plan(plan, stream=io.StringIO(), executor=executor), 130
            )
            summary = json.loads((plan.output_base / "summary.json").read_text())
            self.assertEqual(summary["status"], "FAIL")
            self.assertEqual(summary["tasks"][0]["status"], "FAILED")
            self.assertTrue(
                all(item["status"] == "NOT_RUN" for item in summary["tasks"][1:])
            )

    def test_existing_non_private_or_symlink_run_root_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            plan.output_base.mkdir(mode=0o755)
            plan.output_base.chmod(0o755)
            with self.assertRaisesRegex(
                OrchestratorError, "^DCI benchmark output root is unsafe$"
            ):
                execute_plan(plan, stream=io.StringIO(), executor=FakeExecutor())
            target = root / "target"
            target.mkdir(mode=0o700)
            linked_plan = self._plan(root, output_root=root / "linked-run")
            linked_plan.output_base.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(
                OrchestratorError, "^DCI benchmark output root is unsafe$"
            ):
                execute_plan(
                    linked_plan, stream=io.StringIO(), executor=FakeExecutor()
                )

    def test_replaced_run_root_fails_before_later_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            calls = 0

            def replacing_executor(command, *, cwd, environment, on_line):
                nonlocal calls
                calls += 1
                if calls == 2:
                    moved = plan.output_base.with_name("moved")
                    plan.output_base.rename(moved)
                    plan.output_base.mkdir(mode=0o700)
                return 0

            with self.assertRaisesRegex(
                OrchestratorError, "^DCI benchmark output root changed$"
            ):
                execute_plan(
                    plan, stream=io.StringIO(), executor=replacing_executor
                )
            self.assertEqual(calls, 2)


if __name__ == "__main__":
    unittest.main()
