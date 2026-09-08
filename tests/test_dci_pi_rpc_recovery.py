from __future__ import annotations

import io
import tempfile
import threading
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import MagicMock, patch

from asterion.capabilities.dci.implementation.runtime.pi_rpc import PiRpcClient
from asterion.runtimes.pi_rpc import PiRpcConfig, PiRpcSession


def _client(root: Path) -> PiRpcClient:
    package = root / "pi" / "packages" / "coding-agent"
    package.mkdir(parents=True)
    agent = root / "agent"
    agent.mkdir()
    return PiRpcClient(
        package_dir=package,
        cwd=root,
        agent_dir=agent,
        provider="provider",
        model="model",
        tools="grep",
        show_tools=False,
        system_prompt_file=None,
        append_system_prompt_file=None,
        extra_args=(),
        literal_extra_args=(),
        keep_session=False,
        node_max_old_space_size_mb=None,
        stream_text=False,
    )


def _attach_transport(client: PiRpcClient) -> PiRpcSession:
    transport = PiRpcSession(
        PiRpcConfig(("unused",), client.cwd, {}, deadline_seconds=10.0)
    )
    client._session = transport
    return transport


class DciPiRpcRecoveryTests(unittest.TestCase):
    def test_settled_validation_uses_common_control_and_shared_request_ids(
        self,
    ) -> None:
        events = (
            {"type": "response", "id": "py-1", "success": True},
            {"type": "agent_start"},
            {"type": "turn_start"},
            {"type": "message_end", "message": {"role": "assistant"}},
            {"type": "agent_settled"},
        )
        state = {
            "isStreaming": False,
            "isCompacting": False,
            "messageCount": 1,
            "pendingMessageCount": 0,
        }
        with tempfile.TemporaryDirectory() as directory:
            client = _client(Path(directory).resolve())
            transport = _attach_transport(client)
            with (
                patch.object(transport, "send") as send,
                patch.object(transport, "read_json_line", side_effect=events),
                patch.object(client, "probe_protocol", return_value=state),
                patch(
                    "asterion.capabilities.dci.implementation.runtime.pi_rpc.time.sleep",
                    side_effect=AssertionError("direct settled wait"),
                ),
            ):
                answer = client.prompt_and_wait("question", timeout_seconds=1.0)
                next_request_id = client._next_id()

        self.assertEqual(answer, "")
        self.assertEqual(send.call_args.args[0]["id"], "py-1")
        self.assertEqual(next_request_id, "py-2")

    def test_prompt_lifecycle_is_driven_only_by_common_transport(self) -> None:
        responses = {
            "question": (
                {"type": "response", "id": "ignored-by-facade", "success": True},
                {"type": "agent_start"},
                {"type": "turn_start"},
                {"type": "message_end", "message": {"role": "assistant"}},
                {"type": "agent_end"},
            ),
            "recover final answer": (
                {"type": "response", "id": "ignored-by-facade", "success": True},
                {"type": "agent_start"},
                {"type": "turn_start"},
                {
                    "type": "message_update",
                    "assistantMessageEvent": {
                        "type": "text_delta",
                        "delta": "recovered answer",
                    },
                },
                {"type": "agent_end"},
            ),
        }

        def drive_prompt(message: str, **kwargs: object) -> float:
            on_event = kwargs["on_event"]
            control = MagicMock()
            for event in responses[message]:
                on_event(event, control)  # type: ignore[operator]
            return 0.75

        with tempfile.TemporaryDirectory() as directory:
            client = _client(Path(directory).resolve())
            transport = MagicMock()
            transport.drive_prompt.side_effect = drive_prompt
            client._session = transport
            with (
                patch.object(client, "_send", side_effect=AssertionError("direct send")),
                patch.object(
                    client,
                    "_read_json_line",
                    side_effect=AssertionError("direct read"),
                ),
                patch(
                    "asterion.capabilities.dci.implementation.runtime.pi_rpc.time.monotonic",
                    side_effect=AssertionError("direct deadline"),
                ),
            ):
                answer = client.prompt_and_wait(
                    "question",
                    max_turns=3,
                    timeout_seconds=1.0,
                    final_answer_recovery="recover final answer",
                )

        self.assertEqual(answer, "recovered answer")
        self.assertEqual(
            [call.args[0] for call in transport.drive_prompt.call_args_list],
            ["question", "recover final answer"],
        )
        self.assertEqual(
            [call.kwargs["timeout_seconds"] for call in transport.drive_prompt.call_args_list],
            [1.0, 0.75],
        )

    def test_recovery_frames_flow_unchanged_through_common_transport(self) -> None:
        events = (
            {"type": "response", "id": "py-1", "success": True},
            {"type": "agent_start"},
            {"type": "turn_start"},
            {"type": "message_end", "message": {"role": "assistant"}},
            {"type": "agent_end"},
            {"type": "response", "id": "py-2", "success": True},
            {"type": "agent_start"},
            {"type": "turn_start"},
            {
                "type": "message_update",
                "assistantMessageEvent": {
                    "type": "text_delta",
                    "delta": "recovered answer",
                },
            },
            {"type": "agent_end"},
        )
        with tempfile.TemporaryDirectory() as directory:
            client = _client(Path(directory).resolve())
            transport = _attach_transport(client)
            with (
                patch.object(transport, "send") as send,
                patch.object(transport, "read_json_line", side_effect=events),
            ):
                answer = client.prompt_and_wait(
                    "question",
                    max_turns=3,
                    final_answer_recovery="recover final answer",
                )

        self.assertEqual(answer, "recovered answer")
        self.assertEqual(
            [call.args[0] for call in send.call_args_list],
            [
                {"id": "py-1", "type": "prompt", "message": "question"},
                {
                    "id": "py-2",
                    "type": "prompt",
                    "message": "recover final answer",
                },
            ],
        )

    def test_tool_using_recovery_shares_the_original_turn_limit(self) -> None:
        events = (
            {"type": "response", "id": "py-1", "success": True},
            {"type": "agent_start"},
            {"type": "turn_start"},
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "stopReason": "stop",
                    "content": [],
                },
            },
            {"type": "agent_end"},
            {"type": "response", "id": "py-2", "success": True},
            {"type": "agent_start"},
            {"type": "turn_start"},
            {
                "type": "tool_execution_start",
                "toolCallId": "tool-1",
                "toolName": "grep",
            },
            {
                "type": "tool_execution_end",
                "toolCallId": "tool-1",
                "toolName": "grep",
                "isError": False,
            },
            {"type": "turn_start"},
            {
                "type": "message_update",
                "assistantMessageEvent": {
                    "type": "text_delta",
                    "delta": "recovered answer",
                },
            },
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "stopReason": "stop",
                    "content": [
                        {"type": "text", "text": "recovered answer"}
                    ],
                },
            },
            {"type": "agent_end"},
        )
        with tempfile.TemporaryDirectory() as directory:
            client = _client(Path(directory).resolve())
            transport = _attach_transport(client)
            with (
                patch.object(transport, "send") as send,
                patch.object(transport, "read_json_line", side_effect=events),
            ):
                answer = client.prompt_and_wait(
                    "question",
                    max_turns=3,
                    timeout_seconds=1.0,
                    final_answer_recovery="recover final answer",
                )

        self.assertEqual(answer, "recovered answer")
        self.assertEqual(
            [call.args[0] for call in send.call_args_list],
            [
                {"id": "py-1", "type": "prompt", "message": "question"},
                {
                    "id": "py-2",
                    "type": "prompt",
                    "message": "recover final answer",
                },
            ],
        )

    def test_unbounded_primary_prompt_keeps_recovery_at_one_turn(self) -> None:
        events = (
            {"type": "response", "id": "py-1", "success": True},
            {"type": "agent_start"},
            {"type": "turn_start"},
            {"type": "message_end", "message": {"role": "assistant"}},
            {"type": "agent_end"},
            {"type": "response", "id": "py-2", "success": True},
            {"type": "agent_start"},
            {"type": "turn_start"},
            {"type": "turn_start"},
            {"type": "agent_end"},
        )
        with tempfile.TemporaryDirectory() as directory:
            client = _client(Path(directory).resolve())
            transport = _attach_transport(client)
            with (
                patch.object(transport, "send") as send,
                patch.object(transport, "read_json_line", side_effect=events),
                redirect_stderr(io.StringIO()) as stderr,
            ):
                client.prompt_and_wait(
                    "question",
                    max_turns=None,
                    final_answer_recovery="recover final answer",
                )

        self.assertEqual(
            [call.args[0]["type"] for call in send.call_args_list],
            ["prompt", "prompt", "abort"],
        )
        self.assertIn("Reached max_turns=1", stderr.getvalue())

    def test_exhausted_turn_budget_does_not_send_recovery_prompt(self) -> None:
        events = (
            {"type": "response", "id": "py-1", "success": True},
            {"type": "agent_start"},
            {"type": "turn_start"},
            {"type": "message_end", "message": {"role": "assistant"}},
            {"type": "agent_end"},
        )
        with tempfile.TemporaryDirectory() as directory:
            client = _client(Path(directory).resolve())
            transport = _attach_transport(client)
            with (
                patch.object(transport, "send") as send,
                patch.object(transport, "read_json_line", side_effect=events),
            ):
                answer = client.prompt_and_wait(
                    "question",
                    max_turns=1,
                    final_answer_recovery="recover final answer",
                )

        self.assertEqual(answer, "")
        self.assertEqual(
            [call.args[0]["type"] for call in send.call_args_list],
            ["prompt"],
        )

    def test_empty_recovery_is_single_shot(self) -> None:
        events = (
            {"type": "response", "id": "py-1", "success": True},
            {"type": "agent_start"},
            {"type": "turn_start"},
            {"type": "message_end", "message": {"role": "assistant"}},
            {"type": "agent_end"},
            {"type": "response", "id": "py-2", "success": True},
            {"type": "agent_start"},
            {"type": "turn_start"},
            {"type": "message_end", "message": {"role": "assistant"}},
            {"type": "agent_end"},
        )
        with tempfile.TemporaryDirectory() as directory:
            client = _client(Path(directory).resolve())
            transport = _attach_transport(client)
            with (
                patch.object(transport, "send") as send,
                patch.object(transport, "read_json_line", side_effect=events),
            ):
                answer = client.prompt_and_wait(
                    "question",
                    max_turns=4,
                    final_answer_recovery="recover final answer",
                )

        self.assertEqual(answer, "")
        self.assertEqual(
            [call.args[0]["type"] for call in send.call_args_list],
            ["prompt", "prompt"],
        )

    def test_cancellation_before_recovery_prevents_second_prompt(self) -> None:
        cancel_event = threading.Event()
        events = iter(
            (
                {"type": "response", "id": "py-1", "success": True},
                {"type": "agent_start"},
                {"type": "turn_start"},
                {"type": "message_end", "message": {"role": "assistant"}},
                {"type": "agent_end"},
            )
        )

        def read_event(*, timeout_seconds: float | None = None) -> dict[str, object]:
            del timeout_seconds
            event = next(events)
            if event["type"] == "agent_end":
                cancel_event.set()
            return event

        with tempfile.TemporaryDirectory() as directory:
            client = _client(Path(directory).resolve())
            transport = _attach_transport(client)
            with (
                patch.object(transport, "send") as send,
                patch.object(
                    transport, "read_json_line", side_effect=read_event
                ),
                self.assertRaisesRegex(RuntimeError, "cancelled"),
            ):
                client.prompt_and_wait(
                    "question",
                    max_turns=4,
                    cancel_event=cancel_event,
                    final_answer_recovery="recover final answer",
                )

        self.assertEqual(
            [call.args[0]["type"] for call in send.call_args_list],
            ["prompt"],
        )


if __name__ == "__main__":
    unittest.main()
