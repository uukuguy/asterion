from __future__ import annotations
import unittest


class TestPrimeP3DevelopmentHost(unittest.IsolatedAsyncioTestCase):
    async def test_host_binds_gateway_oracle_and_cleanup(self) -> None:
        from asterion.applications.prime_agent.operator.p3_development_host import (
            run_prime_p3_development,
        )
        from asterion.applications.prime_agent.operator import (
            p3_development_workload as work,
        )

        events: list[str] = []

        class Gateway:
            async def open(self, **_: object) -> None:
                events.append("open")

            async def prompt(self, _: str) -> dict[str, object]:
                events.append("prompt")
                return {
                    "lifecycle": "completed",
                    "usage": {},
                    "assistant": {"completed": True, "stop_reason": "stop"},
                    "observations": {
                        "child_count": 2,
                        "max_depth": 1,
                        "model_callback_count": 10,
                        "remaining_child_count": 0,
                        "retained_follow_up_count": 1,
                        "tool_call_count": 4,
                    },
                }

            async def cancel(self) -> dict[str, str]:
                return {"lifecycle": "cancelled"}

            async def close(self) -> None:
                events.append("close")

            async def request_nested(self, _: str, __: object) -> dict[str, object]:
                return {}

        class Service:
            async def start(self) -> None:
                events.append("start")

            async def execute(self, _: str, __: str) -> None:
                return None

            async def read(self, name: str) -> bytes:
                return {
                    "solution.py": work.P3_EXPECTED_SOURCE_BYTES,
                    "test_solution.py": work.P3_EXPECTED_TEST_BYTES,
                    "aggregate.json": work.P3_AGGREGATE_BYTES,
                }[name]

            async def cleanup(self) -> None:
                events.append("cleanup")

        trace = await run_prime_p3_development(
            gateway=Gateway(),
            service=Service(),
            run_id="run",
            session_id="session",
            prompt="fixed",
        )
        self.assertRegex(trace.trace_sha256, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(events, ["start", "open", "prompt", "close", "cleanup"])
