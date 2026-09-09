from __future__ import annotations

import asyncio
import contextvars
import io
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from asterion.runtimes.pi_rpc import (
    PiRpcConfig,
    PiRpcEvent,
    PiRpcResult,
    PiRpcSession,
    normalize_pi_usage,
)


_FAKE_PI = r"""
import json
import signal
import sys
import time

mode = sys.argv[1]

def emit(value):
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()

request = json.loads(sys.stdin.readline())
if mode == "malformed":
    sys.stdout.write("{not-json}\n")
    sys.stdout.flush()
elif mode == "eof":
    pass
elif mode == "mismatch":
    emit({"type": "response", "id": "wrong", "success": True})
elif mode == "no-ack":
    emit({"type": "agent_settled"})
elif mode == "agent-end":
    emit({"type": "response", "id": request["id"], "success": True})
    emit({"type": "agent_end"})
elif mode == "oversized":
    sys.stdout.write(" " * (1024 * 1024 + 1) + "\n")
    sys.stdout.flush()
elif mode == "final-oversized":
    emit({"type": "response", "id": request["id"], "success": True})
    for _ in range(33):
        emit({
            "type": "message_update",
            "assistantMessageEvent": {
                "type": "text_delta",
                "delta": "x" * (32 * 1024),
            },
        })
    emit({"type": "agent_settled"})
elif mode == "stderr-oversized":
    sys.stderr.write("x" * (64 * 1024 + 1))
    sys.stderr.flush()
    emit({"type": "response", "id": request["id"], "success": True})
    emit({"type": "agent_settled"})
elif mode == "stdout-total-oversized":
    emit({"type": "response", "id": request["id"], "success": True})
    for _ in range(513):
        emit({"type": "progress", "padding": "x" * (32 * 1024)})
    emit({"type": "agent_settled"})
elif mode == "event-count-oversized":
    emit({"type": "response", "id": request["id"], "success": True})
    for index in range(65536):
        emit({"type": "progress", "index": index})
    emit({"type": "agent_settled"})
elif mode == "deadline":
    emit({"type": "response", "id": request["id"], "success": True})
    time.sleep(60)
elif mode == "ignore-term":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    emit({"type": "response", "id": request["id"], "success": True})
    while True:
        time.sleep(1)
elif mode == "cancel":
    emit({"type": "response", "id": request["id"], "success": True})
    emit({"type": "agent_start"})
    abort = json.loads(sys.stdin.readline())
    Path = __import__("pathlib").Path
    Path(sys.argv[2]).write_text(abort["type"], encoding="utf-8")
    time.sleep(60)
elif mode == "ack-settled":
    emit({"type": "response", "id": request["id"], "success": True})
    emit({"type": "agent_start", "attempt": 1})
    emit({
        "type": "message_update",
        "assistantMessageEvent": {"type": "text_delta", "delta": "do"},
    })
    emit({
        "type": "message_update",
        "assistantMessageEvent": {"type": "text_delta", "delta": "ne"},
    })
    emit({"type": "agent_settled", "state": {"idle": True}})
else:
    raise AssertionError(mode)
"""


@dataclass
class FakeSignal:
    cancelled: bool


class _StuckThread:
    def __init__(self, **_kwargs: object) -> None:
        pass

    def start(self) -> None:
        pass

    def join(self, timeout: float | None = None) -> None:
        del timeout

    def is_alive(self) -> bool:
        return True


class _ExitedProcess:
    def __init__(self) -> None:
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO()
        self.stderr = io.BytesIO()

    def poll(self) -> int:
        return 0


class PiRpcSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name).resolve()
        self.fake = self.work / "fake_pi.py"
        self.fake.write_text(_FAKE_PI, encoding="utf-8")

    def command(self, mode: str, *args: str) -> tuple[str, ...]:
        return (sys.executable, "-u", str(self.fake), mode, *args)

    def test_normalize_pi_usage_projects_public_runtime_fields(self) -> None:
        self.assertEqual(
            normalize_pi_usage(
                {
                    "message": {
                        "role": "assistant",
                        "usage": {"input": 120, "output": 31},
                    }
                }
            ),
            {"input_tokens": 120, "output_tokens": 31},
        )
        self.assertIsNone(normalize_pi_usage({"message": {"role": "user"}}))
        with self.assertRaisesRegex(ValueError, "Pi usage event is invalid"):
            normalize_pi_usage(
                {
                    "message": {
                        "role": "assistant",
                        "usage": {"input": True, "output": 1},
                    }
                }
            )

    def collect(
        self,
        mode: str,
        *,
        signal: FakeSignal | None = None,
        deadline_seconds: float = 2.0,
        args: tuple[str, ...] = (),
        on_event=None,
        compact_events: bool = False,
    ) -> PiRpcResult:
        session = PiRpcSession(
            PiRpcConfig(
                command=self.command(mode, *args),
                cwd=self.work,
                environment={},
                deadline_seconds=deadline_seconds,
                compact_events=compact_events,
            )
        )
        return asyncio.run(
            session.run(
                "inspect",
                signal=signal or FakeSignal(False),
                on_event=on_event or (lambda event: None),
            )
        )

    def test_rpc_requires_ack_and_settled_terminal(self) -> None:
        observed = []
        result = self.collect("ack-settled", on_event=observed.append)

        self.assertEqual(result.final_text, "done")
        self.assertEqual(
            [event.type for event in result.events],
            [
                "response",
                "agent_start",
                "message_update",
                "message_update",
                "agent_settled",
            ],
        )
        self.assertEqual(result.events, tuple(observed))
        self.assertEqual([event.sequence for event in result.events], [1, 2, 3, 4, 5])
        self.assertEqual(result.stderr, b"")

    def test_compact_projection_retains_final_text_without_emitting_deltas(self) -> None:
        result = self.collect("ack-settled", compact_events=True)

        self.assertEqual(result.final_text, "done")
        self.assertEqual(
            [event.type for event in result.events],
            ["response", "agent_start", "agent_settled"],
        )

    def test_async_callbacks_run_on_calling_loop_thread_and_context(self) -> None:
        calling_thread = threading.get_ident()
        context = contextvars.ContextVar("pi_rpc_test_context")
        token = context.set("caller-context")
        observed: list[tuple[int, str]] = []
        try:
            self.collect(
                "ack-settled",
                on_event=lambda event: observed.append(
                    (threading.get_ident(), context.get())
                ),
            )
        finally:
            context.reset(token)

        self.assertTrue(observed)
        self.assertEqual({thread for thread, _value in observed}, {calling_thread})
        self.assertEqual({value for _thread, value in observed}, {"caller-context"})

    def test_async_cancellation_waits_for_prompt_driver_to_quiesce(self) -> None:
        async def exercise() -> None:
            marker = self.work / "abort-driver"
            session = PiRpcSession(
                PiRpcConfig(
                    command=self.command("cancel", str(marker)),
                    cwd=self.work,
                    environment={},
                    deadline_seconds=2.0,
                )
            )
            callback_seen = threading.Event()
            driver_exited = threading.Event()
            original_drive = session.drive_prompt

            def tracked_drive(*args: object, **kwargs: object) -> object:
                try:
                    return original_drive(*args, **kwargs)  # type: ignore[arg-type]
                finally:
                    time.sleep(0.3)
                    driver_exited.set()

            with patch.object(session, "drive_prompt", side_effect=tracked_drive):
                task = asyncio.create_task(
                    session.run(
                        "inspect",
                        signal=FakeSignal(False),
                        on_event=lambda event: callback_seen.set(),
                    )
                )
                for _ in range(100):
                    if callback_seen.is_set():
                        break
                    await asyncio.sleep(0.01)
                self.assertTrue(callback_seen.is_set())
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task

            self.assertTrue(driver_exited.is_set())
            self.assertIsNone(session.process)
            self.assertFalse(session._run_active)

        asyncio.run(exercise())

    def test_results_are_immutable_copies(self) -> None:
        environment = {"VISIBLE": "before"}
        config = PiRpcConfig(
            command=self.command("ack-settled"),
            cwd=self.work,
            environment=environment,
            deadline_seconds=2.0,
        )
        environment["VISIBLE"] = "after"
        result = asyncio.run(
            PiRpcSession(config).run(
                "inspect", signal=FakeSignal(False), on_event=lambda event: None
            )
        )

        self.assertEqual(config.environment["VISIBLE"], "before")
        with self.assertRaises(TypeError):
            config.environment["VISIBLE"] = "changed"  # type: ignore[index]
        with self.assertRaises(TypeError):
            result.events[-1].payload["state"] = {}  # type: ignore[index]
        state = result.events[-1].payload["state"]
        with self.assertRaises(TypeError):
            state["idle"] = False  # type: ignore[index]

    def test_events_reject_non_json_mutable_leaves(self) -> None:
        for value in (bytearray(b"mutable"), {"mutable"}, object()):
            with (
                self.subTest(value_type=type(value).__name__),
                self.assertRaisesRegex(ValueError, "payload"),
            ):
                PiRpcEvent(1, "event", {"value": value})

    def test_malformed_json_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "invalid JSONL"):
            self.collect("malformed")

    def test_unexpected_eof_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "exited unexpectedly"):
            self.collect("eof")

    def test_response_id_mismatch_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "response did not match"):
            self.collect("mismatch")

    def test_settled_before_ack_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "before prompt acknowledgement"):
            self.collect("no-ack")

    def test_agent_end_is_accepted_as_native_terminal(self) -> None:
        result = self.collect("agent-end")

        self.assertEqual([event.type for event in result.events], ["response", "agent_end"])

    def test_stdout_line_cap_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "output limit"):
            self.collect("oversized")

    def test_final_text_cap_truncates_without_breaking_terminal(self) -> None:
        result = self.collect("final-oversized")

        self.assertLessEqual(len(result.final_text.encode("utf-8")), 1024 * 1024)
        self.assertEqual(result.events[-1].type, "agent_settled")

    def test_stderr_cap_fails_closed_even_when_stdout_settles(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "output limit"):
            self.collect("stderr-oversized")

    def test_aggregate_stdout_byte_cap_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "output limit"):
            self.collect("stdout-total-oversized")

    def test_event_count_cap_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "output limit"):
            self.collect("event-count-oversized", deadline_seconds=10.0)

    def test_command_arguments_are_passed_literally(self) -> None:
        marker = self.work / "shell-was-used"
        result = self.collect("ack-settled", args=(f"; touch {marker}",))
        self.assertEqual(result.final_text, "done")
        self.assertFalse(marker.exists())

    def test_deadline_aborts_the_prompt(self) -> None:
        started = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            self.collect("deadline", deadline_seconds=0.05)
        self.assertLess(time.monotonic() - started, 2.0)

    def test_cancellation_before_start_does_not_launch(self) -> None:
        marker = self.work / "not-launched"
        command = (
            sys.executable,
            "-c",
            f"from pathlib import Path; Path({str(marker)!r}).touch()",
        )
        session = PiRpcSession(
            PiRpcConfig(command, self.work, {}, deadline_seconds=2.0)
        )
        with self.assertRaisesRegex(RuntimeError, "cancelled before start"):
            asyncio.run(
                session.run(
                    "inspect",
                    signal=FakeSignal(True),
                    on_event=lambda event: None,
                )
            )
        self.assertFalse(marker.exists())

    def test_cancellation_during_prompt_sends_abort_and_cleans_up(self) -> None:
        marker = self.work / "abort"
        signal = FakeSignal(False)

        def cancel_after_start(event) -> None:
            if event.type == "agent_start":
                signal.cancelled = True

        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            self.collect(
                "cancel",
                signal=signal,
                args=(str(marker),),
                on_event=cancel_after_start,
            )
        self.assertEqual(marker.read_text(encoding="utf-8"), "abort")

    def test_cleanup_is_bounded_when_process_ignores_terminate(self) -> None:
        started = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            self.collect("ignore-term", deadline_seconds=0.05)
        self.assertLess(time.monotonic() - started, 2.0)

    def test_unresolved_reader_cleanup_is_reported_and_blocks_state_reuse(
        self,
    ) -> None:
        process = _ExitedProcess()
        session = PiRpcSession(
            PiRpcConfig(("fake",), self.work, {}, deadline_seconds=1.0),
            _popen=lambda *_args, **_kwargs: process,  # type: ignore[arg-type]
            _thread_factory=_StuckThread,  # type: ignore[arg-type]
        )
        session.start()

        started = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, "cleanup.*timed out"):
            session.stop()
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertIs(session.process, process)
        with self.assertRaisesRegex(RuntimeError, "already started"):
            session.start()


if __name__ == "__main__":
    unittest.main()
