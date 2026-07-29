from __future__ import annotations

import json
import os
import platform
import sys
import tempfile
import time
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from asterion.benchmarks import (
    AuthorizedProcessTaskExecutor,
    AuthorizedProcessTaskPlan,
    BenchmarkProgressEvent,
    BenchmarkTaskInvocation,
    BenchmarkTaskResult,
)
from asterion.benchmarks.process import BenchmarkProcessError


class AuthorizedProcessTaskPlanTests(unittest.TestCase):
    def test_plan_is_frozen_and_requires_direct_argv(self) -> None:
        plan = AuthorizedProcessTaskPlan(
            argv=(sys.executable, "-c", "pass"),
            cwd=Path.cwd(),
            env={"PYTHONPATH": "src"},
            timeout_seconds=1.0,
            max_output_bytes=32,
        )

        self.assertEqual(plan.argv[0], sys.executable)
        self.assertEqual(dict(plan.env), {"PYTHONPATH": "src"})
        with self.assertRaises(FrozenInstanceError):
            plan.timeout_seconds = 2.0  # type: ignore[misc]
        with self.assertRaises(BenchmarkProcessError):
            AuthorizedProcessTaskPlan(
                argv=("echo hello",),
                cwd=Path.cwd(),
                env={},
                timeout_seconds=1.0,
                max_output_bytes=32,
            )
        with self.assertRaises(BenchmarkProcessError):
            AuthorizedProcessTaskPlan(
                argv=(sys.executable,),
                cwd=Path.cwd(),
                env={"SECRET_TOKEN": "value"},
                timeout_seconds=1.0,
                max_output_bytes=32,
            )

    def test_invalid_plan_errors_do_not_echo_hostile_values(self) -> None:
        with self.assertRaises(BenchmarkProcessError) as caught:
            AuthorizedProcessTaskPlan(
                argv=("SECRET-PROGRAM",),
                cwd=Path("SECRET-PATH"),
                env={},
                timeout_seconds=0.0,
                max_output_bytes=1,
            )

        self.assertNotIn("SECRET", str(caught.exception))


