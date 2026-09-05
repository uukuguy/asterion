"""Provider-free contracts for P2 host evidence boundaries."""

from __future__ import annotations

import asyncio
import unittest


class TestPrimeP2DevelopmentHost(unittest.IsolatedAsyncioTestCase):
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
