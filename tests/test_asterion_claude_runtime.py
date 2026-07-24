from __future__ import annotations

import json
import os
import subprocess
import stat
import sys
import tempfile
import unittest
import asyncio
from pathlib import Path
from unittest.mock import Mock

from asterion.runtime.host import RunRequest
from asterion.runtime.protocol import validate_event_stream
from asterion.runtime.protocol import ProtocolError
from asterion.runtimes.claude_code import ClaudeCodeRuntimeClient


FIXTURE = Path(__file__).parent / "fixtures/claude_code/valid-success.jsonl"


class Cancelled:
    cancelled = True


class MutableCancellation:
    cancelled = False


class ClaudeCodeRuntimeClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_persistent_evidence_is_private_and_resolvable_after_completion(self) -> None:
        process = Mock(
            return_value=subprocess.CompletedProcess([], 0, FIXTURE.read_text(), "")
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "private"
            runtime = ClaudeCodeRuntimeClient(
                executable="claude",
                cwd=Path(directory),
                environment={},
                evidence_root=root,
                run_process=process,
            )

            events = [
                event
                async for event in runtime.run(RunRequest("persistent-run", "question"))
            ]
            run_dir = runtime.completed_run_dir("persistent-run")

            self.assertIsNotNone(run_dir)
            assert run_dir is not None
            self.assertEqual(stat.S_IMODE(run_dir.stat().st_mode), 0o700)
            self.assertEqual((run_dir / "final.txt").read_text(), "OK\n")
            policy = json.loads((run_dir / "runtime-policy.json").read_text())
            self.assertEqual(policy["runtime_cwd"], str(Path(directory).resolve()))
            self.assertTrue(all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in run_dir.iterdir()))
            self.assertEqual(events[-1].type, "run.completed")

    async def test_profile_max_turns_reaches_command_and_runtime_policy(self) -> None:
        process = Mock(
            return_value=subprocess.CompletedProcess([], 0, FIXTURE.read_text(), "")
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "private"
            runtime = ClaudeCodeRuntimeClient(
                executable="claude",
                cwd=Path(directory),
                environment={},
                evidence_root=root,
                max_turns=100,
                run_process=process,
            )
            _ = [event async for event in runtime.run(RunRequest("profile-run", "q"))]
            command = process.call_args.args[0]
            self.assertEqual(command[command.index("--max-turns") + 1], "100")
            run_dir = runtime.completed_run_dir("profile-run")
            assert run_dir is not None
            policy = json.loads((run_dir / "runtime-policy.json").read_text())
            self.assertEqual(policy["max_turns"], 100)

    async def test_exact_profile_controls_reach_command_and_runtime_policy(self) -> None:
        process = Mock(
            return_value=subprocess.CompletedProcess([], 0, FIXTURE.read_text(), "")
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "private"
            runtime = ClaudeCodeRuntimeClient(
                executable="claude",
                cwd=Path(directory),
                environment={},
                evidence_root=root,
                tools=("Read", "Grep"),
                max_turns=100,
                agent_model="claude-sonnet-4-6",
                reasoning="medium",
                context_profile="level3",
                run_process=process,
            )
            _ = [event async for event in runtime.run(RunRequest("exact-profile", "q"))]
            command = process.call_args.args[0]
            self.assertEqual(command[command.index("--model") + 1], "claude-sonnet-4-6")
            self.assertEqual(command[command.index("--effort") + 1], "medium")
            self.assertEqual(command[command.index("--tools") + 1], "Read,Grep")
            self.assertIn("level3", command[command.index("--append-system-prompt") + 1])
            run_dir = runtime.completed_run_dir("exact-profile")
            assert run_dir is not None
            policy = json.loads((run_dir / "runtime-policy.json").read_text())
            self.assertEqual(policy["agent_model"], "claude-sonnet-4-6")
            self.assertEqual(policy["reasoning"], "medium")
            self.assertEqual(policy["tools"], ["Read", "Grep"])
            self.assertEqual(policy["context_profile"], "level3")

    async def test_projects_fixture_events_without_retaining_secret_environment(self) -> None:
        process = Mock(
            return_value=subprocess.CompletedProcess([], 0, FIXTURE.read_text(), "")
        )
        runtime = ClaudeCodeRuntimeClient(
            executable="claude",
            cwd=Path.cwd(),
            environment={"ANTHROPIC_AUTH_TOKEN": "SECRET"},
            run_process=process,
        )

        events = [
            event
            async for event in runtime.run(RunRequest("runtime-run", "SECRET-PROMPT"))
        ]

        self.assertEqual(runtime.manifest.runtime_id, "claude-code.reference")
        self.assertEqual(
            runtime.manifest.capabilities,
            ("claude.tool.glob", "claude.tool.grep", "filesystem.read"),
        )
        command = process.call_args.args[0]
        self.assertIn("Read,Grep,Glob", command)
        self.assertNotIn("Bash", command)
        self.assertEqual(process.call_args.kwargs["env"]["ANTHROPIC_AUTH_TOKEN"], "SECRET")
        self.assertNotIn("SECRET", repr(events))
        self.assertTrue(all(event.run_id == "runtime-run" for event in events))
        validate_event_stream([event.to_mapping() for event in events])

    async def test_configured_default_timeout_applies_without_request_deadline(self) -> None:
        process = Mock(
            return_value=subprocess.CompletedProcess([], 0, FIXTURE.read_text(), "")
        )
        runtime = ClaudeCodeRuntimeClient(
            executable="claude",
            cwd=Path.cwd(),
            environment={},
            default_timeout_seconds=3600.0,
            run_process=process,
        )

        events = [
            event
            async for event in runtime.run(RunRequest("configured-timeout", "question"))
        ]

        self.assertEqual(process.call_args.kwargs["timeout"], 3600.0)
        self.assertEqual(events[-1].type, "run.completed")

    async def test_pre_cancel_fails_before_starting_fixture_process(self) -> None:
        process = Mock()
        runtime = ClaudeCodeRuntimeClient(
            executable="claude",
            cwd=Path.cwd(),
            environment={},
            run_process=process,
        )

        with self.assertRaises(ValueError):
            await anext(runtime.run(RunRequest("runtime-run", "input"), signal=Cancelled()))
        process.assert_not_called()

    async def test_deadline_failure_is_redacted(self) -> None:
        process = Mock(side_effect=subprocess.TimeoutExpired(["claude"], 0.001))
        runtime = ClaudeCodeRuntimeClient(
            executable="claude",
            cwd=Path.cwd(),
            environment={},
            run_process=process,
        )

        with self.assertRaises(ProtocolError) as caught:
            await anext(
                runtime.run(
                    RunRequest(
                        "deadline-run", "SECRET-DEADLINE-INPUT", deadline_ms=1
                    )
                )
            )

        self.assertNotIn("SECRET", str(caught.exception))

    async def test_nonzero_process_exit_cannot_claim_completion(self) -> None:
        process = Mock(
            return_value=subprocess.CompletedProcess([], 17, FIXTURE.read_text(), "")
        )
        runtime = ClaudeCodeRuntimeClient(
            executable="claude",
            cwd=Path.cwd(),
            environment={},
            run_process=process,
        )

        with self.assertRaises(ProtocolError):
            await anext(runtime.run(RunRequest("nonzero-run", "question")))

    async def test_inflight_cancellation_terminates_and_reaps_child(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pid_file = root / "child.pid"
            executable = root / "blocking-claude"
            executable.write_text(
                f"#!{sys.executable}\n"
                "import os, pathlib, time\n"
                "pathlib.Path(os.environ['TEST_CHILD_PID_FILE']).write_text(str(os.getpid()))\n"
                "time.sleep(30)\n"
            )
            executable.chmod(0o700)
            signal = MutableCancellation()
            runtime = ClaudeCodeRuntimeClient(
                executable=str(executable),
                cwd=root,
                environment={"TEST_CHILD_PID_FILE": str(pid_file)},
                default_timeout_seconds=None,
            )
            task = asyncio.create_task(
                anext(runtime.run(RunRequest("cancel-running", "question"), signal=signal))
            )
            for _ in range(100):
                if pid_file.exists():
                    break
                await asyncio.sleep(0.01)
            self.assertTrue(pid_file.exists())
            pid = int(pid_file.read_text())
            signal.cancelled = True

            with self.assertRaises(ProtocolError):
                await asyncio.wait_for(task, timeout=3)
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    async def test_task_cancellation_terminates_and_reaps_child(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pid_file = root / "child.pid"
            executable = root / "blocking-claude"
            executable.write_text(
                f"#!{sys.executable}\n"
                "import os, pathlib, time\n"
                "pathlib.Path(os.environ['TEST_CHILD_PID_FILE']).write_text(str(os.getpid()))\n"
                "time.sleep(30)\n"
            )
            executable.chmod(0o700)
            runtime = ClaudeCodeRuntimeClient(
                executable=str(executable),
                cwd=root,
                environment={"TEST_CHILD_PID_FILE": str(pid_file)},
                default_timeout_seconds=None,
            )
            task = asyncio.create_task(
                anext(runtime.run(RunRequest("cancel-task", "question")))
            )
            for _ in range(100):
                if pid_file.exists():
                    break
                await asyncio.sleep(0.01)
            self.assertTrue(pid_file.exists())
            pid = int(pid_file.read_text())
            task.cancel()

            try:
                with self.assertRaises(ProtocolError):
                    await asyncio.wait_for(task, timeout=3)
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)
            finally:
                try:
                    os.kill(pid, 9)
                except ProcessLookupError:
                    pass

    @unittest.skipIf(os.name == "nt", "POSIX process-group behavior")
    async def test_task_cancellation_kills_descendant_holding_pipe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent_pid_file = root / "parent.pid"
            child_pid_file = root / "child.pid"
            executable = root / "claude-with-descendant"
            child = (
                "import os,pathlib,signal,time;"
                "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                "pathlib.Path(os.environ['TEST_CHILD_PID_FILE']).write_text(str(os.getpid()));"
                "time.sleep(30)"
            )
            executable.write_text(
                f"#!{sys.executable}\n"
                "import os, pathlib, subprocess, sys, time\n"
                f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
                "child_path = pathlib.Path(os.environ['TEST_CHILD_PID_FILE'])\n"
                "while not child_path.exists():\n"
                "    time.sleep(0.01)\n"
                "pathlib.Path(os.environ['TEST_PARENT_PID_FILE']).write_text(str(os.getpid()))\n"
                "time.sleep(30)\n"
            )
            executable.chmod(0o700)
            runtime = ClaudeCodeRuntimeClient(
                executable=str(executable),
                cwd=root,
                environment={
                    "TEST_PARENT_PID_FILE": str(parent_pid_file),
                    "TEST_CHILD_PID_FILE": str(child_pid_file),
                },
                default_timeout_seconds=None,
            )
            task = asyncio.create_task(
                anext(runtime.run(RunRequest("cancel-descendant", "question")))
            )
            for _ in range(200):
                if parent_pid_file.exists() and child_pid_file.exists():
                    break
                await asyncio.sleep(0.01)
            self.assertTrue(parent_pid_file.exists())
            self.assertTrue(child_pid_file.exists())
            parent_pid = int(parent_pid_file.read_text())
            child_pid = int(child_pid_file.read_text())
            task.cancel()

            try:
                await asyncio.sleep(2.5)
                self.assertTrue(task.done(), "cancellation blocked on a surviving descendant")
                with self.assertRaises(ProcessLookupError):
                    os.kill(child_pid, 0)
            finally:
                try:
                    os.killpg(parent_pid, 9)
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(task, timeout=3)
                except (ProtocolError, asyncio.CancelledError, asyncio.TimeoutError):
                    pass


if __name__ == "__main__":
    unittest.main()
