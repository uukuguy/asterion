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

from asterion.services.diagnostics import MemoryDiagnosticSink

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
        if message == "leading-settled":
            emit({"type": "agent_settled"})
            continue
        if message not in {"missing-ack", "late-ack"}:
            emit({"type": "response", "id": response_id, "success": True})
        emit({"type": "agent_start", "pid": os.getpid()})
        if message == "tool-blocking":
            emit({"type": "tool_execution_start", "toolCallId": "effect-1", "toolName": "ipython", "args": {}})
            with open(sys.argv[1] + ".effect", "w", encoding="utf-8") as marker:
                marker.write("effect remains after cancellation")
            emit({"type": "tool_execution_end", "toolCallId": "effect-1", "isError": False})
        if message in {"blocking", "tool-blocking"}:
            abort = json.loads(sys.stdin.readline())
            with open(sys.argv[1], "w", encoding="utf-8") as marker:
                marker.write(json.dumps(abort, separators=(",", ":")))
            time.sleep(60)
        if message == "retry-recovered":
            emit({"type": "message_end", "message": {"role": "assistant", "stopReason": "error", "errorMessage": "PRIVATE-RETRY-ERROR"}})
            emit({"type": "agent_end", "willRetry": True})
            emit({"type": "agent_start"})
            emit({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "recovered"}})
            emit({"type": "message_end", "message": {"role": "assistant", "stopReason": "stop"}})
            emit({"type": "agent_end", "willRetry": False})
            emit({"type": "agent_settled"})
            continue
        emit({
            "type": "message_update",
            "assistantMessageEvent": {"type": "text_delta", "delta": message},
        })
        if message in {"assistant-error", "assistant-aborted"}:
            emit({"type": "message_end", "message": {"role": "assistant", "stopReason": message.removeprefix("assistant-"), "errorMessage": "PRIVATE-ERROR"}})
        emit({"type": "agent_end", "messages": []})
        if message == "continuation":
            emit({"type": "agent_start"})
            emit({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": ":continued"}})
            emit({"type": "agent_end", "messages": []})
        if message == "late-ack":
            emit({"type": "response", "id": request["id"], "success": True})
        time.sleep(0.02)
        emit({"type": "agent_settled"})
        late_stderr = message == "late-stderr"
    elif request_type == "compact":
        emit({"type": "compaction_start", "reason": "manual"})
        if message == "reject-compact":
            emit({"type": "compaction_end", "reason": "manual", "aborted": True, "willRetry": False, "errorSeverity": "error"})
            emit({"type": "response", "id": request["id"], "command": "compact", "success": False, "error": "arbitrary private cancellation text"})
        else:
            result = {"summary": "private summary", "firstKeptEntryId": "entry-1", "tokensBefore": 100, "details": {}}
            emit({"type": "compaction_end", "reason": "manual", "result": result, "aborted": False, "willRetry": False})
            emit({"type": "response", "id": "wrong" if message == "compact-wrong-id" else request["id"], "command": "prompt" if message == "compact-wrong-command" else "compact", "success": True, "data": {} if message == "compact-wrong-result" else result})
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
    async def test_native_retry_can_recover_before_settlement(self) -> None:
        for compact_events in (False, True):
            with self.subTest(compact_events=compact_events):
                rpc = self.make_session(compact_events=compact_events)
                await rpc.open(signal=NeverCancelled())
                try:
                    result = await rpc.prompt(
                        "retry-recovered", signal=NeverCancelled(),
                        on_event=self.events.append,
                    )
                    self.assertEqual(result.final_text, "recovered")
                    self.assertFalse(rpc._lifecycle_poisoned)
                finally:
                    await rpc.close()

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

    def make_session(
        self, *, deadline_seconds: float | None = 2.0, compact_events: bool = False,
        diagnostics=None,
    ) -> PiRpcSession:
        return PiRpcSession(
            PiRpcConfig(
                (sys.executable, "-u", str(self.fake_rpc), str(self.abort_marker)),
                self.work,
                {},
                deadline_seconds=deadline_seconds,
                compact_events=compact_events,
            ),
            diagnostics=diagnostics,
        )

    async def test_explicit_no_deadline_keeps_reusable_commands_and_cancellation(self) -> None:
        rpc = self.make_session(deadline_seconds=None)
        await rpc.open(signal=NeverCancelled())
        self.addAsyncCleanup(rpc.close)
        self.assertIsNone(rpc._session_deadline)
        self.assertIsNotNone(rpc.validate_lifecycle(opened=True))
        for prompt in ("first", "second"):
            result = await rpc.prompt(prompt, signal=NeverCancelled(), on_event=self.events.append)
            self.assertEqual(result.final_text, prompt)
        await rpc.compact(signal=NeverCancelled(), on_event=self.events.append)
        signal = MutableSignal()
        pending = asyncio.create_task(rpc.prompt("blocking", signal=signal, on_event=self.events.append))
        await asyncio.sleep(0.05)
        signal.cancelled = True
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            await asyncio.wait_for(pending, 2)

    async def test_prompt_waits_for_settlement_after_agent_end(self) -> None:
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
            ["response", "agent_start", "message_update", "agent_end", "agent_settled"],
        )

    async def test_consecutive_prompts_own_their_settlement(self) -> None:
        rpc = self.make_session()
        await rpc.open(signal=NeverCancelled())
        self.addAsyncCleanup(rpc.close)

        results = []
        for stage in ("one", "two", "three"):
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
                "agent_settled",
            )
        self.assertEqual(
            [result.request_id for result in results], ["py-1", "py-2", "py-3"]
        )
        self.assertEqual(
            [event.sequence for event in self.events],
            list(range(1, len(self.events) + 1)),
        )

    async def test_prompt_boundaries_match_in_both_projection_modes(self) -> None:
        for compact_events in (False, True):
            with self.subTest(compact_events=compact_events):
                rpc = self.make_session(compact_events=compact_events)
                await rpc.open(signal=NeverCancelled())
                try:
                    events = []
                    for prompt in ("first", "continuation", "third", "late-ack"):
                        result = await rpc.prompt(prompt, signal=NeverCancelled(), on_event=events.append)
                        self.assertEqual(result.final_text, prompt + (":continued" if prompt == "continuation" else ""))
                        self.assertEqual(result.events[-1].type, "agent_settled")
                    self.assertEqual([event.sequence for event in events], list(range(1, len(events) + 1)))
                finally:
                    await rpc.close()

    async def test_missing_ack_and_native_failure_never_complete(self) -> None:
        for compact_events in (False, True):
            for prompt in ("leading-settled", "missing-ack", "assistant-error", "assistant-aborted"):
                with self.subTest(compact_events=compact_events, prompt=prompt):
                    rpc = self.make_session(deadline_seconds=0.3, compact_events=compact_events)
                    await rpc.open(signal=NeverCancelled())
                    try:
                        with self.assertRaises(RuntimeError) as caught:
                            await rpc.prompt(prompt, signal=NeverCancelled(), on_event=lambda event: None)
                        self.assertNotIn("PRIVATE-ERROR", str(caught.exception))
                        with self.assertRaisesRegex(RuntimeError, "poisoned"):
                            await rpc.prompt("never-sent", signal=NeverCancelled(), on_event=lambda event: None)
                    finally:
                        await rpc.close()

    async def test_prompt_failure_records_private_diagnostic_without_payload(self) -> None:
        sink = MemoryDiagnosticSink()
        rpc = self.make_session(deadline_seconds=0.3, diagnostics=sink)
        await rpc.open(signal=NeverCancelled())
        try:
            with self.assertRaises(RuntimeError) as caught:
                await rpc.prompt(
                    "assistant-error", signal=NeverCancelled(), on_event=lambda event: None
                )
            diagnostic_id = rpc.last_diagnostic_id
            self.assertIsNotNone(diagnostic_id)
            record = sink.get(diagnostic_id)
            self.assertEqual(record.stage, "pi.prompt")
            self.assertNotIn("PRIVATE-ERROR", repr(record))
            self.assertNotIn("assistant-error", repr(record))
            self.assertNotIn("PRIVATE-ERROR", str(caught.exception))
        finally:
            await rpc.close()

    async def test_compact_semantics_match_in_both_projection_modes(self) -> None:
        for compact_events in (False, True):
            for prompt in ("normal", "reject-compact"):
                with self.subTest(compact_events=compact_events, prompt=prompt):
                    rpc = self.make_session(compact_events=compact_events)
                    await rpc.open(signal=NeverCancelled())
                    try:
                        await rpc.prompt(prompt, signal=NeverCancelled(), on_event=lambda event: None)
                        result = await rpc.compact(signal=NeverCancelled(), on_event=lambda event: None)
                        self.assertEqual(result.outcome, "aborted" if prompt == "reject-compact" else "completed")
                        self.assertEqual(set(result.events[-1].payload), {"id", "success"})
                    finally:
                        await rpc.close()

    async def test_invalid_compact_wire_responses_fail_in_both_modes(self) -> None:
        for compact_events in (False, True):
            for prompt in ("compact-wrong-id", "compact-wrong-command", "compact-wrong-result"):
                with self.subTest(compact_events=compact_events, prompt=prompt):
                    rpc = self.make_session(compact_events=compact_events)
                    await rpc.open(signal=NeverCancelled())
                    try:
                        await rpc.prompt(prompt, signal=NeverCancelled(), on_event=lambda event: None)
                        with self.assertRaises(RuntimeError):
                            await rpc.compact(signal=NeverCancelled(), on_event=lambda event: None)
                        with self.assertRaisesRegex(RuntimeError, "poisoned"):
                            await rpc.prompt("never-sent", signal=NeverCancelled(), on_event=lambda event: None)
                    finally:
                        await rpc.close()

    async def test_unowned_queued_event_fences_before_another_prompt(self) -> None:
        rpc = self.make_session()
        await rpc.open(signal=NeverCancelled())
        self.addAsyncCleanup(rpc.close)
        await rpc.prompt("first", signal=NeverCancelled(), on_event=lambda event: None)
        assert rpc._state is not None
        rpc._state.stdout_queue.put({"type": "agent_settled"})
        with patch.object(rpc, "send", wraps=rpc.send) as send:
            with self.assertRaisesRegex(RuntimeError, "unowned"):
                await rpc.prompt("never-sent", signal=NeverCancelled(), on_event=lambda event: None)
        send.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, "poisoned"):
            await rpc.prompt("never-sent", signal=NeverCancelled(), on_event=lambda event: None)

    async def test_prompt_compact_prompt_reuses_one_process(self) -> None:
        rpc = self.make_session(compact_events=True)
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

    async def test_cancellation_after_tool_effect_fences_without_rollback(self) -> None:
        rpc = self.make_session()
        signal = MutableSignal()
        await rpc.open(signal=NeverCancelled())
        self.addAsyncCleanup(rpc.close)

        def cancel_after_effect(event) -> None:
            if event.type == "tool_execution_end":
                signal.cancelled = True

        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            await rpc.prompt("tool-blocking", signal=signal, on_event=cancel_after_effect)
        with self.assertRaisesRegex(RuntimeError, "poisoned"):
            await rpc.prompt("never-sent", signal=NeverCancelled(), on_event=lambda event: None)
        await rpc.close()
        self.assertEqual(Path(str(self.abort_marker) + ".effect").read_text(), "effect remains after cancellation")

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
        rpc = self.make_session(compact_events=True)
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
        self.assertEqual([event.sequence for event in result.events], [1, 2, 3, 4, 5])
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
