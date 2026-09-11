from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

from asterion.runtimes.pi_rpc import (
    CancellationSignal,
    PiRpcConfig,
    PiRpcResult,
    PiRpcSession,
)


_FAKE_REUSABLE_PI = r"""
import json
import os
import sys
import time

def emit(value):
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()

late_stderr = False

for line in sys.stdin:
    request = json.loads(line)
    request_type = request["type"]
    if request_type == "prompt":
        message = request["message"]
        response_id = "wrong" if message == "mismatch" else request["id"]
        emit({"type": "response", "id": response_id, "success": True})
        emit({"type": "agent_start", "pid": os.getpid()})
        if message == "blocking":
            abort = json.loads(sys.stdin.readline())
            with open(sys.argv[1], "w", encoding="utf-8") as marker:
                marker.write(json.dumps(abort, separators=(",", ":")))
            time.sleep(60)
        emit({
            "type": "message_update",
            "assistantMessageEvent": {"type": "text_delta", "delta": message},
        })
        emit({"type": "agent_end", "messages": []})
        late_stderr = message == "late-stderr"
    elif request_type == "compact":
        emit({"type": "compaction_start", "reason": "manual"})
        if message == "reject-compact":
            emit({"type": "compaction_end", "reason": "manual", "aborted": True, "willRetry": False, "errorSeverity": "error"})
            emit({"type": "response", "id": request["id"], "command": "compact", "success": False, "error": "arbitrary private cancellation text"})
        else:
            result = {"summary": "private summary", "firstKeptEntryId": "entry-1", "tokensBefore": 100, "details": {}}
            emit({"type": "compaction_end", "reason": "manual", "result": result, "aborted": False, "willRetry": False})
            emit({"type": "response", "id": request["id"], "command": "compact", "success": True, "data": result})
    elif request_type == "abort":
        break
    else:
        raise AssertionError(request_type)

if late_stderr:
    sys.stderr.write("late stderr\n")
    sys.stderr.flush()
"""


@dataclass
class MutableSignal:
    cancelled: bool = False


class NeverCancelled:
    @property
    def cancelled(self) -> bool:
        return False


class CallbackFailure(BaseException):
    pass


class PiRpcReusableTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self._cleanup_temporary)
        self.work = Path(self.temporary.name).resolve()
        self.fake_rpc = self.work / "fake_reusable_pi.py"
        self.fake_rpc.write_text(_FAKE_REUSABLE_PI, encoding="utf-8")
        self.abort_marker = self.work / "abort.json"
        self.events = []

    async def _cleanup_temporary(self) -> None:
        self.temporary.cleanup()

    def make_session(self, *, deadline_seconds: float = 2.0) -> PiRpcSession:
        return PiRpcSession(
            PiRpcConfig(
                (sys.executable, "-u", str(self.fake_rpc), str(self.abort_marker)),
                self.work,
                {},
                deadline_seconds=deadline_seconds,
            )
        )

    async def test_prompt_completes_on_default_agent_end_terminal(self) -> None:
        rpc = self.make_session(deadline_seconds=0.2)
        await rpc.open(signal=NeverCancelled())
        self.addAsyncCleanup(rpc.close)

        result = await rpc.prompt(
            "selected-default-terminal",
            signal=NeverCancelled(),
            on_event=self.events.append,
        )

        self.assertEqual(result.final_text, "selected-default-terminal")
        self.assertEqual(
            [event.type for event in result.events],
            ["response", "agent_start", "message_update", "agent_end"],
        )

    async def test_consecutive_prompts_complete_on_agent_end_terminal(self) -> None:
        rpc = self.make_session()
        await rpc.open(signal=NeverCancelled())
        self.addAsyncCleanup(rpc.close)

        results = []
        for stage in ("one", "two"):
            results.append(
                await rpc.prompt(
                    f"paired-terminal-{stage}",
                    signal=NeverCancelled(),
                    on_event=self.events.append,
                )
            )

        for result in results:
            self.assertEqual(
                result.events[-1].type,
                "agent_end",
            )
        self.assertEqual(
            [result.request_id for result in results], ["py-1", "py-2"]
        )
        self.assertEqual(
            [event.sequence for event in self.events],
            list(range(1, len(self.events) + 1)),
        )

    async def test_prompt_compact_prompt_reuses_one_process(self) -> None:
        rpc = self.make_session()
        await rpc.open(signal=NeverCancelled())
        self.addAsyncCleanup(rpc.close)
        assert rpc.process is not None
        pid = rpc.process.pid

        first = await rpc.prompt(
            "stage-one", signal=NeverCancelled(), on_event=self.events.append
        )
        compact = await rpc.compact(
            signal=NeverCancelled(), on_event=self.events.append
        )
        second = await rpc.prompt(
            "stage-two", signal=NeverCancelled(), on_event=self.events.append
        )

        assert rpc.process is not None
        self.assertEqual(rpc.process.pid, pid)
        self.assertEqual(
            [event.sequence for event in self.events],
            list(range(1, len(self.events) + 1)),
        )
        self.assertEqual(
            (first.request_id, compact.request_id, second.request_id),
            ("py-1", "py-2", "py-3"),
        )
        self.assertEqual(first.final_text, "stage-one")
        self.assertEqual(second.final_text, "stage-two")
        self.assertEqual(compact.rpc_type, "compact")
        self.assertEqual(
            [event.type for event in compact.events],
            ["compaction_start", "compaction_end", "response"],
        )

        await rpc.close()
        self.assertIsNone(rpc.process)

    async def test_session_deadline_is_absolute_and_prewrite_timeout_is_recoverable(
        self,
    ) -> None:
        rpc = self.make_session(deadline_seconds=1.0)
        now = [100.0]
        with patch(
            "asterion.runtimes.pi_rpc.time",
            SimpleNamespace(monotonic=lambda: now[0]),
        ):
            await rpc.open(signal=NeverCancelled())
            self.addAsyncCleanup(rpc.close)
            first = await rpc.prompt(
                "first", signal=NeverCancelled(), on_event=lambda _event: None
            )
            now[0] = 101.0
            with self.assertRaisesRegex(RuntimeError, "timed out after 1 seconds"):
                await rpc.compact(signal=NeverCancelled(), on_event=lambda _event: None)
            with self.assertRaisesRegex(RuntimeError, "timed out after 1 seconds"):
                await rpc.prompt(
                    "second", signal=NeverCancelled(), on_event=lambda _event: None
                )

        self.assertEqual(first.request_id, "py-1")

    async def test_inflight_prompt_does_not_rebase_the_session_deadline(self) -> None:
        rpc = self.make_session(deadline_seconds=1.0)
        now = [100.0]
        with patch(
            "asterion.runtimes.pi_rpc.time",
            SimpleNamespace(monotonic=lambda: now[0]),
        ):
            await rpc.open(signal=NeverCancelled())
            self.addAsyncCleanup(rpc.close)
            now[0] = 100.75

            def exhaust_deadline(event) -> None:
                if event.type == "agent_start":
                    now[0] = 101.0

            with self.assertRaisesRegex(RuntimeError, "timed out after 1 seconds"):
                await rpc.prompt(
                    "late", signal=NeverCancelled(), on_event=exhaust_deadline
                )

        with self.assertRaisesRegex(RuntimeError, "poisoned"):
            await rpc.compact(signal=NeverCancelled(), on_event=lambda _event: None)

    async def test_cancellation_after_dispatch_poisons_until_close(self) -> None:
        rpc = self.make_session()
        signal = MutableSignal()
        await rpc.open(signal=NeverCancelled())
        self.addAsyncCleanup(rpc.close)

        def cancel_after_dispatch(event) -> None:
            if event.type == "agent_start":
                signal.cancelled = True

        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            await rpc.prompt("blocking", signal=signal, on_event=cancel_after_dispatch)
        with self.assertRaisesRegex(RuntimeError, "poisoned"):
            await rpc.prompt(
                "never-sent", signal=NeverCancelled(), on_event=lambda _event: None
            )
        abort = json.loads(self.abort_marker.read_text(encoding="utf-8"))
        self.assertEqual(abort["type"], "abort")

        await rpc.close()
        self.assertIsNone(rpc.process)

    async def test_cancelled_pre_dispatch_prompt_leaves_session_reusable(self) -> None:
        rpc = self.make_session()
        driver_started = threading.Event()
        release_driver = threading.Event()
        original_drive = rpc.drive_prompt
        await rpc.open(signal=NeverCancelled())
        self.addAsyncCleanup(rpc.close)

        def gated_drive(*args: object, **kwargs: object) -> object:
            driver_started.set()
            release_driver.wait()
            return original_drive(*args, **kwargs)  # type: ignore[arg-type]

        with (
            patch.object(rpc, "drive_prompt", side_effect=gated_drive),
            patch.object(rpc, "send", wraps=rpc.send) as send,
        ):
            task = asyncio.create_task(
                rpc.prompt(
                    "cancelled", signal=NeverCancelled(), on_event=lambda _event: None
                )
            )
            await asyncio.wait_for(asyncio.to_thread(driver_started.wait), timeout=1.0)
            task.cancel()
            await asyncio.sleep(0)
            release_driver.set()
            with self.assertRaises(asyncio.CancelledError):
                await task

            self.assertEqual(send.call_count, 0)
            result = await rpc.prompt(
                "recovered", signal=NeverCancelled(), on_event=lambda _event: None
            )

        self.assertEqual(result.final_text, "recovered")

    async def test_concurrent_command_is_rejected_without_dispatch(self) -> None:
        rpc = self.make_session()
        signal = MutableSignal()
        started = asyncio.Event()
        await rpc.open(signal=NeverCancelled())
        self.addAsyncCleanup(rpc.close)

        first = asyncio.create_task(
            rpc.prompt(
                "blocking",
                signal=signal,
                on_event=lambda event: (
                    started.set() if event.type == "agent_start" else None
                ),
            )
        )
        await asyncio.wait_for(started.wait(), timeout=1.0)
        with self.assertRaisesRegex(RuntimeError, "active command"):
            await rpc.compact(signal=NeverCancelled(), on_event=lambda _event: None)
        signal.cancelled = True
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            await first

    async def test_response_identity_failure_poisons_session(self) -> None:
        rpc = self.make_session()
        await rpc.open(signal=NeverCancelled())
        self.addAsyncCleanup(rpc.close)

        with self.assertRaisesRegex(RuntimeError, "response did not match"):
            await rpc.prompt(
                "mismatch", signal=NeverCancelled(), on_event=lambda _event: None
            )
        with self.assertRaisesRegex(RuntimeError, "poisoned"):
            await rpc.compact(signal=NeverCancelled(), on_event=lambda _event: None)

    async def test_callback_base_exception_after_dispatch_poisons_session(self) -> None:
        rpc = self.make_session()
        await rpc.open(signal=NeverCancelled())
        self.addAsyncCleanup(rpc.close)

        def fail_callback(_event) -> None:
            raise CallbackFailure("callback failed")

        with self.assertRaisesRegex(CallbackFailure, "callback failed"):
            await rpc.prompt(
                "callback", signal=NeverCancelled(), on_event=fail_callback
            )
        with self.assertRaisesRegex(RuntimeError, "poisoned"):
            await rpc.compact(signal=NeverCancelled(), on_event=lambda _event: None)

    async def test_second_task_cancellation_keeps_driver_owned_until_quiescent(
        self,
    ) -> None:
        rpc = self.make_session()
        driver_started = threading.Event()
        cleanup_started = threading.Event()
        release_driver = threading.Event()
        await rpc.open(signal=NeverCancelled())
        self.addAsyncCleanup(rpc.close)

        def slow_driver(*_args: object, **kwargs: object) -> None:
            on_request_written = kwargs["on_request_written"]
            signal = cast(CancellationSignal, kwargs["signal"])
            assert callable(on_request_written)
            on_request_written()
            driver_started.set()
            while not signal.cancelled:
                time.sleep(0.01)
            cleanup_started.set()
            release_driver.wait()

        with patch.object(rpc, "drive_prompt", side_effect=slow_driver):
            task = asyncio.create_task(
                rpc.prompt(
                    "blocking", signal=NeverCancelled(), on_event=lambda _event: None
                )
            )
            await asyncio.wait_for(asyncio.to_thread(driver_started.wait), timeout=1.0)
            task.cancel()
            await asyncio.wait_for(asyncio.to_thread(cleanup_started.wait), timeout=1.0)
            task.cancel()
            try:
                await asyncio.sleep(0)

                self.assertFalse(task.done())
                with patch.object(
                    rpc,
                    "read_json_line",
                    side_effect=AssertionError("competing reader"),
                ):
                    with self.assertRaisesRegex(RuntimeError, "active command"):
                        await rpc.compact(
                            signal=NeverCancelled(), on_event=lambda _event: None
                        )
            finally:
                release_driver.set()
                if not task.done():
                    with self.assertRaises(asyncio.CancelledError):
                        await task

            with self.assertRaisesRegex(RuntimeError, "poisoned"):
                await rpc.compact(signal=NeverCancelled(), on_event=lambda _event: None)

    async def test_prompt_send_that_transmits_then_raises_poisons_session(self) -> None:
        rpc = self.make_session()
        await rpc.open(signal=NeverCancelled())
        self.addAsyncCleanup(rpc.close)
        original_send = rpc.send

        def transmit_then_raise(payload: object) -> None:
            original_send(payload)  # type: ignore[arg-type]
            raise OSError("flush failed after dispatch")

        with patch.object(rpc, "send", side_effect=transmit_then_raise):
            with self.assertRaisesRegex(OSError, "flush failed after dispatch"):
                await rpc.prompt(
                    "first", signal=NeverCancelled(), on_event=lambda _event: None
                )

        with self.assertRaisesRegex(RuntimeError, "poisoned"):
            await rpc.prompt(
                "never-sent", signal=NeverCancelled(), on_event=lambda _event: None
            )

    async def test_compact_send_that_transmits_then_raises_poisons_session(
        self,
    ) -> None:
        rpc = self.make_session()
        await rpc.open(signal=NeverCancelled())
        self.addAsyncCleanup(rpc.close)
        original_send = rpc.send

        def transmit_then_raise(payload: object) -> None:
            original_send(payload)  # type: ignore[arg-type]
            raise OSError("flush failed after dispatch")

        with patch.object(rpc, "send", side_effect=transmit_then_raise):
            with self.assertRaisesRegex(OSError, "flush failed after dispatch"):
                await rpc.compact(signal=NeverCancelled(), on_event=lambda _event: None)

        with self.assertRaisesRegex(RuntimeError, "poisoned"):
            await rpc.compact(signal=NeverCancelled(), on_event=lambda _event: None)

    async def test_close_is_idempotent_and_stops_once(self) -> None:
        rpc = self.make_session()
        await rpc.open(signal=NeverCancelled())
        with patch.object(rpc, "stop", wraps=rpc.stop) as stop:
            await rpc.close()
            await rpc.close()
        self.assertEqual(stop.call_count, 1)
        self.assertIsNone(rpc.process)

    async def test_aborted_compact_needs_exact_typed_settlement_before_reuse(self):
        rpc = self.make_session()
        await rpc.open(signal=NeverCancelled())
        self.addAsyncCleanup(rpc.close)
        await rpc.prompt(
            "reject-compact", signal=NeverCancelled(), on_event=lambda _: None
        )
        result = await rpc.compact(signal=NeverCancelled(), on_event=lambda _: None)
        self.assertEqual(result.outcome, "aborted")
        with self.assertRaises(RuntimeError):
            rpc.validate_lifecycle(opened=True)
        with self.assertRaises(RuntimeError):
            await rpc.prompt(
                "forbidden", signal=NeverCancelled(), on_event=lambda _: None
            )
        from dataclasses import replace

        with self.assertRaises(RuntimeError):
            rpc.settle_rejected_compact(replace(result))
        rpc.settle_rejected_compact(result)
        rpc.validate_lifecycle(opened=True)
        second = await rpc.prompt(
            "continued", signal=NeverCancelled(), on_event=lambda _: None
        )
        self.assertEqual(second.final_text, "continued")

    async def test_lifecycle_validation_rejects_closed_or_dead_process(self):
        rpc = self.make_session()
        self.assertIsNone(rpc.validate_lifecycle(opened=False))
        await rpc.open(signal=NeverCancelled())
        self.addAsyncCleanup(rpc.close)
        identity = rpc.validate_lifecycle(opened=True)
        self.assertIsNotNone(identity)
        self.assertIs(identity, rpc.validate_lifecycle(opened=True))
        rpc.process.kill()
        await asyncio.to_thread(rpc.process.wait)
        with self.assertRaises(RuntimeError):
            rpc.validate_lifecycle(opened=True)
        await rpc.close()
        with self.assertRaises(RuntimeError):
            rpc.validate_lifecycle(opened=True)

    async def test_legacy_run_remains_one_shot_and_hides_request_identity(self) -> None:
        rpc = self.make_session()
        result = await rpc.run(
            "legacy", signal=NeverCancelled(), on_event=self.events.append
        )

        self.assertIs(type(result), PiRpcResult)
        self.assertEqual(result.final_text, "legacy")
        self.assertIsNone(result.request_id)
        self.assertEqual([event.sequence for event in result.events], [1, 2, 3, 4])
        self.assertIsNone(rpc.process)

    async def test_legacy_run_rejects_close_between_open_and_prompt(self) -> None:
        rpc = self.make_session()
        prompt_entered = asyncio.Event()
        release_prompt = asyncio.Event()
        original_prompt = rpc.prompt

        async def delayed_prompt(*args: object, **kwargs: object) -> PiRpcResult:
            prompt_entered.set()
            await release_prompt.wait()
            return await original_prompt(*args, **kwargs)  # type: ignore[arg-type]

        with patch.object(rpc, "prompt", side_effect=delayed_prompt):
            task = asyncio.create_task(
                rpc.run("legacy", signal=NeverCancelled(), on_event=lambda _event: None)
            )
            await asyncio.wait_for(prompt_entered.wait(), timeout=1.0)

            close_rejected = False
            try:
                with self.assertRaisesRegex(RuntimeError, "active command"):
                    await rpc.close()
                close_rejected = True
            finally:
                release_prompt.set()
                if not close_rejected:
                    try:
                        await task
                    except BaseException:
                        pass

            result = await task

        self.assertEqual(result.final_text, "legacy")
        self.assertIsNone(rpc.process)

    async def test_legacy_run_returns_stderr_drained_during_close(self) -> None:
        rpc = self.make_session()

        result = await rpc.run(
            "late-stderr", signal=NeverCancelled(), on_event=lambda _event: None
        )

        self.assertEqual(result.stderr, b"late stderr\n")


if __name__ == "__main__":
    unittest.main()
