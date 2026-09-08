from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
import unittest

from asterion.applications.prime_agent.operator.p7_solving_broker_service import (
    P7SolvingBrokerServiceError,
)
from asterion.services.progress import HostProgressEvent


class _Progress:
    def __init__(self) -> None:
        self.events: list[HostProgressEvent] = []

    def emit(self, event: HostProgressEvent) -> None:
        self.events.append(event)


class _Sink:
    def __init__(self, log: list[str]) -> None:
        self.records: list[str] = []
        self.log = log

    def write(self, text: str) -> None:
        self.records.append(text)
        if not self.log or self.log[-1] != "presentation":
            self.log.append("presentation")


class _StoreProbe:
    def __init__(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_host import (
            P7SolvingReceiptStore,
        )

        self.value = P7SolvingReceiptStore()


class _Broker:
    def __init__(self, log: list[str], *, terminal_reason: str = "level-completed") -> None:
        self.log = log
        self.terminal_reason = terminal_reason
        self.action_count = 0
        self.solved = False

    def start(self) -> bytes:
        self.log.append("broker:start")
        return b"client"

    def seal(self) -> dict[str, object]:
        self.log.append("broker:seal")
        if self.action_count == 0 or (not self.solved and self.terminal_reason == "level-completed"):
            raise P7SolvingBrokerServiceError()
        completed = 1 if self.solved else 0
        return {
            "action_count": self.action_count,
            "levels_completed": completed,
            "score": "3.571429" if completed else "0.000000",
            "score_sha256": "sha256:" + "a" * 64,
            "terminal_reason": self.terminal_reason,
            "transcript_sha256": "sha256:" + "b" * 64,
        }

    def replay(self) -> dict[str, object]:
        self.log.append("broker:replay")
        seal = self.seal()
        return {
            **{key: seal[key] for key in ("action_count", "levels_completed", "score", "score_sha256", "terminal_reason")},
            "replay_sha256": seal["transcript_sha256"],
        }

    def presentation(self) -> dict[str, object]:
        self.log.append("broker:presentation")
        seal = self.seal()
        return {
            "action_count": seal["action_count"],
            "applied_actions": [
                {"name": "ACTION6", "data": {"x": index, "y": index + 1}}
                for index in range(self.action_count)
            ],
            "completion_grid": [[[0, 1], [2, 3]]],
            "initial_grid": [[[0, 0], [0, 0]]],
            "levels_completed": seal["levels_completed"],
            "score": seal["score"],
            "terminal_reason": seal["terminal_reason"],
        }

    def close(self) -> None:
        self.log.append("broker:close")


class _Worker:
    def __init__(self, log: list[str], broker: _Broker) -> None:
        self.log = log
        self.broker = broker
        self.executed: list[str] = []

    async def acquire(self, client: bytes) -> None:
        self.log.append("worker:acquire")
        if client != b"client":
            raise ValueError

    async def execute_cell(self, code: str) -> dict[str, object]:
        self.executed.append(code)
        self.log.append("worker:cell")
        self.broker.action_count += 13 if code.startswith("import p7_client\np7_client.observe()") else 3
        if self.broker.action_count >= 6 and self.broker.terminal_reason == "level-completed":
            self.broker.solved = True
            self.log.append("broker:level")
        return {"cell_count": len(self.executed), "output": "bounded result", "is_error": False}

    async def cleanup(self) -> None:
        self.log.append("worker:cleanup")


class _Provider:
    def __init__(self, log: list[str], *, fail: bool = False, category: str = "internal") -> None:
        self.log = log
        self.fail = fail
        self.category = category
        self.calls = 0

    async def __call__(self, body: bytes) -> bytes:
        self.calls += 1
        self.log.append("provider:call")
        if self.fail:
            raise ValueError("private payload SENTINEL_SECRET")
        json.loads(body)
        return b'{"content":[{"text":"continue","type":"text"}],"role":"assistant","stopReason":"stop","timestamp":1}'

    def finalize(self) -> object:
        self.log.append("provider:finalize")
        return SimpleNamespace(input_tokens=5, output_tokens=7, cost_microunits=11)

    def callback_counts(self) -> dict[str, int]:
        return {"normal": self.calls, "summary": 0}

    def failure_category(self) -> str:
        return self.category

    async def close(self) -> None:
        self.log.append("provider:close")


class _Gateway:
    def __init__(self, log: list[str], broker: _Broker, mode: str = "success") -> None:
        self.log = log
        self.broker = broker
        self.mode = mode
        self.prompts = 0
        self.model_hook = None
        self.tool_hook = None
        self.tool_results: list[dict[str, object]] = []

    def bind(self, *, model_hook, tool_hook) -> None:
        self.model_hook, self.tool_hook = model_hook, tool_hook
        self.log.append("gateway:bind")

    async def open(self, **_: object) -> None:
        self.log.append("gateway:open")

    async def prompt(self, prompt: str) -> dict[str, object]:
        self.prompts += 1
        self.log.append("gateway:prompt")
        if self.mode == "cancel":
            raise asyncio.CancelledError
        assert self.model_hook is not None and self.tool_hook is not None and prompt
        await self.model_hook({"request": "bounded"})
        if self.mode == "provider-failure":
            raise AssertionError("provider failure did not propagate")
        if self.mode == "noncompletion":
            return {"lifecycle": "completed", "normal_model_callback_count": 1, "summary_model_callback_count": 0, "tool_callback_count": 0}
        self.tool_results.append(await self.tool_hook({"tool_call_id": "cell-1", "code": "explore()"}))
        if self.mode == "seeded":
            self.log.append("gateway:quiescent")
            return {"lifecycle": "completed", "normal_model_callback_count": 1, "summary_model_callback_count": 0, "tool_callback_count": 1}
        await self.tool_hook({"tool_call_id": "cell-2", "code": "refine()"})
        before = len(getattr(self.tool_hook, "__self__", ())) if False else None
        del before
        post = await self.tool_hook({"tool_call_id": "cell-3", "code": "post_solve()"})
        if post["details"] != {"broker_terminal": "LEVEL_SOLVED"}:
            raise AssertionError("solve latch was lost")
        self.log.append("gateway:quiescent")
        return {"lifecycle": "completed", "normal_model_callback_count": 1, "summary_model_callback_count": 0, "tool_callback_count": 3}

    def terminal_witness(self) -> dict[str, object]:
        self.log.append("gateway:witness")
        tools = 1 if self.mode == "seeded" else 3
        return {
            "identity": {"run_id": "p7-success", "session_id": "session-p7-success", "runtime_id": "prime.agent", "generation": 1},
            "result": {
                "lifecycle": "completed",
                "usage": {"input_tokens": 5, "output_tokens": 7, "total_tokens": 12},
                "assistant": {"completed": True, "stop_reason": "stop"},
                "observations": {
                    "active_tool_names": ["ipython"], "compact_count": 0,
                    "normal_model_callback_count": 1, "summary_model_callback_count": 0,
                    "rlm_child_count": 0, "tool_call_count": tools, "solved_latched": True,
                },
            },
            "cumulative": {"normal_model_callback_count": 1, "summary_model_callback_count": 0, "tool_callback_count": tools},
        }

    async def close(self) -> None:
        self.log.append("gateway:close")


class TestPrimeP7SolvingHost(unittest.IsolatedAsyncioTestCase):
    async def test_seeded_cell_error_stops_after_first_execution(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_host import (
            PrimeP7SolvingHostError,
            run_p7_solving_lifecycle,
        )
        from asterion.applications.prime_agent.operator.p7_solving_prompt import (
            P7_SEEDED_INTEGRATION_PROMPT,
        )

        class FailedWorker(_Worker):
            async def execute_cell(self, code: str) -> dict[str, object]:
                self.executed.append(code)
                return {"cell_count": len(self.executed), "output": "SENTINEL_SECRET", "is_error": True}

        log: list[str] = []
        broker, sink, progress = _Broker(log), _Sink(log), _Progress()
        worker = FailedWorker(log, broker)
        with self.assertRaises(PrimeP7SolvingHostError):
            await run_p7_solving_lifecycle(
                gateway=_Gateway(log, broker), provider=_Provider(log), worker=worker,
                broker=broker, receipt_store=_StoreProbe().value, run_id="p7-failure",
                session_id="session-p7-failure", presentation=sink, progress=progress,
                prompt=P7_SEEDED_INTEGRATION_PROMPT, mode="seeded",
            )
        self.assertEqual(len(worker.executed), 1)
        self.assertIn("Tool callback failed at stage: worker-cell", sink.records)
        self.assertNotIn("SENTINEL_SECRET", repr(sink.records))
        self.assertNotIn("broker:seal", log)
        self.assertIn("worker:cleanup", log)

    async def test_autonomous_cell_error_is_returned_with_safe_failure_presentation(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_host import (
            run_p7_solving_lifecycle,
        )

        class FailedThenRecoveredWorker(_Worker):
            async def execute_cell(self, code: str) -> dict[str, object]:
                result = await super().execute_cell(code)
                if len(self.executed) == 1:
                    result.update(is_error=True, output="SENTINEL_SECRET")
                return result

        log: list[str] = []
        broker, sink = _Broker(log), _Sink(log)
        gateway = _Gateway(log, broker)
        await run_p7_solving_lifecycle(
            gateway=gateway, provider=_Provider(log), worker=FailedThenRecoveredWorker(log, broker),
            broker=broker, receipt_store=_StoreProbe().value, run_id="p7-success",
            session_id="session-p7-success", presentation=sink,
        )
        self.assertIn("IPython cell failed", sink.records)
        self.assertIs(gateway.tool_results[0]["isError"], True)
        self.assertNotIn("SENTINEL_SECRET", repr(sink.records))

    async def test_seeded_prompt_is_explicit_and_reaches_the_same_lifecycle(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_host import (
            run_p7_solving_lifecycle,
        )
        from asterion.applications.prime_agent.operator.p7_solving_prompt import (
            P7_SEEDED_INTEGRATION_CELL,
            P7_SEEDED_INTEGRATION_PROMPT,
        )

        class SeededFrameBroker(_Broker):
            def presentation(self) -> dict[str, object]:
                value = super().presentation()
                # The real first-level completion returns two 64 x 64 frames.
                value["initial_grid"] = [[[0] * 64 for _ in range(64)]]
                value["completion_grid"] = [
                    [[color] * 64 for _ in range(64)] for color in (0, 1)
                ]
                return value

        log: list[str] = []
        broker, sink = SeededFrameBroker(log), _Sink(log)
        gateway, worker = _Gateway(log, broker, mode="seeded"), _Worker(log, broker)
        receipt = await run_p7_solving_lifecycle(
            gateway=gateway, provider=_Provider(log), worker=worker,
            broker=broker, receipt_store=_StoreProbe().value, run_id="p7-success",
            session_id="session-p7-success", presentation=sink,
            prompt=P7_SEEDED_INTEGRATION_PROMPT, mode="seeded",
        )

        self.assertEqual(receipt.completed_level_count, 1)
        self.assertEqual(gateway.prompts, 1)
        self.assertEqual(worker.executed, [P7_SEEDED_INTEGRATION_CELL])
        self.assertEqual(sink.records[:2], [
            "Mode: seeded", "Purpose: integration chain verification",
        ])
        self.assertIn("Layer 2:", sink.records)

    async def test_seeded_mode_rejects_more_than_one_tool_callback(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_host import (
            PrimeP7SolvingHostError,
            run_p7_solving_lifecycle,
        )
        from asterion.applications.prime_agent.operator.p7_solving_prompt import (
            P7_SEEDED_INTEGRATION_PROMPT,
        )

        log: list[str] = []
        broker, sink = _Broker(log), _Sink(log)
        gateway = _Gateway(log, broker)
        with self.assertRaises(PrimeP7SolvingHostError):
            await run_p7_solving_lifecycle(
                gateway=gateway, provider=_Provider(log), worker=_Worker(log, broker),
                broker=broker, receipt_store=_StoreProbe().value, run_id="p7-success",
                session_id="session-p7-success", presentation=sink,
                prompt=P7_SEEDED_INTEGRATION_PROMPT, mode="seeded",
            )
        self.assertIn("Validation failed at stage: callback-accounting", sink.records)
        self.assertIn("worker:cleanup", log)

    async def test_model_failure_renders_only_fixed_safe_category(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_host import (
            PrimeP7SolvingHostError,
            run_p7_solving_lifecycle,
        )

        log: list[str] = []
        broker = _Broker(log)
        sink = _Sink(log)
        with self.assertRaises(PrimeP7SolvingHostError):
            await run_p7_solving_lifecycle(
                gateway=_Gateway(log, broker, mode="provider-failure"),
                provider=_Provider(log, fail=True, category="input-limit"),
                worker=_Worker(log, broker), broker=broker,
                receipt_store=_StoreProbe().value, run_id="p7-failure",
                session_id="session-p7-failure", presentation=sink,
        )
        self.assertEqual(sink.records, ["Model callback failed: input-limit"])
        self.assertNotIn("SENTINEL_SECRET", repr(sink.records))

    def test_model_callback_uses_provider_canonical_utf8(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_host import (
            _canonical,
        )
        from asterion.applications.prime_agent.operator.p7_solving_sdk_provider import (
            _canonical_json,
        )

        value = {"systemPrompt": "Prime π"}
        self.assertEqual(_canonical(value), _canonical_json(value).encode("utf-8"))

    async def test_success_is_quiescent_replayed_cleaned_then_published(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_host import (
            run_p7_solving_lifecycle,
        )

        log: list[str] = []
        broker = _Broker(log)
        worker = _Worker(log, broker)
        provider = _Provider(log)
        gateway = _Gateway(log, broker)
        progress, sink, store = _Progress(), _Sink(log), _StoreProbe().value
        receipt = await run_p7_solving_lifecycle(
            gateway=gateway, provider=provider, worker=worker, broker=broker,
            receipt_store=store, run_id="p7-success", session_id="session-p7-success",
            progress=progress, presentation=sink,
        )

        self.assertEqual(receipt.completed_level_count, 1)
        self.assertEqual(receipt.primitive_action_count, 6)
        self.assertEqual(receipt.partial_game_score, "3.571429")
        self.assertIs(store.get_receipt(run_id=receipt.run_id, receipt_sha256=receipt.receipt_sha256), receipt)
        from asterion.applications.prime_agent.operator.p7_solving_host import PrimeP7SolvingHostError

        with self.assertRaises(PrimeP7SolvingHostError):
            store.get_receipt(run_id=receipt.run_id, receipt_sha256=receipt.receipt_sha256)
        self.assertEqual(worker.executed, ["explore()", "refine()"])
        required = [
            "broker:start", "worker:acquire", "gateway:prompt", "broker:level",
            "gateway:quiescent", "provider:finalize", "gateway:witness",
            "broker:replay", "broker:presentation", "presentation",
            "gateway:close", "provider:close", "worker:cleanup", "broker:close",
        ]
        positions = [log.index(item) for item in required]
        self.assertEqual(positions, sorted(positions))
        witness_index, replay_index = log.index("gateway:witness"), log.index("broker:replay")
        self.assertIn("broker:seal", log[witness_index + 1 : replay_index])
        self.assertTrue(all(event.current is None and event.total is None for event in progress.events))
        self.assertFalse(any(record in repr(progress.events) for record in sink.records))

    async def test_limits_cancellation_and_noncompletion_fail_once(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_host import (
            PrimeP7SolvingHostError,
            run_p7_solving_lifecycle,
        )

        for mode, terminal, cancelled in (
            ("callback-limit", "level-completed", False),
            ("deadline", "level-completed", False),
            ("success", "action-cap", False),
            ("noncompletion", "level-completed", False),
            ("cancel", "level-completed", True),
        ):
            with self.subTest(mode=mode, terminal=terminal):
                log: list[str] = []
                broker = _Broker(log, terminal_reason=terminal)
                provider = _Provider(log, fail=mode in {"callback-limit", "deadline"})
                gateway = _Gateway(log, broker, mode=mode)
                worker = _Worker(log, broker)
                store = _StoreProbe().value
                expected = asyncio.CancelledError if cancelled else PrimeP7SolvingHostError
                with self.assertRaises(expected):
                    await run_p7_solving_lifecycle(
                        gateway=gateway, provider=provider, worker=worker, broker=broker,
                        receipt_store=store, run_id="p7-failure", session_id="session-p7-failure",
                    )
                self.assertEqual(gateway.prompts, 1)
                self.assertLessEqual(provider.calls, 1)
                with self.assertRaises(PrimeP7SolvingHostError):
                    store.get_receipt(run_id="p7-failure", receipt_sha256="sha256:" + "0" * 64)


if __name__ == "__main__":
    unittest.main()