class AuthorizedProcessTaskExecutorTests(unittest.TestCase):
    def test_completed_process_returns_allowlisted_task_result_only(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            out = Path(temp_dir) / "out.json"
            result = self._execute(
                "example.task",
                AuthorizedProcessTaskPlan(
                    argv=(
                        sys.executable,
                        "-c",
                        (
                            "import json, pathlib, sys; "
                            "pathlib.Path(sys.argv[1]).write_text("
                            "json.dumps({'ok': True}) + '\\n', encoding='utf-8'); "
                            "print('SECRET-STDOUT')"
                        ),
                        str(out),
                    ),
                    cwd=Path.cwd(),
                    env={},
                    timeout_seconds=2.0,
                    max_output_bytes=8,
                    artifact_ids=("artifact.alpha",),
                    case_count=4,
                ),
            )

        self.assertEqual(
            result,
            BenchmarkTaskResult(
                task_id="example.task",
                status="completed",
                case_count=4,
                artifact_ids=("artifact.alpha",),
            ),
        )
        self.assertFalse(hasattr(result, "stdout"))
        self.assertFalse(hasattr(result, "stderr"))

    def test_nonzero_exit_fails_without_output_or_payload_leak(self) -> None:
        result = self._execute(
            "example.task",
            AuthorizedProcessTaskPlan(
                argv=(
                    sys.executable,
                    "-c",
                    "import sys; print('SECRET-STDOUT'); sys.exit(7)",
                ),
                cwd=Path.cwd(),
                env={},
                timeout_seconds=2.0,
                max_output_bytes=128,
                case_count=2,
            ),
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.case_count, 0)
        self.assertNotIn("SECRET", repr(result))

    def test_environment_is_cleared_and_explicit(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            out = Path(temp_dir) / "env.json"
            result = self._execute(
                "example.task",
                AuthorizedProcessTaskPlan(
                    argv=(
                        sys.executable,
                        "-c",
                        (
                            "import json, os, pathlib, sys; "
                            "pathlib.Path(sys.argv[1]).write_text("
                            "json.dumps({'secret': os.environ.get('SECRET_PARENT'), "
                            "'allowed': os.environ.get('ALLOWED')}, sort_keys=True), "
                            "encoding='utf-8')"
                        ),
                        str(out),
                    ),
                    cwd=Path.cwd(),
                    env={"ALLOWED": "visible"},
                    timeout_seconds=2.0,
                    max_output_bytes=128,
                    case_count=1,
                ),
            )

            data = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(result.status, "completed")
        self.assertEqual(data, {"allowed": "visible", "secret": None})

    def test_direct_argv_does_not_invoke_shell(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            marker = Path(temp_dir) / "marker"
            result = self._execute(
                "example.task",
                AuthorizedProcessTaskPlan(
                    argv=(
                        sys.executable,
                        "-c",
                        "import sys; sys.exit(0 if sys.argv[1] == ';' else 9)",
                        ";",
                        f"touch {marker}",
                    ),
                    cwd=Path.cwd(),
                    env={},
                    timeout_seconds=2.0,
                    max_output_bytes=128,
                    case_count=1,
                ),
            )

        self.assertEqual(result.status, "completed")
        self.assertFalse(marker.exists())

    def test_precancelled_signal_does_not_spawn(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            marker = Path(temp_dir) / "marker"
            result = self._execute(
                "example.task",
                AuthorizedProcessTaskPlan(
                    argv=(
                        sys.executable,
                        "-c",
                        (
                            "import pathlib, sys; "
                            "pathlib.Path(sys.argv[1]).write_text('spawned')"
                        ),
                        str(marker),
                    ),
                    cwd=Path.cwd(),
                    env={},
                    timeout_seconds=2.0,
                    max_output_bytes=128,
                ),
                cancellation=ManualCancellation(cancelled=True),
            )

        self.assertEqual(result.status, "cancelled")
        self.assertFalse(marker.exists())

    def test_timeout_kills_process_and_returns_cancelled(self) -> None:
        result = self._execute(
            "example.task",
            AuthorizedProcessTaskPlan(
                argv=(sys.executable, "-c", "import time; time.sleep(30)"),
                cwd=Path.cwd(),
                env={},
                timeout_seconds=0.1,
                max_output_bytes=128,
            ),
        )

        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.case_count, 0)

    def test_callback_progress_reports_bounded_output_metadata(self) -> None:
        events: list[BenchmarkProgressEvent] = []
        result = self._execute(
            "example.task",
            AuthorizedProcessTaskPlan(
                argv=(
                    sys.executable,
                    "-c",
                    (
                        "import sys; "
                        "sys.stdout.write('x' * 100); "
                        "sys.stderr.write('y' * 100)"
                    ),
                ),
                cwd=Path.cwd(),
                env={},
                timeout_seconds=2.0,
                max_output_bytes=10,
                case_count=1,
            ),
            on_progress=events.append,
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(
            [(event.status, event.task_id) for event in events],
            [("task.process-exited", "example.task")],
        )

    @unittest.skipUnless(os.name == "posix", "POSIX process-group cancellation only")
    def test_cancellation_kills_process_tree_before_returning(self) -> None:
        if platform.system() not in {"Darwin", "Linux"}:
            self.skipTest("process liveness probe is only validated on Darwin/Linux")
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            state = Path(temp_dir) / "pids.json"
            cancellation = ManualCancellation()
            plan = AuthorizedProcessTaskPlan(
                argv=(
                    sys.executable,
                    "tests/fixtures/helpers/benchmark_process_tree.py",
                    str(state),
                ),
                cwd=Path.cwd(),
                env={},
                timeout_seconds=10.0,
                max_output_bytes=128,
                termination_grace_seconds=0.1,
            )
            invocation = BenchmarkTaskInvocation(
                task_id="example.task",
                binding_id="example.task",
                public_arguments=("tree",),
                private_payload=plan,
            )

            result = AuthorizedProcessTaskExecutor(
                poll_interval_seconds=0.02,
            ).execute(
                invocation,
                cancellation=CancellationAfterStateFile(cancellation, state),
                on_progress=lambda _event: None,
            )
            pids = json.loads(state.read_text(encoding="utf-8"))

        self.assertEqual(result.status, "cancelled")
        self.assertEventuallyGone(int(pids["child_pid"]))
        self.assertEventuallyGone(int(pids["grandchild_pid"]))

    def test_invalid_payload_is_rejected_without_leaking_repr(self) -> None:
        invocation = BenchmarkTaskInvocation(
            task_id="example.task",
            binding_id="example.task",
            public_arguments=("safe",),
            private_payload={"secret": "SECRET-PAYLOAD"},
        )

        with self.assertRaises(BenchmarkProcessError) as caught:
            AuthorizedProcessTaskExecutor().execute(
                invocation,
                cancellation=ManualCancellation(),
                on_progress=lambda _event: None,
            )

        self.assertNotIn("SECRET", str(caught.exception))

    def _execute(
        self,
        task_id: str,
        plan: AuthorizedProcessTaskPlan,
        *,
        cancellation: ManualCancellation | None = None,
        on_progress=lambda _event: None,
    ) -> BenchmarkTaskResult:
        invocation = BenchmarkTaskInvocation(
            task_id=task_id,
            binding_id=task_id,
            public_arguments=("safe",),
            private_payload=plan,
        )
        return AuthorizedProcessTaskExecutor().execute(
            invocation,
            cancellation=cancellation or ManualCancellation(),
            on_progress=on_progress,
        )

    def assertEventuallyGone(self, pid: int) -> None:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if not _pid_alive(pid):
                return
            time.sleep(0.05)
        self.fail(f"process {pid} remained alive")


class ManualCancellation:
    def __init__(self, *, cancelled: bool = False) -> None:
        self._cancelled = cancelled

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True


class CancellationAfterStateFile:
    def __init__(self, delegate: ManualCancellation, state_file: Path) -> None:
        self._delegate = delegate
        self._state_file = state_file

    @property
    def cancelled(self) -> bool:
        if self._state_file.exists():
            self._delegate.cancel()
        return self._delegate.cancelled


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as stat_file:
            parts = stat_file.read().split()
    except OSError:
        return True
    return len(parts) < 3 or parts[2] != "Z"


if __name__ == "__main__":
    unittest.main()
