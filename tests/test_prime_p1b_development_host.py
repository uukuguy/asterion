"""Focused fake closure checks for the P1-B development host."""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch


_INITIAL = b"def answer() -> int:\n    return 0\n"
_FINAL = b"def answer() -> int:\n    return 42\n"


class _Service:
    instances: list["_Service"] = []
    cleanup_failure = False

    def __init__(self, **_: object) -> None:
        self.calls: list[object] = []
        self.snapshots = iter((_INITIAL, _FINAL))
        type(self).instances.append(self)

    async def acquire(self) -> None:
        self.calls.append("acquire")

    async def execute_cell(self, cell: str) -> dict[str, object]:
        self.calls.append(("cell", cell))
        count = sum(isinstance(call, tuple) for call in self.calls)
        return {"cell_count": count, "kernel_generation": 1, "probe_count": count * 6}

    async def initial_snapshot(self) -> bytes:
        self.calls.append("initial_snapshot")
        return next(self.snapshots)

    async def finish(self) -> object:
        self.calls.append("finish")
        return SimpleNamespace(kernel_generation=1, cell_count=2, probe_count=12)

    async def snapshot(self) -> bytes:
        self.calls.append("snapshot")
        return next(self.snapshots)

    async def cleanup(self) -> None:
        self.calls.append("cleanup")
        if self.cleanup_failure:
            raise RuntimeError("cleanup failed")


class _Provider:
    fail_at: int | None = None

    def __init__(self) -> None:
        self.calls: list[bytes] = []
        self.closed = False

    async def __call__(self, body: bytes) -> bytes:
        self.calls.append(body)
        if self.fail_at == len(self.calls) - 1:
            raise ValueError("SENTINEL_CALLBACK_FAILURE")
        return json.dumps(
            {"content": [], "role": "assistant", "stopReason": "stop"},
            separators=(",", ":"),
            sort_keys=True,
        ).encode()

    def terminal_usage(self) -> object:
        return SimpleNamespace(input_tokens=1, output_tokens=1, cost_microunits=1)

    async def close(self) -> None:
        self.closed = True


class _Gateway:
    instances: list["_Gateway"] = []
    bad_witness = False

    def __init__(self, *, model_hook: object, tool_hook: object, **_: object) -> None:
        self.calls: list[str] = []
        self.model, self.tool = model_hook, tool_hook
        type(self).instances.append(self)

    async def open(self, **_: object) -> None:
        self.calls.append("open")

    async def prompt(self, _: str) -> object:
        self.calls.append("prompt")
        await self.model({"context": {}, "model": {}, "options": {}})  # type: ignore[misc]
        if len([item for item in self.calls if item == "prompt"]) == 1:
            await self.tool({"tool_call_id": "call-1", "code": "one"})  # type: ignore[misc]
            await self.model({"context": {}, "model": {}, "options": {}})  # type: ignore[misc]
        else:
            await self.tool({"tool_call_id": "call-2", "code": "two"})  # type: ignore[misc]
            await self.model({"context": {}, "model": {}, "options": {}})  # type: ignore[misc]
        return {"lifecycle": "completed"}

    async def compact(self) -> object:
        self.calls.append("compact")
        await self.model({"context": {}, "model": {}, "options": {}})  # type: ignore[misc]
        return {
            "compact_called": not self.bad_witness,
            "succeeded": True,
            "start_count": 1,
            "end_count": 1,
            "message_count_before": 2,
            "message_count_after": 1,
            "tokens_before": 3,
            "first_kept_entry_id_sha256": "sha256:" + "a" * 64,
        }

    async def close(self) -> None:
        self.calls.append("close")

    async def cancel(self) -> object:
        self.calls.append("cancel")
        return {"lifecycle": "cancelled"}


