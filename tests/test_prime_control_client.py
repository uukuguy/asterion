from __future__ import annotations

import asyncio
import base64
import hashlib
import unittest
from collections.abc import AsyncIterator, Mapping

from asterion.control.host import ControlCommand, EventCursor
from asterion.control.session_context import (
    SessionContextCommand,
    SessionContextReceipt,
)
from asterion.control.providers.prime.client import (
    MAX_PRIVATE_TEXT_BYTES,
    PrimeControlError,
    PrimeControlPlaneClient,
)
from asterion.control.execution import ActionExecutionReceipt
from asterion.control.authority import BudgetUsage, RemainingBudget


class FakeResolver:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.byte_values: dict[str, bytes] = {}
        self.requests: list[tuple[str, int]] = []
        self.byte_requests: list[tuple[str, str, str, int, int]] = []

    def resolve_text(self, reference: str, *, max_bytes: int) -> str:
        self.requests.append((reference, max_bytes))
        return self.values[reference]

    def resolve_bytes(
        self,
        reference: str,
        *,
        expected_media_type: str,
        expected_sha256: str,
        expected_size: int,
        max_bytes: int,
    ) -> bytes:
        self.byte_requests.append(
            (
                reference,
                expected_media_type,
                expected_sha256,
                expected_size,
                max_bytes,
            )
        )
        return self.byte_values[reference]


class FakeProcess:
    def __init__(self) -> None:
        self.requests: list[Mapping[str, object]] = []
        self.event_requests: list[Mapping[str, object]] = []
        self.closed = 0
        self.failure: Exception | None = None
        self.close_failures = 0
        self.response: Mapping[str, object] | None = None
        self.event_values: list[Mapping[str, object]] = []
        self.private_values: dict[str, str] = {}

    def fail_with(self, message: str) -> None:
        self.failure = RuntimeError(message)

    async def request(self, envelope: Mapping[str, object]) -> Mapping[str, object]:
        self.requests.append(envelope)
        if self.failure is not None:
            raise self.failure
        if self.response is not None:
            if self.response.get("id") == "<request>":
                return {**self.response, "id": envelope["id"]}
            return self.response
        if envelope.get("type") == "private.read":
            return {
                "protocol": "asterion.prime-gateway-ipc/v1",
                "id": envelope["id"],
                "type": "private.value",
                "text": self.private_values[str(envelope["reference"])],
            }
        if envelope.get("type") == "authority.update":
            return {
                "protocol": "asterion.prime-gateway-ipc/v1",
                "id": envelope["id"],
                "type": "authority.accepted",
            }
        return {
            "protocol": "asterion.prime-gateway-ipc/v1",
            "id": envelope["id"],
            "type": "command.accepted",
        }

    def events(self, envelope: Mapping[str, object]) -> AsyncIterator[Mapping[str, object]]:
        self.event_requests.append(envelope)
        return self._events()

    async def _events(self) -> AsyncIterator[Mapping[str, object]]:
        for value in self.event_values:
            yield value

    async def close(self) -> None:
        self.closed += 1
        if self.close_failures > 0:
            self.close_failures -= 1
            raise RuntimeError("SENTINEL_CLOSE_FAILURE")


def create_command() -> ControlCommand:
    return ControlCommand(
        command_id="command-1",
        session_id="session-1",
        authority_revision=1,
        type="session.create",
        payload={
            "system_id": "research.system",
            "system_version": "1.0.0",
            "goal_id": "goal-1",
            "goal_ref": "goal-ref-1",
        },
    )


def input_command() -> ControlCommand:
    return ControlCommand(
        command_id="command-2",
        session_id="session-1",
        authority_revision=1,
        type="input.submit",
        payload={
            "input_id": "input-1",
            "delivery": "direct",
            "content_ref": "content-ref-1",
        },
    )


def terminal_command() -> ControlCommand:
    return ControlCommand(
        command_id="terminal:action-1",
        session_id="session-1",
        authority_revision=1,
        type="action.resolve",
        payload={
            "action_id": "action-1",
            "resolution": "succeeded",
            "reason_code": "executed",
            "receipt_ref": "receipt-1",
        },
    )


