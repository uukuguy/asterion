from __future__ import annotations

import io
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
import unittest

from tools import dci_benchmark_orchestrator as orchestrator
from tools.dci_benchmark_orchestrator import (
    PROJECT,
    BenchmarkTask,
    OrchestratorError,
    RunOptions,
    build_plan,
    build_task_command,
    execute_plan,
    render_plan,
    select_tasks,
    stream_command,
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

    def test_relative_resource_root_is_canonical_in_the_child_environment(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env_directory = root / "configuration"
            env_directory.mkdir()
            env_file = env_directory / "operator.env"
            env_file.write_text(
                "ASTERION_DCI_RESOURCE_ROOT=../resources\n",
                encoding="utf-8",
            )

            plan = build_plan(
                RunOptions(env_file=env_file),
                process_environment={},
                invocation_cwd=root / "unrelated-cwd",
                run_label="fixture-run",
            )

            expected = str((root / "resources").resolve())
            self.assertEqual(plan.resource_root, Path(expected))
            self.assertEqual(
                plan.environment["ASTERION_DCI_RESOURCE_ROOT"],
                expected,
            )
            launcher = next(task for task in plan.tasks if task.launcher is not None)
            direct = next(task for task in plan.tasks if task.launcher is None)
            command = build_task_command(plan, direct, root / "batch")
            self.assertTrue(
                command[command.index("--dataset") + 1].startswith(expected)
            )
            self.assertTrue(
                command[command.index("--corpus") + 1].startswith(expected)
            )
            child_environments: list[dict[str, str]] = []

            def capture_environment(
                command, *, cwd, environment, on_line
            ) -> int:
                del command, cwd, on_line
                child_environments.append(dict(environment))
                return 0

            bounded = replace(plan, tasks=(launcher, direct))
            self.assertEqual(
                execute_plan(
                    bounded,
                    stream=io.StringIO(),
                    executor=capture_environment,
                ),
                0,
            )
            self.assertEqual(len(child_environments), 3)
            self.assertTrue(
                all(
                    environment["ASTERION_DCI_RESOURCE_ROOT"] == expected
                    for environment in child_environments
                )
            )

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

    def test_cli_argument_failures_are_stable_body_free_and_unabbreviated(
        self,
    ) -> None:
        sentinel = "/private/SENTINEL-operator-path"
        cases = (
            ("invalid-suite", ("--suite", sentinel)),
            ("invalid-integer", ("--limit", sentinel)),
            ("unknown-option", (f"--unknown={sentinel}",)),
            ("abbreviation", ("--max-conc", "1")),
        )
        for label, arguments in cases:
            with self.subTest(label=label):
                result = subprocess.run(
                    [
                        sys.executable,
                        "tools/run_dci_benchmarks.py",
                        *arguments,
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )

                self.assertEqual(result.returncode, 2)
                self.assertEqual(
                    result.stderr,
                    "ERROR: DCI benchmark arguments are invalid\n",
                )
                self.assertEqual(result.stdout, "")
                self.assertNotIn(sentinel, result.stderr)


class BenchmarkEntrypointTests(unittest.TestCase):
    def test_shell_entrypoint_has_valid_syntax_and_exact_python_target(self) -> None:
        project = Path(__file__).resolve().parents[1]
        script = project / "scripts/run_dci_benchmarks.sh"
        syntax = subprocess.run(
            ["bash", "-n", str(script)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        text = script.read_text(encoding="utf-8")
        self.assertIn('uv run --project "$PROJECT_ROOT"', text)
        self.assertIn(
            'python "$PROJECT_ROOT/tools/run_dci_benchmarks.py" "$@"', text
        )
        self.assertNotIn("source ", text)
        self.assertNotIn('. "$', text)

    def test_cli_help_has_no_monetary_inputs(self) -> None:
        project = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            ["uv", "run", "python", "tools/run_dci_benchmarks.py", "--help"],
            cwd=project,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--execute", completed.stdout)
        self.assertIn("--limit", completed.stdout)
        self.assertNotIn("cost", completed.stdout.lower())
        self.assertNotIn("usd", completed.stdout.lower())
        self.assertNotIn("price", completed.stdout.lower())


class FakeExecutor:
    def __init__(self, outcomes: list[int | BaseException] | None = None) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.outcomes = list(outcomes or ())

    def __call__(self, command, *, cwd, environment, on_line):
        self.commands.append(tuple(command))
        on_line(
            "child sentinel-secret private-root-value "
            f"{PROJECT} {environment.get('HOME', '')} "
            f"{environment.get('CACHE_PATH', '')} "
            "dataset-body prompt-body answer-body provider-payload\n"
        )
        outcome = self.outcomes.pop(0) if self.outcomes else 0
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _FakeStdout:
    def __init__(self) -> None:
        self.closed = False

    def __iter__(self):
        yield "callback-content\n"

    def close(self) -> None:
        self.closed = True


class _StubbornFakeProcess:
    def __init__(self) -> None:
        self.stdout = _FakeStdout()
        self.sent_signals: list[int] = []
        self.terminated = False
        self.killed = False
        self.wait_timeouts: list[float | None] = []

    def send_signal(self, value: int) -> None:
        self.sent_signals.append(value)

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout=None) -> int:
        self.wait_timeouts.append(timeout)
        if len(self.wait_timeouts) == 1:
            raise subprocess.TimeoutExpired(("fake-child",), timeout)
        return -9


class _IrreapableFakeProcess(_StubbornFakeProcess):
    def wait(self, timeout=None) -> int:
        self.wait_timeouts.append(timeout)
        raise subprocess.TimeoutExpired(("fake-child",), timeout)


class _RaisingStream:
    def write(self, value: str) -> int:
        raise BrokenPipeError("private-stream-path")

    def flush(self) -> None:
        raise BrokenPipeError("private-stream-path")


class StreamCommandTests(unittest.TestCase):
    def test_callback_failures_stop_with_bounded_wait_kill_and_reap(self) -> None:
        for exception, expected_signal in (
            (RuntimeError("callback failed"), None),
            (KeyboardInterrupt(), signal.SIGINT),
        ):
            with self.subTest(exception=type(exception).__name__):
                process = _StubbornFakeProcess()

                def fail_callback(line: str) -> None:
                    raise exception

                with (
                    patch(
                        "tools.dci_benchmark_orchestrator.subprocess.Popen",
                        return_value=process,
                    ),
                    self.assertRaises(type(exception)),
                ):
                    stream_command(
                        ("fake-command",),
                        cwd=PROJECT,
                        environment={},
                        on_line=fail_callback,
                    )

                self.assertTrue(process.stdout.closed)
                self.assertEqual(
                    process.sent_signals,
                    [] if expected_signal is None else [expected_signal],
                )
                self.assertEqual(process.terminated, expected_signal is None)
                self.assertTrue(process.killed)
                self.assertEqual(len(process.wait_timeouts), 2)
                self.assertIsNotNone(process.wait_timeouts[0])

    def test_cleanup_waits_are_bounded_when_a_child_cannot_be_reaped(
        self,
    ) -> None:
        process = _IrreapableFakeProcess()

        with (
            patch(
                "tools.dci_benchmark_orchestrator.subprocess.Popen",
                return_value=process,
            ),
            self.assertRaisesRegex(
                OrchestratorError,
                "^DCI benchmark child process cleanup failed$",
            ),
        ):
            stream_command(
                ("fake-command",),
                cwd=PROJECT,
                environment={},
                on_line=lambda line: (_ for _ in ()).throw(
                    RuntimeError("callback failed")
                ),
            )

        self.assertEqual(len(process.wait_timeouts), 2)
        self.assertTrue(
            all(timeout is not None for timeout in process.wait_timeouts)
        )

    @unittest.skipUnless(
        hasattr(os, "killpg") and os.name == "posix",
        "process groups require POSIX",
    )
    def test_callback_failure_stops_a_real_descendant_process(self) -> None:
        descendant_pid: int | None = None
        script = (
            "import signal, subprocess, sys, time\n"
            "child = subprocess.Popen([sys.executable, '-c', "
            "\"import signal,time; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)\"])\n"
            "print(f'DESCENDANT={child.pid}', flush=True)\n"
            "time.sleep(60)\n"
        )

        def fail_after_descendant(line: str) -> None:
            nonlocal descendant_pid
            if line.startswith("DESCENDANT="):
                descendant_pid = int(line.partition("=")[2])
            raise RuntimeError("callback failed")

        try:
            with (
                patch.object(
                    orchestrator,
                    "_CHILD_STOP_TIMEOUT_SECONDS",
                    0.2,
                ),
                self.assertRaisesRegex(RuntimeError, "^callback failed$"),
            ):
                stream_command(
                    (sys.executable, "-c", script),
                    cwd=PROJECT,
                    environment=os.environ,
                    on_line=fail_after_descendant,
                )

            self.assertIsNotNone(descendant_pid)
            assert descendant_pid is not None
            deadline = time.monotonic() + 2.0
            running = True
            while time.monotonic() < deadline:
                status = subprocess.run(
                    ["ps", "-o", "stat=", "-p", str(descendant_pid)],
                    check=False,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                running = bool(status) and not status.startswith("Z")
                if not running:
                    break
                time.sleep(0.02)
            self.assertFalse(running, "descendant process survived cleanup")
        finally:
            if descendant_pid is not None:
                try:
                    os.kill(descendant_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


class BenchmarkExecutionTests(unittest.TestCase):
    def _plan(self, root: Path, **changes):
        env_file = root / ".env"
        env_file.write_text(
            f"ASTERION_DCI_RESOURCE_ROOT={root / 'resources'}\n"
            f"ASTERION_DCI_OUTPUT_ROOT={root / 'outputs'}\n"
            "DEEPSEEK_API_KEY=sentinel-secret\n"
            "PRIVATE_PATH=private-root-value\n"
            f"HOME={Path.home()}\n"
            f"CACHE_PATH={root / 'cache-private'}\n",
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
            for private_text in (
                "child",
                str(PROJECT),
                str(Path.home()),
                str(root / "cache-private"),
                "dataset-body",
                "prompt-body",
                "answer-body",
                "provider-payload",
            ):
                self.assertNotIn(private_text, stream.getvalue())

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
            self.assertEqual(
                stat.S_IMODE(
                    (root / "run" / "bcplus.level3").stat().st_mode
                ),
                0o700,
            )
            runner_log = (
                root / "run" / "bcplus.level3" / "runner.log"
            ).read_text(encoding="utf-8")
            self.assertIn("<redacted>", runner_log)
            self.assertNotIn("sentinel-secret", runner_log)
            self.assertNotIn("private-root-value", runner_log)
            self.assertNotIn(str(PROJECT), runner_log)
            self.assertNotIn(str(Path.home()), runner_log)
            self.assertNotIn(str(root / "cache-private"), runner_log)
            self.assertEqual(summary["tasks"][0]["status"], "DONE")
            self.assertEqual(summary["tasks"][1]["status"], "FAILED")
            self.assertTrue(
                all(item["status"] == "NOT_RUN" for item in summary["tasks"][2:])
            )
            encoded = json.dumps(summary, sort_keys=True)
            self.assertNotIn(str(root), encoded)
            self.assertNotIn("sentinel-secret", encoded)
            self.assertNotIn("private-root-value", encoded)
            for private_text in (
                str(PROJECT),
                str(Path.home()),
                str(root / "cache-private"),
                "dataset-body",
                "prompt-body",
                "answer-body",
                "provider-payload",
            ):
                self.assertNotIn(private_text, encoded)

    def test_summary_schema_references_and_closed_batch_layout_are_exact(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            plan = replace(plan, tasks=(plan.tasks[0],))
            clock_values = iter((10.0, 10.125))

            self.assertEqual(
                execute_plan(
                    plan,
                    stream=io.StringIO(),
                    executor=FakeExecutor([0, 0]),
                    clock=lambda: next(clock_values),
                ),
                0,
            )

            summary = json.loads((plan.output_base / "summary.json").read_text())
            self.assertEqual(
                set(summary),
                {
                    "schema",
                    "suite",
                    "run_label",
                    "limit",
                    "max_concurrency",
                    "status",
                    "tasks",
                },
            )
            self.assertEqual(
                summary["schema"],
                "asterion.capabilities.dci.implementation.evaluation.benchmark-orchestrator-summary/v1",
            )
            self.assertEqual(summary["status"], "PASS")
            self.assertEqual(len(summary["tasks"]), 1)
            row = summary["tasks"][0]
            self.assertEqual(
                set(row),
                {
                    "task_id",
                    "selection_variant",
                    "status",
                    "exit_code",
                    "elapsed_seconds",
                    "output",
                    "log",
                    "skip_reason",
                },
            )
            self.assertEqual(
                row,
                {
                    "task_id": "bcplus.level3",
                    "selection_variant": "github-level3",
                    "status": "DONE",
                    "exit_code": 0,
                    "elapsed_seconds": 0.125,
                    "output": "bcplus.level3/batch",
                    "log": "bcplus.level3/runner.log",
                    "skip_reason": None,
                },
            )
            task_root = plan.output_base / "bcplus.level3"
            batch_root = task_root / "batch"
            self.assertTrue(batch_root.is_dir())
            self.assertEqual(stat.S_IMODE(task_root.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(batch_root.stat().st_mode), 0o700)
            self.assertTrue((task_root / "runner.log").is_file())
            self.assertEqual(tuple(batch_root.iterdir()), ())

    def test_unsafe_or_ambiguous_slugs_fail_before_any_child_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            executor = FakeExecutor()
            for task_id in ("", ".", "..", "x" * 256):
                with self.subTest(task_id=task_id):
                    unsafe = replace(plan.tasks[0], task_id=task_id)
                    with self.assertRaisesRegex(
                        OrchestratorError,
                        "^DCI benchmark task binding is invalid$",
                    ):
                        execute_plan(
                            replace(plan, tasks=(unsafe,)),
                            stream=io.StringIO(),
                            executor=executor,
                        )
            first = replace(plan.tasks[0], task_id="A/B")
            second = replace(plan.tasks[1], task_id="A?B")
            with self.assertRaisesRegex(
                OrchestratorError,
                "^DCI benchmark task binding is ambiguous$",
            ):
                execute_plan(
                    replace(plan, tasks=(first, second)),
                    stream=io.StringIO(),
                    executor=executor,
                )
            self.assertEqual(executor.commands, [])

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

    def test_child_start_failure_is_summarized_and_stops(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            executor = FakeExecutor(
                [
                    0,
                    OrchestratorError(
                        "DCI benchmark child process failed to start"
                    ),
                ]
            )
            stream = io.StringIO()

            self.assertEqual(
                execute_plan(plan, stream=stream, executor=executor),
                2,
            )

            summary = json.loads((plan.output_base / "summary.json").read_text())
            self.assertEqual(summary["status"], "FAIL")
            self.assertEqual(summary["tasks"][0]["status"], "FAILED")
            self.assertEqual(summary["tasks"][0]["exit_code"], 2)
            self.assertTrue(
                all(item["status"] == "NOT_RUN" for item in summary["tasks"][1:])
            )
            self.assertNotIn(
                "DCI benchmark child process failed to start",
                stream.getvalue(),
            )

    def test_log_descriptor_failures_are_stable_and_summarized(self) -> None:
        real_open = os.open
        real_fstat = os.fstat
        real_fchmod = os.fchmod

        def fail_log_open(path, flags, mode=0o777, *, dir_fd=None):
            if os.fspath(path).endswith("runner.log"):
                raise OSError("private-path-open")
            return real_open(path, flags, mode, dir_fd=dir_fd)

        fstat_failed = False

        def fail_first_regular_fstat(descriptor):
            nonlocal fstat_failed
            metadata = real_fstat(descriptor)
            if stat.S_ISREG(metadata.st_mode) and not fstat_failed:
                fstat_failed = True
                raise OSError("private-path-fstat")
            return metadata

        fchmod_failed = False

        def fail_first_regular_fchmod(descriptor, mode):
            nonlocal fchmod_failed
            metadata = real_fstat(descriptor)
            if stat.S_ISREG(metadata.st_mode) and not fchmod_failed:
                fchmod_failed = True
                raise OSError("private-path-fchmod")
            return real_fchmod(descriptor, mode)

        failures = (
            ("os.open", fail_log_open),
            ("os.fstat", fail_first_regular_fstat),
            ("os.fchmod", fail_first_regular_fchmod),
        )
        for target, side_effect in failures:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                plan = self._plan(root)
                plan = replace(plan, tasks=(plan.tasks[0],))
                fstat_failed = False
                fchmod_failed = False
                stream = io.StringIO()
                with patch(
                    f"tools.dci_benchmark_orchestrator.{target}",
                    side_effect=side_effect,
                ):
                    result = execute_plan(
                        plan,
                        stream=stream,
                        executor=FakeExecutor([0, 0]),
                    )

                self.assertEqual(result, 2)
                summary = json.loads(
                    (plan.output_base / "summary.json").read_text()
                )
                self.assertEqual(summary["tasks"][0]["status"], "FAILED")
                self.assertEqual(summary["tasks"][0]["exit_code"], 2)
                self.assertNotIn("private-path", stream.getvalue())

    def test_unsafe_summary_descriptor_is_normalized_and_cleaned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            plan = replace(plan, tasks=(plan.tasks[0],))
            real_open = os.open
            real_fstat = os.fstat
            summary_descriptor = None

            def capture_summary_descriptor(
                path, flags, mode=0o777, *, dir_fd=None
            ):
                nonlocal summary_descriptor
                descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
                if (
                    os.fspath(path).startswith(".summary.")
                    and os.fspath(path).endswith(".tmp")
                ):
                    summary_descriptor = descriptor
                return descriptor

            def replace_summary_metadata(descriptor):
                metadata = real_fstat(descriptor)
                if descriptor == summary_descriptor:
                    values = list(metadata)
                    values[0] = stat.S_IFDIR | 0o700
                    return os.stat_result(values)
                return metadata

            with (
                patch(
                    "tools.dci_benchmark_orchestrator.os.open",
                    side_effect=capture_summary_descriptor,
                ),
                patch(
                    "tools.dci_benchmark_orchestrator.os.fstat",
                    side_effect=replace_summary_metadata,
                ),
                self.assertRaisesRegex(
                    OrchestratorError,
                    "^DCI benchmark summary is unsafe$",
                ),
            ):
                execute_plan(
                    plan,
                    stream=io.StringIO(),
                    executor=FakeExecutor([0, 0]),
                )

            self.assertFalse(
                any(
                    child.name.startswith(".summary.")
                    for child in plan.output_base.iterdir()
                )
            )

    def test_summary_temp_swap_is_never_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            plan = replace(plan, tasks=(plan.tasks[0],))
            temporary_name = ".summary.swap-test.tmp"
            real_fsync = os.fsync
            swapped = False

            def swap_temp_after_fsync(descriptor):
                nonlocal swapped
                real_fsync(descriptor)
                if not swapped:
                    swapped = True
                    temporary_path = plan.output_base / temporary_name
                    temporary_path.rename(
                        plan.output_base / ".summary.original-moved"
                    )
                    temporary_path.write_text(
                        '{"unsafe": "provider-body"}\n',
                        encoding="utf-8",
                    )
                    temporary_path.chmod(0o600)

            with (
                patch(
                    "tools.dci_benchmark_orchestrator."
                    "_summary_temporary_name",
                    return_value=temporary_name,
                    create=True,
                ),
                patch(
                    "tools.dci_benchmark_orchestrator.os.fsync",
                    side_effect=swap_temp_after_fsync,
                ),
                self.assertRaisesRegex(
                    OrchestratorError,
                    "^DCI benchmark summary is unsafe$",
                ),
            ):
                execute_plan(
                    plan,
                    stream=io.StringIO(),
                    executor=FakeExecutor([0, 0]),
                )

            self.assertTrue(swapped)
            self.assertFalse((plan.output_base / "summary.json").exists())
            replacement = plan.output_base / temporary_name
            self.assertEqual(
                replacement.read_text(encoding="utf-8"),
                '{"unsafe": "provider-body"}\n',
            )

    def test_replaced_batch_root_is_attested_before_any_child_write(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            plan = replace(plan, tasks=(plan.tasks[0],))
            calls = 0
            replacement: Path | None = None

            def identity_checking_child(
                command, *, cwd, environment, on_line
            ):
                del cwd, on_line
                nonlocal calls, replacement
                calls += 1
                if calls == 1:
                    return 0
                output_root = Path(
                    command[command.index("--output-root") + 1]
                )
                moved = output_root.with_name("original-batch")
                output_root.rename(moved)
                output_root.mkdir(mode=0o700)
                replacement = output_root
                metadata = output_root.stat()
                if (
                    "ASTERION_DCI_EXPECTED_OUTPUT_DEVICE" not in environment
                    or "ASTERION_DCI_EXPECTED_OUTPUT_INODE" not in environment
                ):
                    (output_root / "provider-private.json").write_text(
                        '{"private": true}\n',
                        encoding="utf-8",
                    )
                    return 0
                expected = (
                    int(environment["ASTERION_DCI_EXPECTED_OUTPUT_DEVICE"]),
                    int(environment["ASTERION_DCI_EXPECTED_OUTPUT_INODE"]),
                )
                if (metadata.st_dev, metadata.st_ino) != expected:
                    return 2
                (output_root / "provider-private.json").write_text(
                    '{"private": true}\n',
                    encoding="utf-8",
                )
                return 0

            with self.assertRaisesRegex(
                OrchestratorError,
                "^DCI benchmark task root changed$",
            ):
                execute_plan(
                    plan,
                    stream=io.StringIO(),
                    executor=identity_checking_child,
                )

            self.assertIsNotNone(replacement)
            assert replacement is not None
            self.assertEqual(tuple(replacement.iterdir()), ())

    def test_unsafe_promoted_summary_is_removed_when_still_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            plan = replace(plan, tasks=(plan.tasks[0],))
            real_replace = os.replace

            def weaken_promoted_summary(
                source,
                destination,
                *,
                src_dir_fd=None,
                dst_dir_fd=None,
            ):
                real_replace(
                    source,
                    destination,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                )
                (plan.output_base / "summary.json").chmod(0o644)

            with (
                patch(
                    "tools.dci_benchmark_orchestrator.os.replace",
                    side_effect=weaken_promoted_summary,
                ),
                self.assertRaisesRegex(
                    OrchestratorError,
                    "^DCI benchmark summary is unsafe$",
                ),
            ):
                execute_plan(
                    plan,
                    stream=io.StringIO(),
                    executor=FakeExecutor([0, 0]),
                )

            self.assertFalse((plan.output_base / "summary.json").exists())

    def test_runner_log_replacement_fails_without_summary_publication(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            plan = replace(plan, tasks=(plan.tasks[0],))
            calls = 0

            def replacing_executor(command, *, cwd, environment, on_line):
                nonlocal calls
                calls += 1
                if calls == 2:
                    task_root = plan.output_base / "bcplus.level3"
                    runner_log = task_root / "runner.log"
                    runner_log.rename(task_root / "original-runner.log")
                    runner_log.write_text(
                        "unsafe provider-body\n",
                        encoding="utf-8",
                    )
                    runner_log.chmod(0o600)
                return 0

            with self.assertRaisesRegex(
                OrchestratorError,
                "^DCI benchmark task log changed$",
            ):
                execute_plan(
                    plan,
                    stream=io.StringIO(),
                    executor=replacing_executor,
                )

            self.assertEqual(calls, 2)
            self.assertFalse((plan.output_base / "summary.json").exists())

    def test_public_stream_failure_cannot_hide_completed_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            plan = replace(plan, tasks=(plan.tasks[0],))
            executor = FakeExecutor([0, 0])

            self.assertEqual(
                execute_plan(
                    plan,
                    stream=_RaisingStream(),
                    executor=executor,
                ),
                0,
            )

            self.assertEqual(len(executor.commands), 2)
            summary = json.loads((plan.output_base / "summary.json").read_text())
            self.assertEqual(summary["status"], "PASS")
            self.assertEqual(summary["tasks"][0]["status"], "DONE")
            self.assertNotIn(
                "private-stream-path",
                json.dumps(summary, sort_keys=True),
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

    def test_replaced_task_or_batch_root_fails_closed(self) -> None:
        for replaced_name in ("task", "batch"):
            with (
                self.subTest(replaced_name=replaced_name),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                plan = self._plan(root)
                plan = replace(plan, tasks=(plan.tasks[0],))
                calls = 0

                def replacing_executor(
                    command, *, cwd, environment, on_line
                ):
                    nonlocal calls
                    calls += 1
                    if calls == 2:
                        task_root = plan.output_base / "bcplus.level3"
                        replaced = (
                            task_root
                            if replaced_name == "task"
                            else task_root / "batch"
                        )
                        moved = replaced.with_name(f"moved-{replaced.name}")
                        replaced.rename(moved)
                        replaced.mkdir(mode=0o700)
                    return 0

                with self.assertRaisesRegex(
                    OrchestratorError,
                    "^DCI benchmark task root changed$",
                ):
                    execute_plan(
                        plan,
                        stream=io.StringIO(),
                        executor=replacing_executor,
                    )
                self.assertEqual(calls, 2)
                self.assertFalse((plan.output_base / "summary.json").exists())

    def test_batch_replacement_after_log_open_fails_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            plan = replace(plan, tasks=(plan.tasks[0],))
            executor = FakeExecutor([0, 0])
            real_open_log = orchestrator._open_private_log

            def replace_batch_after_log_open(task_root):
                handle = real_open_log(task_root)
                batch = task_root.path / "batch"
                batch.rename(task_root.path / "moved-batch")
                batch.mkdir(mode=0o700)
                return handle

            with (
                patch(
                    "tools.dci_benchmark_orchestrator._open_private_log",
                    side_effect=replace_batch_after_log_open,
                ),
                self.assertRaisesRegex(
                    OrchestratorError,
                    "^DCI benchmark task root changed$",
                ),
            ):
                execute_plan(
                    plan,
                    stream=io.StringIO(),
                    executor=executor,
                )

            self.assertEqual(len(executor.commands), 1)


if __name__ == "__main__":
    unittest.main()