class TestPrimeP1BDevelopmentHost(unittest.IsolatedAsyncioTestCase):
    async def test_fake_closure_runs_fixed_flow_and_returns_body_free_trace(
        self,
    ) -> None:
        from asterion.applications.prime_agent.operator import (
            p1b_development_host as subject,
        )

        _Service.instances.clear()
        _Gateway.instances.clear()
        provider = _Provider()
        observation = subject._P1BObservation()  # noqa: SLF001
        with self.assertRaises(subject.PrimeP1BDevelopmentHostError) as invalid:
            await subject.run_prime_p1b_development(
                image_digest="sha256:" + "a" * 64,
                transport=object(),
                operator_config={"DEEPSEEK_API_KEY": "secret"},
                node_bin="/operator/node",
                entrypoint="/operator/bridge.js",
                prime_source_root="/operator/prime",
                _observation=object(),  # type: ignore[arg-type]
            )
        self.assertIsNone(invalid.exception.__context__)
        with (
            patch.object(subject, "P1BDockerPersistentWorkerService", _Service),
            patch.object(subject, "PrimeP1BDevelopmentGateway", _Gateway),
            patch.object(
                subject,
                "create_prime_p1b_development_sdk_provider",
                return_value=provider,
            ),
        ):
            trace = await subject.run_prime_p1b_development(
                image_digest="sha256:" + "a" * 64,
                transport=object(),
                operator_config={"DEEPSEEK_API_KEY": "secret"},
                node_bin="/operator/node",
                entrypoint="/operator/bridge.js",
                prime_source_root="/operator/prime",
                _observation=observation,
            )

        self.assertEqual(
            (trace.scope, trace.promotion), ("p1-b-development", "unpromoted")
        )
        self.assertRegex(trace.trace_sha256, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(len(provider.calls), 5)
        self.assertTrue(provider.closed)
        self.assertEqual(
            _Service.instances[0].calls,
            [
                "acquire",
                "initial_snapshot",
                ("cell", "one"),
                ("cell", "two"),
                "finish",
                "snapshot",
                "cleanup",
            ],
        )
        self.assertEqual(
            _Gateway.instances[0].calls,
            ["open", "prompt", "compact", "prompt", "close"],
        )
        self.assertNotIn("secret", repr(trace))
        snapshot = observation.snapshot()
        self.assertFalse(snapshot.observation_invalid)
        self.assertIsNone(snapshot.first_work_failure)
        self.assertEqual(snapshot.cleanup_failures, ())
        self.assertEqual(len(snapshot.events), 50)
        self.assertEqual(
            [(event.stage, event.lane, event.state, event.index) for event in snapshot.events],
            [
                ("setup", "work", "started", None), ("setup", "work", "succeeded", None),
                ("worker.acquire", "work", "started", None), ("worker.acquire", "work", "succeeded", None),
                ("worker.snapshot0", "work", "started", None), ("worker.snapshot0", "work", "succeeded", None),
                ("oracle", "work", "started", 0), ("oracle", "work", "succeeded", 0),
                ("setup", "work", "started", None), ("setup", "work", "succeeded", None),
                ("gateway.open", "work", "started", None), ("gateway.open", "work", "succeeded", None),
                ("gateway.prompt0", "work", "started", None),
                ("provider.callback", "work", "started", 0), ("provider.callback", "work", "succeeded", 0),
                ("worker.cell", "work", "started", 0), ("worker.cell", "work", "succeeded", 0),
                ("provider.callback", "work", "started", 1), ("provider.callback", "work", "succeeded", 1),
                ("gateway.prompt0", "work", "succeeded", None),
                ("gateway.compact", "work", "started", None),
                ("provider.callback", "work", "started", 2), ("provider.callback", "work", "succeeded", 2),
                ("gateway.compact", "work", "succeeded", None),
                ("gateway.prompt1", "work", "started", None),
                ("provider.callback", "work", "started", 3), ("provider.callback", "work", "succeeded", 3),
                ("worker.cell", "work", "started", 1), ("worker.cell", "work", "succeeded", 1),
                ("provider.callback", "work", "started", 4), ("provider.callback", "work", "succeeded", 4),
                ("gateway.prompt1", "work", "succeeded", None),
                ("gateway.close", "work", "started", None), ("gateway.close", "work", "succeeded", None),
                ("conversation.validate", "work", "started", None), ("conversation.validate", "work", "succeeded", None),
                ("provider.usage", "work", "started", None), ("provider.usage", "work", "succeeded", None),
                ("worker.finish", "work", "started", None), ("worker.finish", "work", "succeeded", None),
                ("worker.snapshot1", "work", "started", None), ("worker.snapshot1", "work", "succeeded", None),
                ("oracle", "work", "started", 1), ("oracle", "work", "succeeded", 1),
                ("trace", "work", "started", None), ("trace", "work", "succeeded", None),
                ("provider.close", "work", "started", None), ("provider.close", "work", "succeeded", None),
                ("worker.cleanup", "cleanup", "started", None), ("worker.cleanup", "cleanup", "succeeded", None),
            ],
        )

    async def test_callback_failure_preserves_first_work_failure_over_cleanup_failure(
        self,
    ) -> None:
        from asterion.applications.prime_agent.operator import (
            p1b_development_host as subject,
        )

        _Service.instances.clear()
        _Gateway.instances.clear()
        _Provider.fail_at = 2
        _Service.cleanup_failure = True
        observation = subject._P1BObservation()  # noqa: SLF001
        try:
            with (
                patch.object(subject, "P1BDockerPersistentWorkerService", _Service),
                patch.object(subject, "PrimeP1BDevelopmentGateway", _Gateway),
                patch.object(
                    subject,
                    "create_prime_p1b_development_sdk_provider",
                    return_value=_Provider(),
                ),
            ):
                with self.assertRaisesRegex(
                    subject.PrimeP1BDevelopmentHostError, "unavailable"
                ) as caught:
                    await subject.run_prime_p1b_development(
                        image_digest="sha256:" + "a" * 64,
                        transport=object(),
                        operator_config={"DEEPSEEK_API_KEY": "SENTINEL"},
                        node_bin="/operator/node",
                        entrypoint="/operator/bridge.js",
                        prime_source_root="/operator/prime",
                        _observation=observation,
                    )
        finally:
            _Provider.fail_at = None
            _Service.cleanup_failure = False
        self.assertIn("cleanup", _Service.instances[0].calls)
        self.assertIn("close", _Gateway.instances[0].calls)
        self.assertNotIn("SENTINEL", str(caught.exception))
        self.assertIsNone(caught.exception.__context__)
        snapshot = observation.snapshot()
        self.assertEqual(
            (snapshot.first_work_failure.stage, snapshot.first_work_failure.index),
            ("provider.callback", 2),
        )
        self.assertEqual(
            [(event.stage, event.lane) for event in snapshot.cleanup_failures],
            [("worker.cleanup", "cleanup")],
        )
        self.assertNotIn("SENTINEL", repr(snapshot))

    async def test_bad_compaction_witness_fails_closed_and_cleans_up_redacted(
        self,
    ) -> None:
        from asterion.applications.prime_agent.operator import (
            p1b_development_host as subject,
        )

        _Service.instances.clear()
        _Gateway.instances.clear()
        _Gateway.bad_witness = True
        try:
            with (
                patch.object(subject, "P1BDockerPersistentWorkerService", _Service),
                patch.object(subject, "PrimeP1BDevelopmentGateway", _Gateway),
                patch.object(
                    subject,
                    "create_prime_p1b_development_sdk_provider",
                    return_value=_Provider(),
                ),
            ):
                with self.assertRaisesRegex(
                    subject.PrimeP1BDevelopmentHostError, "unavailable"
                ) as caught:
                    await subject.run_prime_p1b_development(
                        image_digest="sha256:" + "a" * 64,
                        transport=object(),
                        operator_config={"DEEPSEEK_API_KEY": "SENTINEL"},
                        node_bin="/operator/node",
                        entrypoint="/operator/bridge.js",
                        prime_source_root="/operator/prime",
                    )
        finally:
            _Gateway.bad_witness = False
        self.assertIn("cleanup", _Service.instances[0].calls)
        self.assertIn("close", _Gateway.instances[0].calls)
        self.assertNotIn("SENTINEL", str(caught.exception) + repr(caught.exception))
        self.assertIsNone(caught.exception.__context__)

    async def test_cleanup_failure_does_not_return_a_trace(self) -> None:
        from asterion.applications.prime_agent.operator import (
            p1b_development_host as subject,
        )

        _Service.instances.clear()
        _Gateway.instances.clear()
        _Service.cleanup_failure = True
        try:
            with (
                patch.object(subject, "P1BDockerPersistentWorkerService", _Service),
                patch.object(subject, "PrimeP1BDevelopmentGateway", _Gateway),
                patch.object(
                    subject,
                    "create_prime_p1b_development_sdk_provider",
                    return_value=_Provider(),
                ),
            ):
                with self.assertRaises(subject.PrimeP1BDevelopmentHostError):
                    await subject.run_prime_p1b_development(
                        image_digest="sha256:" + "a" * 64,
                        transport=object(),
                        operator_config={"DEEPSEEK_API_KEY": "secret"},
                        node_bin="/operator/node",
                        entrypoint="/operator/bridge.js",
                        prime_source_root="/operator/prime",
                    )
        finally:
            _Service.cleanup_failure = False
        self.assertIn("cleanup", _Service.instances[0].calls)