def failed_terminal_command() -> ControlCommand:
    return ControlCommand(
        command_id="terminal:action-1",
        session_id="session-1",
        authority_revision=1,
        type="action.resolve",
        payload={
            "action_id": "action-1",
            "resolution": "failed",
            "reason_code": "executor-failed",
            "receipt_ref": "failure-receipt-1",
        },
    )


def event(sequence: int) -> Mapping[str, object]:
    return {
        "protocol": "asterion.agent-control/v1",
        "event_id": f"event-{sequence}",
        "session_id": "session-1",
        "generation": 1,
        "sequence": sequence,
        "emitted_at": f"2026-08-10T03:00:0{sequence}Z",
        "type": "session.running",
        "payload": {"reason_code": "started"},
    }


def context_command() -> SessionContextCommand:
    return SessionContextCommand(
        command_id="context-command-1",
        session_id="session-1",
        generation=1,
        authority_revision=1,
        idempotency_key="context-operation-1",
        operation="session.tree.read",
        payload={"continuation_id": "continuation-1"},
    )


def context_receipt() -> SessionContextReceipt:
    return SessionContextReceipt(
        receipt_id="context-receipt-1",
        command_id="context-command-1",
        session_id="session-1",
        generation=1,
        operation="session.tree.read",
        status="succeeded",
        reason_code="session-context-succeeded",
        payload={
            "evidence_ref": "evidence-1",
            "result": {
                "continuation_id": "continuation-1",
                "nodes": [],
                "leaf_id": None,
            },
        },
    )


def attachment_command() -> SessionContextCommand:
    body = b"private-image-bytes"
    return SessionContextCommand(
        command_id="context-command-attachment",
        session_id="session-1",
        generation=1,
        authority_revision=1,
        idempotency_key="context-operation-attachment",
        operation="session.attachment.bind",
        payload={
            "input_id": "input-1",
            "attachment_id": "attachment-1",
            "body_ref": "attachment-body-1",
            "media_type": "image/png",
            "sha256": hashlib.sha256(body).hexdigest(),
            "size": len(body),
        },
    )


def attachment_receipt() -> SessionContextReceipt:
    command = attachment_command()
    return SessionContextReceipt(
        receipt_id="context-receipt-attachment",
        command_id=command.command_id,
        session_id=command.session_id,
        generation=command.generation,
        operation=command.operation,
        status="succeeded",
        reason_code="session-context-succeeded",
        payload={
            "evidence_ref": None,
            "result": {
                "input_id": "input-1",
                "attachment_id": "attachment-1",
                "media_type": "image/png",
                "sha256": command.payload["sha256"],
                "size": command.payload["size"],
            },
        },
    )


def failed_context_receipt(command: SessionContextCommand) -> SessionContextReceipt:
    return SessionContextReceipt(
        receipt_id=f"receipt:{command.command_id}",
        command_id=command.command_id,
        session_id=command.session_id,
        generation=command.generation,
        operation=command.operation,
        status="failed",
        reason_code="provider-not-ready",
        payload={"evidence_ref": None, "result": None},
    )


