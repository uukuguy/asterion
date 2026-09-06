"""Provider-free contracts for P2 host evidence boundaries."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from asterion.services.progress import HostProgressEvent


class TestPrimeP2DevelopmentHost(unittest.IsolatedAsyncioTestCase):
    async def test_concrete_lifecycle_emits_the_fixed_success_sequence(self) -> None:
        from asterion.applications.prime_agent.operator import p2_development_host as subject

        events: list[HostProgressEvent] = []

        class Reporter:
            def emit(self, event: HostProgressEvent) -> None:
                events.append(event)

        class Provider:
            async def __call__(self, _: bytes) -> bytes:
                return b'{"role":"assistant"}'

            def terminal_usage(self) -> object:
                return SimpleNamespace(input_tokens=2, output_tokens=3, cost_microunits=7)

        class Transport:
            async def create(self, **_: object) -> str:
                return "container"

            async def start(self, *_: object) -> None:
                return None

            async def execute_cell(self, *_: object) -> None:
                return None

            async def read_result(self, *_: object) -> bytes:
                return b'{"count":3,"sum":23}\n'

            async def remove(self, *_: object) -> None:
                return None

            async def assert_absent(self, *_: object) -> None:
                return None

        class Gateway:
            def __init__(self, *, model_hook, tool_hook, **_: object) -> None:
                self.model_hook = model_hook
                self.tool_hook = tool_hook

            async def open(self, **_: object) -> None:
                return None

            async def prompt(self, _: str) -> dict[str, object]:
                await self.model_hook({"role": "assistant"})
                await self.model_hook({"role": "assistant"})
                await self.tool_hook({"tool_call_id": "one", "code": "x = 1"})
                return {
                    "lifecycle": "completed",
                    "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
                    "assistant": {"completed": True, "stop_reason": "stop"},
                    "observations": {"active_tool_names": ["ipython"], "compact_count": 0, "model_callback_count": 2, "rlm_child_count": 0, "tool_call_count": 1},
                }

            async def cancel(self) -> dict[str, str]:
                return {"lifecycle": "cancelled"}

            async def close(self) -> None:
                return None

        with (
            patch.object(subject, "create_prime_p2_development_sdk_provider", return_value=Provider()),
            patch.object(subject, "PrimeP2DevelopmentGateway", Gateway),
            patch.object(subject, "PrimeP2DevelopmentDockerTransport", Transport),
        ):
            await subject.run_prime_p2_development(
                image_digest="sha256:" + "a" * 64,
                transport=Transport(),
                operator_config={},
                node_bin="node",
                entrypoint="entry",
                prime_source_root="/prime",
                run_id="p2-progress-success",
                progress=Reporter(),
            )

        self.assertEqual(
            events,
            [
                HostProgressEvent("worker", "started"),
                HostProgressEvent("worker", "succeeded"),
                HostProgressEvent("model", "started", 1, 2),
                HostProgressEvent("model", "succeeded", 1, 2),
                HostProgressEvent("model", "started", 2, 2),
                HostProgressEvent("model", "succeeded", 2, 2),
                HostProgressEvent("tool", "started", 1, 1),
                HostProgressEvent("tool", "succeeded", 1, 1),
                HostProgressEvent("validation", "started"),
                HostProgressEvent("validation", "succeeded"),
                HostProgressEvent("cleanup", "started"),
                HostProgressEvent("cleanup", "succeeded"),
            ],
        )

    async def test_worker_failure_reports_cleanup_after_residue_check(self) -> None:
        from asterion.applications.prime_agent.operator import p2_development_host as subject

        events: list[HostProgressEvent] = []

        class Reporter:
            def emit(self, event: HostProgressEvent) -> None:
                events.append(event)

        class Transport:
            async def create(self, **_: object) -> str:
                return "container"

            async def start(self, *_: object) -> None:
                raise RuntimeError("private failure")

            async def remove(self, *_: object) -> None:
                return None

            async def assert_absent(self, *_: object) -> None:
                return None

        with (
            patch.object(subject, "PrimeP2DevelopmentDockerTransport", Transport),
            patch.object(subject, "create_prime_p2_development_sdk_provider", return_value=object()),
        ):
            with self.assertRaises(subject.PrimeP2DevelopmentHostError):
                await subject.run_prime_p2_development(
                    image_digest="sha256:" + "a" * 64,
                    transport=Transport(),
                    operator_config={},
                    node_bin="node",
                    entrypoint="entry",
                    prime_source_root="/prime",
                    run_id="p2-progress-failure",
                    progress=Reporter(),
                )

        self.assertEqual(
            events,
            [
                HostProgressEvent("worker", "started"),
                HostProgressEvent("worker", "failed"),
                HostProgressEvent("cleanup", "started"),
                HostProgressEvent("cleanup", "succeeded"),
            ],
        )
    def test_safe_trace_is_unpromoted_and_redacted(self) -> None:
        from asterion.applications.prime_agent.operator.p2_development_host import (
            PrimeP2DevelopmentEvidence,
        )

        self.assertEqual(PrimeP2DevelopmentEvidence.__dataclass_fields__["scope"].default, "p2-development")
        self.assertEqual(PrimeP2DevelopmentEvidence.__dataclass_fields__["promotion"].default, "unpromoted")

    def test_host_has_its_own_p2_oracle_and_never_imports_p1_supervisor(self) -> None:
        from asterion.applications.prime_agent.operator import p2_development_host

        self.assertTrue(callable(p2_development_host._validate_p2_result))  # noqa: SLF001
        self.assertNotIn("ipython_host_supervisor", p2_development_host.__dict__)
        self.assertNotIn("PRIME_IPYTHON_CODING_WORKLOAD_DIGEST", p2_development_host.__dict__)

    def test_p2_oracle_requires_canonical_aggregate_bytes(self) -> None:
        from asterion.applications.prime_agent.operator.p2_development_host import (
            PrimeP2DevelopmentHostError,
            _validate_p2_result,
        )

        self.assertEqual(_validate_p2_result(b'{"count":3,"sum":23}\n'), {"count": 3, "sum": 23})
        with self.assertRaises(PrimeP2DevelopmentHostError):
            _validate_p2_result(b'{"sum":23,"count":3}\n')

    def test_model_callback_canonicalization_preserves_utf8(self) -> None:
        from asterion.applications.prime_agent.operator.p2_development_host import (
            _canonical,
        )

        self.assertEqual(_canonical({"z": "值", "a": 1}), b'{"a":1,"z":"\xe5\x80\xbc"}')

    async def test_lifecycle_binds_cell_callbacks_oracle_and_cleanup(self) -> None:
        from asterion.applications.prime_agent.operator.p2_development_host import run_p2_development_lifecycle

        events: list[str] = []

        class Gateway:
            async def open(self, **_: object) -> None: events.append("open")
            async def prompt(self, _: str) -> dict[str, str]:
                events.append("prompt")
                return {
                    "lifecycle": "completed",
                    "usage": {
                        "input_tokens": 2,
                        "output_tokens": 3,
                        "total_tokens": 5,
                    },
                    "assistant": {"completed": True, "stop_reason": "stop"},
                    "observations": {
                        "active_tool_names": ["ipython"],
                        "compact_count": 0,
                        "model_callback_count": 2,
                        "rlm_child_count": 0,
                        "tool_call_count": 1,
                    },
                }
            async def cancel(self) -> dict[str, str]:
                events.append("cancel")
                return {"lifecycle": "cancelled"}
            async def close(self) -> None: events.append("close")

        async def result() -> bytes:
            events.append("result")
            return b'{"count":3,"sum":23}\n'
        async def cleanup() -> None: events.append("cleanup")

        terminal = type(
            "Usage",
            (),
            {"input_tokens": 2, "output_tokens": 3, "cost_microunits": 7},
        )()
        evidence = await run_p2_development_lifecycle(
            gateway=Gateway(),
            open_arguments={
                "run_id": "p2-run-a",
                "session_id": "p2-session-a",
                "generation": 1,
                "prime_source_root": "/prime",
                "workspace": "/workspace",
            },
            prompt="schema only",
            run_id="p2-run-a",
            session_id="p2-session-a",
            image_digest="sha256:" + "a" * 64,
            callback_count=lambda: 2,
            tool_count=lambda: 1,
            cell_bytes=lambda: b"print('private')",
            read_result=result,
            cleanup=cleanup,
            usage_certain=lambda: True,
            terminal_usage=lambda: terminal,
        )
        self.assertRegex(evidence.trace.evidence_digest, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(events, ["open", "prompt", "result", "close", "cleanup"])

    async def test_post_validation_close_failure_does_not_retract_success(self) -> None:
        from asterion.applications.prime_agent.operator import p2_development_host as subject

        progress: list[HostProgressEvent] = []

        class Reporter:
            def emit(self, event: HostProgressEvent) -> None:
                progress.append(event)

        class Gateway:
            async def open(self, **_: object) -> None:
                return None

            async def prompt(self, _: str) -> dict[str, object]:
                return {
                    "lifecycle": "completed",
                    "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
                    "assistant": {"completed": True, "stop_reason": "stop"},
                    "observations": {"active_tool_names": ["ipython"], "compact_count": 0, "model_callback_count": 2, "rlm_child_count": 0, "tool_call_count": 1},
                }

            async def cancel(self) -> dict[str, str]:
                return {"lifecycle": "cancelled"}

            async def close(self) -> None:
                raise RuntimeError("private close failure")

        terminal = SimpleNamespace(input_tokens=2, output_tokens=3, cost_microunits=7)
        with self.assertRaises(subject.PrimeP2DevelopmentHostError):
            await subject.run_p2_development_lifecycle(
                gateway=Gateway(),
                open_arguments={"run_id": "p2-close-failure", "session_id": "p2-session", "generation": 1, "prime_source_root": "/prime", "workspace": "/workspace"},
                prompt="schema only",
                run_id="p2-close-failure",
                session_id="p2-session",
                image_digest="sha256:" + "a" * 64,
                callback_count=lambda: 2,
                tool_count=lambda: 1,
                cell_bytes=lambda: b"cell",
                read_result=lambda: asyncio.sleep(0, result=b'{"count":3,"sum":23}\n'),
                cleanup=lambda: asyncio.sleep(0),
                usage_certain=lambda: True,
                terminal_usage=lambda: terminal,
                progress=Reporter(),
            )
        self.assertEqual(
            progress,
            [
                HostProgressEvent("validation", "started"),
                HostProgressEvent("validation", "succeeded"),
            ],
        )

    async def test_cancellation_cleans_up_and_remains_cancellation(self) -> None:
        from asterion.applications.prime_agent.operator.p2_development_host import (
            run_p2_development_lifecycle,
        )

        events: list[str] = []

        class Gateway:
            async def open(self, **_: object) -> None:
                events.append("open")

            async def prompt(self, _: str) -> dict[str, str]:
                raise asyncio.CancelledError

            async def cancel(self) -> dict[str, str]:
                events.append("cancel")
                return {"lifecycle": "cancelled"}

            async def close(self) -> None:
                events.append("close")

        async def cleanup() -> None:
            events.append("cleanup")

        with self.assertRaises(asyncio.CancelledError):
            await run_p2_development_lifecycle(
                gateway=Gateway(),
                open_arguments={
                    "run_id": "p2-run-cancelled",
                    "session_id": "p2-session-cancelled",
                    "generation": 1,
                    "prime_source_root": "/prime",
                    "workspace": "/workspace",
                },
                prompt="schema only",
                run_id="p2-run-cancelled",
                session_id="p2-session-cancelled",
                image_digest="sha256:" + "a" * 64,
                callback_count=lambda: 0,
                tool_count=lambda: 0,
                cell_bytes=lambda: b"",
                read_result=lambda: asyncio.sleep(0, result=b""),
                cleanup=cleanup,
                usage_certain=lambda: False,
                terminal_usage=lambda: object(),
            )
        self.assertEqual(events, ["open", "cancel", "close", "cleanup"])
