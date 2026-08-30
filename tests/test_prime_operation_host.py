"""Tests for the private, operator-owned Prime operation callback."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from asterion.control.providers.prime.operation_host import (
    PRIME_OPERATION_HOST_PROTOCOL,
    PrimeOperationHostError,
    PrimeManagedOperationTransport,
    PrimeOperationHostServer,
)
from asterion.control.providers.prime.process import PrimeSidecarProcessError
from asterion.operation.protocol import (
    EFFECT_COUNTERS,
    OperationReceipt,
    OperationTransaction,
)
from asterion.operation.services import OperationDispatcher


TOKEN = "a" * 64


def _transaction() -> OperationTransaction:
    return OperationTransaction.from_mapping(
        {
            "protocol": "asterion.operation/v1",
            "operation_id": "operation-1",
            "request": {
                "protocol": "asterion.operation/v1",
                "request_kind": "operation.auth-request",
                "request_ref": "request-1",
                "request_sha256": "b" * 64,
                "media_type": "application/json",
                "byte_count": 24,
                "purpose": "operation.auth",
                "client_id": "client-1",
                "session_id": "session-1",
                "generation": 2,
                "authority_revision": 3,
            },
            "session_id": "session-1",
            "client_id": "client-1",
            "generation": 2,
            "authority_revision": 3,
            "authority_id": "authority-1",
            "idempotency_key": "key-operation-1",
            "feature_id": "operation.auth",
            "requested_at": "2026-08-30T10:00:00Z",
        }
    )


def _receipt(
    transaction: OperationTransaction, *, status: str = "succeeded"
) -> OperationReceipt:
    return OperationReceipt.from_mapping(
        {
            "protocol": "asterion.operation/v1",
            "receipt_id": f"receipt-{transaction.operation_id}",
            "operation_id": transaction.operation_id,
            "request_ref": transaction.request.request_ref,
            "request_sha256": transaction.request.request_sha256,
            "purpose": transaction.request.purpose,
            "session_id": transaction.session_id,
            "client_id": transaction.client_id,
            "generation": transaction.generation,
            "authority_revision": transaction.authority_revision,
            "authority_id": transaction.authority_id,
            "idempotency_key": transaction.idempotency_key,
            "feature_id": transaction.feature_id,
            "status": status,
            "reason_code": f"operation-{status}",
            "receipt_ref": f"public-{transaction.operation_id}",
            "reconciliation_ref": None,
            "effect_counts": {counter: 0 for counter in EFFECT_COUNTERS},
            "completed_at": "2026-08-30T10:00:01Z",
        }
    )


class RecordingDispatcher:
    session_id = "session-1"
    generation = 2
    authority_id = "authority-1"
    authority_revision = 3

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.wait: asyncio.Event | None = None
        self.error: Exception | None = None
        self.receipt_override: OperationReceipt | None = None

    async def execute(self, transaction: OperationTransaction) -> OperationReceipt:
        return await self._dispatch("execute", transaction)

    async def reconcile(self, transaction: OperationTransaction) -> OperationReceipt:
        return await self._dispatch("reconcile", transaction)

    async def cancel(
        self, operation_id: str, *, authority_revision: int
    ) -> OperationReceipt:
        self.calls.append(("cancel", (operation_id, authority_revision)))
        if self.wait is not None:
            await self.wait.wait()
        if self.error is not None:
            raise self.error
        return self.receipt_override or _receipt(_transaction(), status="cancelled")

    async def _dispatch(
        self, kind: str, transaction: OperationTransaction
    ) -> OperationReceipt:
        self.calls.append((kind, transaction))
        if self.wait is not None:
            await self.wait.wait()
        if self.error is not None:
            raise self.error
        return self.receipt_override or _receipt(transaction)


def _request(kind: str, request_id: str = "request-1") -> dict[str, object]:
    request: dict[str, object] = {
        "protocol": PRIME_OPERATION_HOST_PROTOCOL,
        "id": request_id,
        "type": f"operation.{kind}",
        "token": TOKEN,
        "session_id": "session-1",
        "generation": 2,
        "authority_id": "authority-1",
        "authority_revision": 3,
    }
    if kind == "cancel":
        request["operation_id"] = "operation-1"
    else:
        request["transaction"] = _plain(_transaction().to_mapping())
    return request


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(child) for child in value]
    return value


class TestPrimeOperationHost(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.private_root = Path(self.temporary.name).resolve()
        self.dispatcher = RecordingDispatcher()
        self.server = PrimeOperationHostServer(
            dispatcher=self.dispatcher,
            private_root=self.private_root,
            token=TOKEN,
            request_timeout=0.1,
        )

    async def asyncTearDown(self) -> None:
        await self.server.close()
        self.temporary.cleanup()

    async def _exchange(
        self, request: dict[str, object] | bytes, *, extra: bytes = b""
    ) -> dict[str, object] | None:
        socket_path = str(self.server.descriptor["socketPath"])
        reader, writer = await asyncio.open_unix_connection(socket_path)
        frame = (
            request
            if isinstance(request, bytes)
            else json.dumps(request, separators=(",", ":")).encode() + b"\n"
        )
        writer.write(frame + extra)
        await writer.drain()
        writer.write_eof()
        response = await reader.readline()
        writer.close()
        await writer.wait_closed()
        return json.loads(response) if response else None

    async def test_exact_requests_dispatch_once_and_return_exact_receipt(self) -> None:
        await self.server.start()
        for kind in ("execute", "reconcile", "cancel"):
            with self.subTest(kind=kind):
                response = await self._exchange(_request(kind, f"request-{kind}"))
                self.assertEqual(
                    set(response or {}), {"protocol", "id", "type", "receipt"}
                )
                assert response is not None
                self.assertEqual(response["protocol"], PRIME_OPERATION_HOST_PROTOCOL)
                self.assertEqual(response["id"], f"request-{kind}")
                self.assertEqual(response["type"], "operation.receipt")
                self.assertEqual(
                    response["receipt"]["operation_id"],  # type: ignore[index]
                    "operation-1",
                )
        self.assertEqual(
            [call[0] for call in self.dispatcher.calls],
            ["execute", "reconcile", "cancel"],
        )

    async def test_descriptor_is_immutable_and_socket_is_private_and_removed(
        self,
    ) -> None:
        descriptor = self.server.descriptor
        self.assertEqual(
            descriptor,
            {
                "socketPath": str(self.private_root.resolve() / "prime-operation.sock"),
                "token": TOKEN,
            },
        )
        with self.assertRaises(TypeError):
            descriptor["token"] = "c" * 64  # type: ignore[index]
        self.assertNotIn(TOKEN, repr(self.server))
        self.assertNotIn(str(self.private_root), repr(self.server))

        await self.server.start()
        socket_path = Path(descriptor["socketPath"])
        self.assertEqual(socket_path.stat().st_mode & 0o777, 0o600)
        await self.server.close()
        await self.server.close()
        self.assertFalse(socket_path.exists())
        with self.assertRaises(PrimeOperationHostError):
            await self.server.start()

    async def test_invalid_request_matrix_fails_closed_before_dispatch(self) -> None:
        await self.server.start()
        cases: dict[str, dict[str, object]] = {}
        for label, field, value in (
            ("token", "token", "c" * 64),
            ("session", "session_id", "session-2"),
            ("generation", "generation", 4),
            ("authority", "authority_id", "authority-2"),
            ("revision", "authority_revision", 4),
            ("protocol", "protocol", "asterion.hostile/v1"),
        ):
            candidate = _request("execute", f"request-{label}")
            candidate[field] = value
            cases[label] = candidate
        unknown = _request("execute", "request-unknown")
        unknown["private_body"] = "SENTINEL-BODY"
        cases["unknown"] = unknown
        transaction_identity = _request("execute", "request-transaction")
        transaction = _plain(transaction_identity["transaction"])
        assert isinstance(transaction, dict)
        transaction["authority_id"] = "authority-2"
        transaction_identity["transaction"] = transaction
        cases["transaction"] = transaction_identity

        for label, request in cases.items():
            with self.subTest(label=label):
                self.assertEqual(
                    await self._exchange(request),
                    {
                        "protocol": PRIME_OPERATION_HOST_PROTOCOL,
                        "id": request["id"],
                        "type": "error",
                        "code": "operation-host-failed",
                    },
                )
        self.assertEqual(self.dispatcher.calls, [])

        invalid_id = _request("execute", "bad id")
        self.assertIsNone(await self._exchange(invalid_id))
        self.assertEqual(self.dispatcher.calls, [])

    async def test_duplicate_extra_trailing_and_oversized_frames_fail_closed(
        self,
    ) -> None:
        await self.server.start()
        duplicate = (
            json.dumps(_request("execute"))
            .replace('"id": "request-1"', '"id": "request-1", "id": "request-2"')
            .encode()
            + b"\n"
        )
        self.assertIsNone(await self._exchange(duplicate))
        self.assertEqual(
            (
                await self._exchange(
                    _request("execute", "request-extra"), extra=b"{}\n"
                )
                or {}
            ).get("code"),
            "operation-host-failed",
        )
        trailing = json.dumps(_request("execute", "request-trailing")).encode()
        self.assertEqual(
            (await self._exchange(trailing + b"\nX") or {}).get("code"),
            "operation-host-failed",
        )
        oversized = b"{" + b"x" * 70_000 + b"}\n"
        self.assertIsNone(await self._exchange(oversized))
        self.assertEqual(self.dispatcher.calls, [])

    async def test_request_requires_half_close_and_rejects_delayed_trailing_data(
        self,
    ) -> None:
        await self.server.start()
        socket_path = str(self.server.descriptor["socketPath"])

        reader, writer = await asyncio.open_unix_connection(socket_path)
        writer.write(json.dumps(_request("execute", "request-open")).encode() + b"\n")
        await writer.drain()
        response = json.loads((await reader.readline()).decode())
        self.assertEqual(response["code"], "operation-host-failed")
        writer.close()
        await writer.wait_closed()
        self.assertEqual(self.dispatcher.calls, [])

        reader, writer = await asyncio.open_unix_connection(socket_path)
        writer.write(
            json.dumps(_request("execute", "request-delayed")).encode() + b"\n"
        )
        await writer.drain()
        await asyncio.sleep(0.02)
        writer.write(b"{}\n")
        await writer.drain()
        writer.write_eof()
        response = json.loads((await reader.readline()).decode())
        self.assertEqual(response["code"], "operation-host-failed")
        writer.close()
        await writer.wait_closed()
        self.assertEqual(self.dispatcher.calls, [])

    async def test_timeout_and_hostile_failures_return_only_safe_error(self) -> None:
        await self.server.start()
        self.dispatcher.wait = asyncio.Event()
        response = await self._exchange(_request("execute", "request-timeout"))
        self.assertEqual(
            response,
            {
                "protocol": PRIME_OPERATION_HOST_PROTOCOL,
                "id": "request-timeout",
                "type": "error",
                "code": "operation-host-failed",
            },
        )

        self.dispatcher.wait = None
        self.dispatcher.error = RuntimeError(
            f"SENTINEL-TOKEN={TOKEN}; SENTINEL-PATH={self.private_root}; SENTINEL-BODY"
        )
        response = await self._exchange(_request("execute", "request-error"))
        rendered = json.dumps(response)
        self.assertEqual((response or {}).get("code"), "operation-host-failed")
        for sentinel in (TOKEN, str(self.private_root), "SENTINEL-BODY"):
            self.assertNotIn(sentinel, rendered)

    async def test_hostile_receipt_identity_is_rejected(self) -> None:
        hostile = dict(_receipt(_transaction()).to_mapping())
        hostile["authority_id"] = "authority-hostile"
        self.dispatcher.receipt_override = OperationReceipt.from_mapping(hostile)
        await self.server.start()
        self.assertEqual(
            (await self._exchange(_request("execute")) or {}).get("code"),
            "operation-host-failed",
        )

    async def test_close_cancels_and_drains_active_handlers(self) -> None:
        self.dispatcher.wait = asyncio.Event()
        server = PrimeOperationHostServer(
            dispatcher=self.dispatcher,
            private_root=self.private_root,
            token=TOKEN,
            request_timeout=10,
        )
        await server.start()
        reader, writer = await asyncio.open_unix_connection(
            str(server.descriptor["socketPath"])
        )
        writer.write(json.dumps(_request("execute")).encode() + b"\n")
        await writer.drain()
        writer.write_eof()
        for _ in range(20):
            if self.dispatcher.calls:
                break
            await asyncio.sleep(0)
        await server.close()
        self.assertEqual(await reader.read(), b"")
        writer.close()
        await writer.wait_closed()

    async def test_preexisting_endpoint_is_rejected_without_unlinking_it(self) -> None:
        socket_path = self.private_root / "prime-operation.sock"
        socket_path.write_text("SENTINEL", encoding="utf-8")
        with self.assertRaisesRegex(
            PrimeOperationHostError, "^Prime operation host failed$"
        ):
            await self.server.start()
        self.assertEqual(socket_path.read_text(encoding="utf-8"), "SENTINEL")
        await self.server.close()
        self.assertTrue(socket_path.exists())

    async def test_symlinked_private_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as target_name:
            link = self.private_root / "linked"
            os.symlink(target_name, link)
            server = PrimeOperationHostServer(
                dispatcher=self.dispatcher,
                private_root=link,
                token=TOKEN,
            )
            with self.assertRaisesRegex(
                PrimeOperationHostError, "^Prime operation host failed$"
            ):
                await server.start()
            await server.close()
            self.assertFalse((Path(target_name) / "prime-operation.sock").exists())

    async def test_symlinked_private_root_parent_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as target_name:
            target = Path(target_name).resolve()
            child = target / "child"
            child.mkdir()
            link = self.private_root / "linked-parent"
            os.symlink(target, link)
            server = PrimeOperationHostServer(
                dispatcher=self.dispatcher,
                private_root=link / "child",
                token=TOKEN,
            )
            with self.assertRaisesRegex(
                PrimeOperationHostError, "^Prime operation host failed$"
            ):
                await server.start()
            await server.close()
            self.assertFalse((child / "prime-operation.sock").exists())

    async def test_dispatcher_is_snapshotted_and_validated_at_construction(
        self,
    ) -> None:
        class MutableDispatcher(RecordingDispatcher):
            pass

        dispatcher = MutableDispatcher()
        server = PrimeOperationHostServer(
            dispatcher=dispatcher,
            private_root=self.private_root,
            token=TOKEN,
        )
        dispatcher.session_id = "session-hostile"
        dispatcher.execute = dispatcher.reconcile  # type: ignore[method-assign]
        await server.start()
        response = await self._exchange_for(server, _request("execute"))
        self.assertEqual((response or {}).get("type"), "operation.receipt")
        self.assertEqual(dispatcher.calls[0][0], "execute")
        await server.close()

        for hostile in (object(), ExplodingDispatcher()):
            with self.subTest(hostile=type(hostile).__name__):
                with self.assertRaisesRegex(
                    PrimeOperationHostError, "^Prime operation host failed$"
                ):
                    PrimeOperationHostServer(
                        dispatcher=cast(OperationDispatcher, hostile),
                        private_root=self.private_root,
                        token=TOKEN,
                    )

    async def _exchange_for(
        self, server: PrimeOperationHostServer, request: dict[str, object]
    ) -> dict[str, object] | None:
        reader, writer = await asyncio.open_unix_connection(
            str(server.descriptor["socketPath"])
        )
        writer.write(json.dumps(request).encode() + b"\n")
        await writer.drain()
        writer.write_eof()
        response = await reader.readline()
        writer.close()
        await writer.wait_closed()
        return json.loads(response) if response else None


class ExplodingDispatcher:
    @property
    def session_id(self) -> str:
        raise RuntimeError(f"SENTINEL-{TOKEN}")


class RecordingCallback:
    def __init__(self, audit: list[str], *, fail_start: bool = False) -> None:
        self.audit = audit
        self.fail_start = fail_start
        self.start_calls = 0
        self.close_calls = 0
        self.descriptor = {"socketPath": "/private/SENTINEL.sock", "token": TOKEN}

    async def start(self) -> None:
        self.start_calls += 1
        self.audit.append("callback.start")
        if self.fail_start:
            raise RuntimeError("SENTINEL_CALLBACK_START")

    async def close(self) -> None:
        self.close_calls += 1
        self.audit.append("callback.close")


class RecordingProcess:
    def __init__(
        self,
        audit: list[str],
        *,
        fail_request: bool = False,
        request_gate: asyncio.Event | None = None,
    ) -> None:
        self.audit = audit
        self.fail_request = fail_request
        self.request_gate = request_gate
        self.request_calls = 0
        self.close_calls = 0
        self.pid: int | None = None

    async def request(self, envelope: Mapping[str, object]) -> Mapping[str, object]:
        del envelope
        self.request_calls += 1
        self.audit.append("process.request")
        if self.fail_request:
            raise RuntimeError("SENTINEL_PROCESS_START")
        self.pid = 4242
        if self.request_gate is not None:
            await self.request_gate.wait()
        return {"ok": True}

    def events(self, envelope: Mapping[str, object]):
        del envelope

        async def iterator():
            self.audit.append("process.events")
            yield {"event": "ok"}

        return iterator()

    async def close(self) -> None:
        self.close_calls += 1
        self.audit.append("process.close")


class NoPidProcess(RecordingProcess):
    pid = None


class ExplodingCallback(RecordingCallback):
    async def close(self) -> None:
        self.audit.append("callback.close")
        raise RuntimeError("SENTINEL_CALLBACK_CLOSE")


class TestPrimeManagedOperationTransport(unittest.IsolatedAsyncioTestCase):
    async def test_starts_callback_once_before_event_iteration_and_request(
        self,
    ) -> None:
        audit: list[str] = []
        callback = RecordingCallback(audit)
        process = RecordingProcess(audit)
        transport = PrimeManagedOperationTransport(
            process=process,
            callback=callback,
        )

        events = [event async for event in transport.events({"id": "event-1"})]
        self.assertEqual(await transport.request({"id": "request-1"}), {"ok": True})

        self.assertEqual(events, [{"event": "ok"}])
        self.assertEqual(callback.start_calls, 1)
        self.assertEqual(
            audit,
            ["callback.start", "process.events", "process.request"],
        )
        await transport.close()

    async def test_concurrent_first_requests_start_callback_once(self) -> None:
        audit: list[str] = []
        callback = RecordingCallback(audit)
        gate = asyncio.Event()
        process = RecordingProcess(audit, request_gate=gate)
        transport = PrimeManagedOperationTransport(process=process, callback=callback)

        first = asyncio.create_task(transport.request({"id": "request-1"}))
        second = asyncio.create_task(transport.request({"id": "request-2"}))
        for _ in range(20):
            if process.request_calls == 2:
                break
            await asyncio.sleep(0)
        gate.set()
        self.assertEqual(
            await asyncio.gather(first, second), [{"ok": True}, {"ok": True}]
        )
        self.assertEqual(callback.start_calls, 1)
        await transport.close()

    async def test_no_call_does_not_start_callback_or_create_endpoint(self) -> None:
        audit: list[str] = []
        callback = RecordingCallback(audit)
        process = RecordingProcess(audit)
        transport = PrimeManagedOperationTransport(process=process, callback=callback)

        await transport.close()

        self.assertEqual(callback.start_calls, 0)
        self.assertEqual(process.request_calls, 0)
        self.assertEqual(audit, ["process.close", "callback.close"])

    async def test_callback_start_failure_never_calls_process(self) -> None:
        audit: list[str] = []
        callback = RecordingCallback(audit, fail_start=True)
        process = RecordingProcess(audit)
        transport = PrimeManagedOperationTransport(process=process, callback=callback)

        with self.assertRaises(PrimeSidecarProcessError) as raised:
            await transport.request({"id": "request-1"})

        self.assertEqual(process.request_calls, 0)
        self.assertNotIn("SENTINEL", str(raised.exception))
        self.assertEqual(audit, ["callback.start"])

    async def test_first_process_start_failure_closes_callback_and_redacts_error(
        self,
    ) -> None:
        audit: list[str] = []
        callback = RecordingCallback(audit)
        process = RecordingProcess(audit, fail_request=True)
        transport = PrimeManagedOperationTransport(process=process, callback=callback)

        with self.assertRaises(PrimeSidecarProcessError) as raised:
            await transport.request({"id": "request-1"})

        self.assertEqual(audit, ["callback.start", "process.request", "callback.close"])
        self.assertNotIn("SENTINEL", repr(raised.exception))
        await transport.close()

    async def test_close_is_process_then_callback_and_idempotent(self) -> None:
        audit: list[str] = []
        callback = RecordingCallback(audit)
        process = RecordingProcess(audit)
        transport = PrimeManagedOperationTransport(process=process, callback=callback)

        await transport.request({"id": "request-1"})
        await transport.close()
        await transport.close()

        self.assertEqual(
            audit,
            [
                "callback.start",
                "process.request",
                "process.close",
                "callback.close",
            ],
        )
        self.assertEqual(process.close_calls, 1)
        self.assertEqual(callback.close_calls, 1)


if __name__ == "__main__":
    unittest.main()