class TestPrimeControlClient(unittest.IsolatedAsyncioTestCase):
    async def test_session_context_text_values_use_only_closed_private_fields(
        self,
    ) -> None:
        budget = {
            "controller_tokens": 10,
            "application_tokens": 0,
            "child_tokens": 0,
            "aggregate_tokens": 10,
            "cost_micros": 10,
            "deadline_ms": 1_000,
        }
        cases = (
            (
                "session.name.set",
                {"name_ref": "name-ref-1"},
                "name-ref-1",
                {"name": "SENTINEL_PRIVATE_NAME"},
            ),
            (
                "session.label.set",
                {
                    "continuation_id": "continuation-1",
                    "entry_id": "entry-1",
                    "label_ref": "label-ref-1",
                },
                "label-ref-1",
                {"label": "SENTINEL_PRIVATE_LABEL"},
            ),
            (
                "session.compact",
                {
                    "continuation_id": "continuation-1",
                    "instructions_ref": "instructions-ref-1",
                    "budget": budget,
                },
                "instructions-ref-1",
                {"instructions": "SENTINEL_PRIVATE_INSTRUCTIONS"},
            ),
        )
        for index, (operation, payload, reference, expected_private) in enumerate(
            cases,
            start=1,
        ):
            with self.subTest(operation=operation):
                resolver = FakeResolver()
                resolver.values[reference] = next(iter(expected_private.values()))
                command = SessionContextCommand(
                    command_id=f"context-command-text-{index}",
                    session_id="session-1",
                    generation=1,
                    authority_revision=1,
                    idempotency_key=f"context-operation-text-{index}",
                    operation=operation,
                    payload=payload,
                )
                fake_process = FakeProcess()
                fake_process.response = {
                    "protocol": "asterion.prime-gateway-ipc/v1",
                    "id": "<request>",
                    "type": "session-context.receipt",
                    "receipt": failed_context_receipt(command).to_mapping(),
                }
                client = PrimeControlPlaneClient(
                    process=fake_process,
                    private_content=resolver,
                )

                await client.execute_session_context(command)

                self.assertEqual(fake_process.requests[0]["private"], expected_private)
                self.assertEqual(
                    resolver.requests,
                    [(reference, 1024 * 1024)],
                )

    async def test_session_context_attachment_resolves_verified_bytes_privately(
        self,
    ) -> None:
        resolver = FakeResolver()
        resolver.byte_values["attachment-body-1"] = b"private-image-bytes"
        fake_process = FakeProcess()
        fake_process.response = {
            "protocol": "asterion.prime-gateway-ipc/v1",
            "id": "<request>",
            "type": "session-context.receipt",
            "receipt": attachment_receipt().to_mapping(),
        }
        client = PrimeControlPlaneClient(
            process=fake_process,
            private_content=resolver,
        )

        await client.execute_session_context(attachment_command())

        envelope = fake_process.requests[0]
        self.assertEqual(
            envelope["private"],
            {
                "body_base64": base64.b64encode(
                    b"private-image-bytes"
                ).decode("ascii")
            },
        )
        command = attachment_command()
        self.assertEqual(
            resolver.byte_requests,
            [
                (
                    "attachment-body-1",
                    "image/png",
                    str(command.payload["sha256"]),
                    len(b"private-image-bytes"),
                    8 * 1024 * 1024,
                )
            ],
        )

    async def test_session_context_attachment_rechecks_private_digest_and_size(
        self,
    ) -> None:
        resolver = FakeResolver()
        resolver.byte_values["attachment-body-1"] = b"tampered"
        fake_process = FakeProcess()
        client = PrimeControlPlaneClient(
            process=fake_process,
            private_content=resolver,
        )

        with self.assertRaises(PrimeControlError):
            await client.execute_session_context(attachment_command())

        self.assertEqual(fake_process.requests, [])

    async def test_session_context_uses_the_same_sidecar_and_validates_receipt(
        self,
    ) -> None:
        fake_process = FakeProcess()
        fake_process.response = {
            "protocol": "asterion.prime-gateway-ipc/v1",
            "id": "<request>",
            "type": "session-context.receipt",
            "receipt": context_receipt().to_mapping(),
        }
        client = PrimeControlPlaneClient(
            process=fake_process,
            private_content=FakeResolver(),
        )

        receipt = await client.execute_session_context(context_command())

        self.assertEqual(receipt.receipt_id, "context-receipt-1")
        self.assertEqual(len(fake_process.requests), 1)
        self.assertEqual(fake_process.requests[0]["type"], "session-context.execute")
        self.assertEqual(fake_process.requests[0]["private"], {})
        await client.close()
        self.assertEqual(fake_process.closed, 1)

    async def test_session_context_rejects_mismatched_or_private_response(self) -> None:
        fake_process = FakeProcess()
        response = dict(context_receipt().to_mapping())
        response["command_id"] = "context-command-other"
        response["provider_payload"] = "SENTINEL_SECRET"
        fake_process.response = {
            "protocol": "asterion.prime-gateway-ipc/v1",
            "id": "<request>",
            "type": "session-context.receipt",
            "receipt": response,
        }
        client = PrimeControlPlaneClient(
            process=fake_process,
            private_content=FakeResolver(),
        )

        with self.assertRaises(PrimeControlError) as raised:
            await client.execute_session_context(context_command())

        self.assertNotIn("SENTINEL_SECRET", str(raised.exception))

    async def test_session_context_cancellation_uses_exact_command_identity(
        self,
    ) -> None:
        fake_process = FakeProcess()
        fake_process.response = {
            "protocol": "asterion.prime-gateway-ipc/v1",
            "id": "<request>",
            "type": "session-context.cancel.accepted",
        }
        client = PrimeControlPlaneClient(
            process=fake_process,
            private_content=FakeResolver(),
        )

        await client.cancel_session_context("context-command-1")

        self.assertEqual(
            fake_process.requests[0]["command_id"], "context-command-1"
        )
    async def test_remaining_budget_update_is_private_and_exact(self) -> None:
        fake_process = FakeProcess()
        client = PrimeControlPlaneClient(
            process=fake_process,
            private_content=FakeResolver(),
        )

        await client.sync_authority_snapshot(
            RemainingBudget(1, 2, 3, 4, 5, 0)
        )

        envelope = fake_process.requests[0]
        self.assertEqual(envelope["type"], "authority.update")
        self.assertEqual(
            envelope["budget"],
            {
                "controller_tokens": 1,
                "application_tokens": 2,
                "child_tokens": 3,
                "aggregate_tokens": 4,
                "cost_micros": 5,
                "deadline_ms": 0,
            },
        )

    async def test_command_is_accepted_only_after_sidecar_ack(self) -> None:
        fake_process = FakeProcess()
        resolver = FakeResolver()
        resolver.values["goal-ref-1"] = "private goal"
        client = PrimeControlPlaneClient(
            process=fake_process,
            private_content=resolver,
        )

        await client.send(create_command())

        self.assertEqual(fake_process.requests[0]["command"]["command_id"], "command-1")  # type: ignore[index]
        self.assertEqual(fake_process.requests[0]["private"], {"goal": "private goal"})
        self.assertEqual(resolver.requests[0][0], "goal-ref-1")

    async def test_private_goal_is_not_rendered_on_sidecar_failure(self) -> None:
        fake_process = FakeProcess()
        resolver = FakeResolver()
        resolver.values["goal-ref-1"] = "SENTINEL_SECRET"
        fake_process.fail_with("SENTINEL_SECRET provider body")
        client = PrimeControlPlaneClient(
            process=fake_process,
            private_content=resolver,
        )

        with self.assertRaises(PrimeControlError) as raised:
            await client.send(create_command())

        self.assertNotIn("SENTINEL_SECRET", str(raised.exception))

    async def test_sidecar_error_response_is_recognized_and_redacted(self) -> None:
        fake_process = FakeProcess()
        resolver = FakeResolver()
        resolver.values["goal-ref-1"] = "SENTINEL_SECRET"
        fake_process.response = {
            "protocol": "asterion.prime-gateway-ipc/v1",
            "id": "<request>",
            "type": "error",
            "code": "prime-gateway-sidecar-failed",
        }
        client = PrimeControlPlaneClient(
            process=fake_process,
            private_content=resolver,
        )

        with self.assertRaises(PrimeControlError) as raised:
            await client.send(create_command())

        self.assertNotIn("SENTINEL_SECRET", str(raised.exception))

    async def test_input_content_is_resolved_in_private_sidecar_field(self) -> None:
        fake_process = FakeProcess()
        resolver = FakeResolver()
        resolver.values["content-ref-1"] = "private input"
        client = PrimeControlPlaneClient(
            process=fake_process,
            private_content=resolver,
        )

        await client.send(input_command())

        self.assertEqual(fake_process.requests[0]["private"], {"content": "private input"})

    async def test_prepared_provider_input_is_cached_for_sync_resolver(self) -> None:
        fake_process = FakeProcess()
        fake_process.private_values["private:input-1"] = "SENTINEL_PROVIDER_INPUT"
        resolver = FakeResolver()
        client = PrimeControlPlaneClient(
            process=fake_process,
            private_content=resolver,
        )

        await client.prepare_private_input("private:input-1")

        self.assertEqual(
            client.resolve_text("private:input-1", max_bytes=MAX_PRIVATE_TEXT_BYTES),
            "SENTINEL_PROVIDER_INPUT",
        )
        self.assertEqual(resolver.requests, [])
        self.assertEqual(fake_process.requests[0]["type"], "private.read")
        client.release_private_input("private:input-1")
        with self.assertRaises(KeyError):
            client.resolve_text("private:input-1", max_bytes=MAX_PRIVATE_TEXT_BYTES)

    async def test_successful_action_resolution_carries_public_safe_private_projection(
        self,
    ) -> None:
        fake_process = FakeProcess()
        client = PrimeControlPlaneClient(
            process=fake_process,
            private_content=FakeResolver(),
        )
        client.bind_action_result(
            ActionExecutionReceipt(
                action_id="action-1",
                receipt_ref="receipt-1",
                usage=BudgetUsage(0, 1, 0, 1, 0),
                artifact_ids=("artifact-1",),
                media_types=("text/plain",),
            )
        )

        await client.send(terminal_command())

        self.assertEqual(
            fake_process.requests[0]["private"],
            {
                "result": {
                    "receipt_ref": "receipt-1",
                    "artifact_ids": ["artifact-1"],
                    "media_types": ["text/plain"],
                }
            },
        )

    async def test_failed_action_resolution_with_receipt_carries_no_private_result(
        self,
    ) -> None:
        fake_process = FakeProcess()
        client = PrimeControlPlaneClient(
            process=fake_process,
            private_content=FakeResolver(),
        )

        await client.send(failed_terminal_command())

        self.assertEqual(fake_process.requests[0]["private"], {})

    async def test_events_use_exact_cursor_and_validate_public_events(self) -> None:
        fake_process = FakeProcess()
        fake_process.event_values = [event(3)]
        client = PrimeControlPlaneClient(
            process=fake_process,
            private_content=FakeResolver(),
        )

        replay = [
            item async for item in client.events(EventCursor(generation=1, sequence=2))
        ]

        self.assertEqual([item.sequence for item in replay], [3])
        self.assertEqual(
            fake_process.event_requests[0]["cursor"],
            {"generation": 1, "sequence": 2},
        )

    async def test_invalid_sidecar_event_fails_closed(self) -> None:
        fake_process = FakeProcess()
        fake_process.event_values = [{"type": "provider.payload", "body": "SENTINEL_SECRET"}]
        client = PrimeControlPlaneClient(
            process=fake_process,
            private_content=FakeResolver(),
        )

        with self.assertRaises(PrimeControlError) as raised:
            _ = [item async for item in client.events()]

        self.assertNotIn("SENTINEL_SECRET", str(raised.exception))

    async def test_close_delegates_to_sidecar_once(self) -> None:
        fake_process = FakeProcess()
        client = PrimeControlPlaneClient(
            process=fake_process,
            private_content=FakeResolver(),
        )

        await client.close()
        await client.close()

        self.assertEqual(fake_process.closed, 1)

    async def test_close_is_retryable_after_transport_failure(self) -> None:
        fake_process = FakeProcess()
        fake_process.close_failures = 1
        client = PrimeControlPlaneClient(
            process=fake_process,
            private_content=FakeResolver(),
        )

        with self.assertRaises(PrimeControlError) as raised:
            await client.close()
        self.assertNotIn("SENTINEL_CLOSE_FAILURE", str(raised.exception))

        await client.close()

        self.assertEqual(fake_process.closed, 2)

    async def test_concurrent_close_shares_one_transport_close(self) -> None:
        fake_process = FakeProcess()
        client = PrimeControlPlaneClient(
            process=fake_process,
            private_content=FakeResolver(),
        )

        await asyncio.gather(client.close(), client.close())

        self.assertEqual(fake_process.closed, 1)


if __name__ == "__main__":
    unittest.main()
