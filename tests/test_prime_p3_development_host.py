from __future__ import annotations
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest


class TestPrimeP3DevelopmentHost(unittest.IsolatedAsyncioTestCase):
    def test_model_payload_uses_provider_canonical_utf8(self) -> None:
        from asterion.applications.prime_agent.operator.p3_development_host import _canonical
        from asterion.applications.prime_agent.operator.p3_development_sdk_provider import _p2

        value = {"system": "递归验证"}
        self.assertEqual(_canonical(value), _p2._canonical_json(value).encode())

    async def test_rlm_socket_returns_without_client_eof_and_rejects_extra_fields(self) -> None:
        from asterion.applications.prime_agent.operator.p3_development_host import _open_rlm_server

        class Gateway:
            async def request_nested(self, kind: str, payload: object) -> dict[str, object]:
                if kind == "rlm.spawn":
                    role = payload["role"]  # type: ignore[index]
                    return {"rlm_child_id": "child-" + role}  # type: ignore[operator]
                if kind == "rlm.list":
                    return {"subagents": []}
                return {}

        async def request(directory: str, value: dict[str, object]) -> dict[str, object]:
            reader, writer = await asyncio.open_unix_connection(str(Path(directory) / "rlm.sock"))
            writer.write(json.dumps(value).encode() + b"\n")
            await writer.drain()
            response = json.loads(await reader.readline())
            writer.close()
            await writer.wait_closed()
            return response

        with TemporaryDirectory() as directory:
            server = await _open_rlm_server(Path(directory), Gateway())
            commands = [
                {"kind": "spawn", "role": "implementation"},
                {"kind": "wait", "role": "implementation"},
                {"kind": "spawn", "role": "review"},
                {"kind": "wait", "role": "review"},
                {"kind": "follow_up"},
                {"kind": "delete", "role": "implementation"},
                {"kind": "delete", "role": "review"},
                {"kind": "list"},
            ]
            for command in commands[:-1]:
                self.assertEqual(
                    await request(directory, command),
                    {"ok": True, "result": {"status": "completed"}},
                )
            self.assertEqual(
                await request(directory, commands[-1]),
                {"ok": True, "result": {"subagents": []}},
            )
            self.assertEqual(
                await request(directory, {"kind": "list", "extra": True}),
                {"ok": False, "result": {}},
            )
            server.close()
            await server.wait_closed()
    async def test_concrete_route_uses_role_provider_workers_and_gateway_hooks(self) -> None:
        from asterion.applications.prime_agent.operator import (
            p3_development_host as subject,
        )

        events: list[object] = []

        class Provider:
            async def callback(self, role: str, _: bytes) -> bytes:
                events.append(("model", role))
                return b'{"role":"assistant"}'

            def terminal_usage(self) -> object:
                return SimpleNamespace(input_tokens=3, output_tokens=3, cost_microunits=6)

        class Transport:
            async def create_workers(self, **_: object):
                return ("root", "implementation", "review")

            async def start_workers(self, workers: tuple[str, ...], _: object) -> None:
                events.append(("start", workers))

            async def execute(self, worker: str, cell: str, _: object) -> None:
                events.append(("tool", worker, cell))

            async def read(self, _: str, name: str, __: object) -> bytes:
                from asterion.applications.prime_agent.operator import (
                    p3_development_workload as work,
                )

                return {
                    "solution.py": work.P3_EXPECTED_SOURCE_BYTES,
                    "test_solution.py": work.P3_EXPECTED_TEST_BYTES,
                    "implementation.json": work.P3_IMPLEMENTATION_BYTES,
                    "review.json": work.P3_REVIEW_BYTES,
                    "review-follow-up.json": work.P3_FOLLOW_UP_BYTES,
                    "aggregate.json": work.P3_AGGREGATE_BYTES,
                }[name]

            async def cleanup(self, workers: tuple[str, ...], _: object) -> None:
                events.append(("cleanup", workers))

            async def assert_absent(self, workers: tuple[str, ...], _: object) -> None:
                events.append(("absent", workers))

        class Gateway:
            instance: "Gateway"

            def __init__(self, *, model_hook, tool_hook, **_: object) -> None:
                self.model_hook = model_hook
                self.tool_hook = tool_hook
                Gateway.instance = self

            async def open(self, **_: object) -> None:
                events.append("open")

            async def prompt(self, _: str) -> dict[str, object]:
                for role, count in (("root", 4), ("implementation", 2), ("review", 4)):
                    for _ in range(count):
                        await self.model_hook(
                            {
                                "role": role,
                                "model": {},
                                "context": {},
                                "options": {},
                            }
                        )
                for role, count in (("root", 1), ("implementation", 1), ("review", 2)):
                    for index in range(count):
                        await self.tool_hook(
                            {"role": role, "tool_call_id": role + str(index), "code": "x = 1"}
                        )
                return {
                    "lifecycle": "completed",
                    "usage": {
                        "implementation": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                        "review": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                        "root": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                    },
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

        with (
            patch.object(subject, "create_prime_p3_development_sdk_provider", return_value=Provider()),
            patch.object(subject, "PrimeP3DevelopmentGateway", Gateway),
        ):
            trace = await subject.run_prime_p3_development(
                image_digest="sha256:" + "a" * 64,
                transport=Transport(),
                operator_config={"opaque": "value"},
                node_bin="node",
                entrypoint="entry",
                prime_source_root="/prime",
                run_id="p3-concrete-run",
            )

        self.assertRegex(trace.trace_sha256, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(events.count(("model", "root")), 4)
        self.assertEqual(events.count(("model", "implementation")), 2)
        self.assertEqual(events.count(("model", "review")), 4)
        self.assertEqual(len([event for event in events if isinstance(event, tuple) and event[0] == "tool"]), 4)
        self.assertIn(("cleanup", ("root", "implementation", "review")), events)
        self.assertIn(("absent", ("root", "implementation", "review")), events)
