from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import os
import sys
import tempfile
import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import MappingProxyType
from typing import cast
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SKILL_SRC = (
    ROOT
    / "src/asterion/control/providers/prime/resources/skills/asterion-control/src"
)
TOKEN = "33" * 32
TARGET = {
    "kind": "application",
    "provider_id": "example.provider",
    "application_id": "alpha",
    "version": "1.0.0",
    "runtime_id": "fake.runtime",
}
BUDGET = {
    "controller_tokens": 0,
    "application_tokens": 100,
    "child_tokens": 0,
    "aggregate_tokens": 100,
    "cost_micros": 5_000,
    "deadline_ms": 10_000,
}


@asynccontextmanager
async def _fake_bridge(
    response: dict[str, object] | None,
) -> AsyncIterator[tuple[Path, list[dict[str, object]]]]:
    with tempfile.TemporaryDirectory() as directory:
        socket_path = Path(directory) / "bridge.sock"
        received: list[dict[str, object]] = []

        async def handle(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            try:
                auth_line = await reader.readline()
                request_line = await reader.readline()
                if auth_line:
                    received.append(json.loads(auth_line))
                if request_line:
                    request = json.loads(request_line)
                    received.append(request)
                    if response is not None:
                        outgoing = {
                            **response,
                            "request_id": request["request_id"],
                        }
                        try:
                            writer.write(
                                json.dumps(
                                    outgoing,
                                    sort_keys=True,
                                    separators=(",", ":"),
                                ).encode()
                                + b"\n"
                            )
                            await writer.drain()
                        except (ConnectionError, OSError):
                            pass
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass

        server = await asyncio.start_unix_server(handle, path=socket_path)
        try:
            yield socket_path, received
        finally:
            server.close()
            await server.wait_closed()


class TestPrimeSkill(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        sys.path.insert(0, str(SKILL_SRC))
        cls.skill = importlib.import_module("asterion_control")

    @classmethod
    def tearDownClass(cls) -> None:
        sys.path.remove(str(SKILL_SRC))
        sys.modules.pop("asterion_control", None)
        sys.modules.pop("asterion_control._protocol", None)

    async def test_invoke_requires_stable_idempotency_and_never_echoes_body(
        self,
    ) -> None:
        with self.assertRaises(ValueError) as raised:
            await self.skill.invoke_application(
                target=TARGET,
                input_text="SENTINEL_SECRET",
                idempotency_key="",
                budget=BUDGET,
            )
        self.assertNotIn("SENTINEL_SECRET", str(raised.exception))
        self.assertNotIn("SENTINEL_SECRET", repr(self.skill))

    async def test_public_functions_have_exact_snake_case_signatures(self) -> None:
        expected = {
            "portfolio",
            "remaining_budget",
            "invoke_application",
            "spawn_child",
            "message_child",
            "cancel_child",
            "request_checkpoint",
            "complete_goal",
            "fail_goal",
            "action_status",
        }
        self.assertEqual(expected, set(self.skill.__all__))
        for name in expected - {"portfolio", "remaining_budget"}:
            signature = inspect.signature(getattr(self.skill, name))
            self.assertTrue(
                all(
                    parameter.kind is inspect.Parameter.KEYWORD_ONLY
                    for parameter in signature.parameters.values()
                )
            )

    async def test_public_functions_emit_the_exact_closed_operation_set(self) -> None:
        response = {
            "protocol": "asterion.skill-control/v1",
            "status": "ok",
            "result": {},
        }
        async with _fake_bridge(response) as (socket_path, received):
            with patch.dict(
                os.environ,
                {
                    "ASTERION_CONTROL_SOCKET": str(socket_path),
                    "ASTERION_CONTROL_TOKEN": TOKEN,
                    "ASTERION_CONTROL_SESSION_ID": "session-1",
                },
                clear=False,
            ):
                await self.skill.portfolio()
                await self.skill.remaining_budget()
                await self.skill.invoke_application(
                    target=TARGET,
                    input_text="input",
                    idempotency_key="invoke-once",
                    budget=BUDGET,
                )
                await self.skill.spawn_child(
                    child_id="child-1",
                    goal_text="goal",
                    idempotency_key="spawn-once",
                    budget=BUDGET,
                )
                await self.skill.message_child(
                    child_id="child-1",
                    message="message",
                    idempotency_key="message-once",
                    budget=BUDGET,
                )
                await self.skill.cancel_child(
                    child_id="child-1",
                    idempotency_key="cancel-once",
                    budget=BUDGET,
                )
                await self.skill.request_checkpoint(
                    checkpoint_id="checkpoint-1",
                    idempotency_key="checkpoint-once",
                    budget=BUDGET,
                )
                await self.skill.complete_goal(
                    goal_id="goal-1",
                    summary="complete",
                    idempotency_key="complete-once",
                    budget=BUDGET,
                )
                await self.skill.fail_goal(
                    goal_id="goal-1",
                    reason="failed",
                    idempotency_key="fail-once",
                    budget=BUDGET,
                )
                await self.skill.action_status(action_id="action-1")

        self.assertEqual(
            [request["operation"] for request in received[1::2]],
            [
                "portfolio.get",
                "budget.get",
                "application.invoke",
                "child.spawn",
                "child.message",
                "child.cancel",
                "checkpoint.request",
                "goal.complete",
                "goal.fail",
                "action.status",
            ],
        )

    async def test_invoke_sends_exact_authenticated_request_and_freezes_result(
        self,
    ) -> None:
        response = {
            "protocol": "asterion.skill-control/v1",
            "status": "ok",
            "result": {
                "action_id": "action-1",
                "admission": {
                    "resolution": "admitted",
                    "reason_code": "authorized",
                },
                "terminal": {
                    "resolution": "succeeded",
                    "reason_code": "completed",
                },
                "result": {
                    "receipt_ref": "receipt-1",
                    "artifact_ids": ["artifact-1"],
                    "media_types": ["text/plain"],
                },
            },
        }
        async with _fake_bridge(response) as (socket_path, received):
            with patch.dict(
                os.environ,
                {
                    "ASTERION_CONTROL_SOCKET": str(socket_path),
                    "ASTERION_CONTROL_TOKEN": TOKEN,
                    "ASTERION_CONTROL_SESSION_ID": "session-1",
                },
                clear=False,
            ):
                result = await self.skill.invoke_application(
                    target=TARGET,
                    input_text="SENTINEL_SECRET",
                    idempotency_key="application-once-1",
                    budget=BUDGET,
                    expected_artifacts=("report.alpha",),
                )

        self.assertIsInstance(result, MappingProxyType)
        nested = result["result"]
        self.assertIsInstance(nested, MappingProxyType)
        self.assertEqual(nested["artifact_ids"], ("artifact-1",))
        self.assertEqual(
            received[0],
            {
                "protocol": "asterion.skill-control/v1",
                "type": "authenticate",
                "token": TOKEN,
                "session_id": "session-1",
            },
        )
        self.assertEqual(received[1]["operation"], "application.invoke")
        self.assertEqual(received[1]["session_id"], "session-1")
        payload = cast(dict[str, object], received[1]["payload"])
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["input_text"], "SENTINEL_SECRET")
        self.assertNotIn("token", received[1])

    async def test_environment_is_read_at_each_call(self) -> None:
        response = {
            "protocol": "asterion.skill-control/v1",
            "status": "ok",
            "result": [],
        }
        async with _fake_bridge(response) as (first_path, first_received):
            with patch.dict(
                os.environ,
                {
                    "ASTERION_CONTROL_SOCKET": str(first_path),
                    "ASTERION_CONTROL_TOKEN": TOKEN,
                    "ASTERION_CONTROL_SESSION_ID": "session-1",
                },
                clear=False,
            ):
                await self.skill.portfolio()
        async with _fake_bridge(response) as (second_path, second_received):
            with patch.dict(
                os.environ,
                {
                    "ASTERION_CONTROL_SOCKET": str(second_path),
                    "ASTERION_CONTROL_TOKEN": "44" * 32,
                    "ASTERION_CONTROL_SESSION_ID": "session-2",
                },
                clear=False,
            ):
                await self.skill.portfolio()
        self.assertEqual(first_received[0]["token"], TOKEN)
        self.assertEqual(second_received[0]["token"], "44" * 32)
        self.assertEqual(second_received[1]["session_id"], "session-2")

    async def test_discovers_control_record_from_prime_agent_dir_without_explicit_env(
        self,
    ) -> None:
        response = {
            "protocol": "asterion.skill-control/v1",
            "status": "ok",
            "result": [],
        }
        async with _fake_bridge(response) as (socket_path, received):
            with tempfile.TemporaryDirectory() as directory:
                discovery = Path(directory) / "asterion-control.json"
                discovery.write_text(
                    json.dumps(
                        {
                            "protocol": "asterion.skill-control-discovery/v1",
                            "socket_path": str(socket_path),
                            "token": TOKEN,
                            "session_id": "session-1",
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
                discovery.chmod(0o600)
                with patch.dict(
                    os.environ,
                    {
                        "PRIME_AGENT_CODING_AGENT_DIR": directory,
                    },
                    clear=True,
                ):
                    await self.skill.portfolio()

        self.assertEqual(received[0]["token"], TOKEN)
        self.assertEqual(received[1]["session_id"], "session-1")

    async def test_discovery_file_rejects_symlink_unsafe_mode_and_oversize(
        self,
    ) -> None:
        response = {
            "protocol": "asterion.skill-control/v1",
            "status": "ok",
            "result": [],
        }
        async with _fake_bridge(response) as (socket_path, _received):
            for case in ("symlink", "mode", "oversize"):
                with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    discovery = root / "asterion-control.json"
                    record = {
                        "protocol": "asterion.skill-control-discovery/v1",
                        "socket_path": str(socket_path),
                        "token": TOKEN,
                        "session_id": "session-1",
                    }
                    if case == "symlink":
                        target = root / "target.json"
                        target.write_text(json.dumps(record) + "\n")
                        target.chmod(0o600)
                        discovery.symlink_to(target)
                    elif case == "mode":
                        discovery.write_text(json.dumps(record) + "\n")
                        discovery.chmod(0o644)
                    else:
                        discovery.write_text(json.dumps({**record, "pad": "x" * 5000}))
                        discovery.chmod(0o600)
                    with patch.dict(
                        os.environ,
                        {"PRIME_AGENT_CODING_AGENT_DIR": directory},
                        clear=True,
                    ):
                        with self.assertRaises(self.skill.AsterionControlError) as raised:
                            await self.skill.portfolio()
                    self.assertNotIn(str(discovery), str(raised.exception))

    async def test_effect_disconnect_is_uncertain_but_query_disconnect_is_not(
        self,
    ) -> None:
        async with _fake_bridge(None) as (socket_path, _received):
            environment = {
                "ASTERION_CONTROL_SOCKET": str(socket_path),
                "ASTERION_CONTROL_TOKEN": TOKEN,
                "ASTERION_CONTROL_SESSION_ID": "session-1",
            }
            with patch.dict(os.environ, environment, clear=False):
                with self.assertRaises(
                    self.skill.AsterionControlUncertainError
                ) as effect:
                    await self.skill.fail_goal(
                        goal_id="goal-1",
                        reason="SENTINEL_PRIVATE_REASON",
                        idempotency_key="fail-once-1",
                        budget=BUDGET,
                    )
                self.assertNotIn("SENTINEL", str(effect.exception))
                with self.assertRaises(self.skill.AsterionControlError) as query:
                    await self.skill.remaining_budget()
                self.assertNotIsInstance(
                    query.exception, self.skill.AsterionControlUncertainError
                )

    async def test_rejects_mismatched_or_oversized_response_without_body(self) -> None:
        response: dict[str, object] = {
            "protocol": "asterion.skill-control/v1",
            "status": "ok",
            "result": "SENTINEL_PRIVATE_RESULT" * 10_000,
        }
        async with _fake_bridge(response) as (socket_path, _received):
            with patch.dict(
                os.environ,
                {
                    "ASTERION_CONTROL_SOCKET": str(socket_path),
                    "ASTERION_CONTROL_TOKEN": TOKEN,
                    "ASTERION_CONTROL_SESSION_ID": "session-1",
                },
                clear=False,
            ):
                with self.assertRaises(self.skill.AsterionControlError) as raised:
                    await self.skill.portfolio()
                self.assertNotIn("SENTINEL", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
