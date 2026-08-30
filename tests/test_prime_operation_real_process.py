from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
import unittest
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import IO, cast

from asterion.control.authority import AuthorityEnvelope, AuthorityLedger
from asterion.control.factory import ControlPlaneFactoryContext
from asterion.control.journal import FileCanonicalJournal, JournalRecord
from asterion.control.providers.prime.client import PrimeControlPlaneClient
from asterion.control.providers.prime.factory import build_prime_control_plane_client
from asterion.control.providers.prime.operation import PrimeOperationError
from asterion.control.providers.prime.process import (
    PrimeSidecarLaunchOptions,
    PrimeSidecarProcess,
)
from asterion.control.providers.prime.rlm import build_prime_rlm_control_host
from asterion.operation.manager import OperationManager
from asterion.operation.protocol import OperationReceipt, OperationTransaction
from tests.test_control_children import _child_envelope
from tests.test_operation_manager import Service, Store, _receipt
from tests.test_prime_control_factory import make_context, prepare_paths
from tests.test_control_host import SpyExecutor
from tests.test_prime_verified_loop import (
    _prime_plan,
    _start_fake_daemon,
    _stop_process,
    _write_prime_source,
)


class RealOperationResolver:
    def __init__(self) -> None:
        self.calls = 0
        self.purposes: list[str] = []

    def resolve(self, descriptor, **kwargs):
        del descriptor, kwargs
        self.calls += 1
        self.purposes.append("operation.auth")
        return b'{"action":"read","private":"SENTINEL_PRIVATE_BODY"}'


class RealOperationService(Service):
    def __init__(self) -> None:
        super().__init__()
        self.receipts: list[OperationReceipt] = []
        self.cancel_calls: list[str] = []

    async def execute(self, transaction, typed_request):
        self.execute_calls.append(transaction.operation_id)
        if typed_request != {
            "action": "read",
            "private": "SENTINEL_PRIVATE_BODY",
        }:
            raise AssertionError(
                "operator service received an unexpected private request"
            )
        receipt = _receipt(transaction)
        self.receipts.append(receipt)
        return receipt

    async def cancel(self, transaction):
        self.cancel_calls.append(transaction.operation_id)
        receipt = _receipt(transaction, "cancelled")
        self.receipts.append(receipt)
        return receipt

    async def reconcile(self, transaction, typed_request, context):
        self.reconcile_calls.append(context.operation_id)
        if typed_request != {
            "action": "read",
            "private": "SENTINEL_PRIVATE_BODY",
        }:
            raise AssertionError(
                "operator service received an unexpected private request"
            )
        receipt = _receipt(transaction)
        self.receipts.append(receipt)
        return receipt


class FailingOperationDispatcher:
    session_id = "session-1"
    generation = 1
    authority_id = "authority-1"
    authority_revision = 1

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, transaction: OperationTransaction) -> OperationReceipt:
        del transaction
        self.calls += 1
        raise RuntimeError("SENTINEL_CALLBACK_FAILURE")

    async def cancel(
        self, operation_id: str, *, authority_revision: int
    ) -> OperationReceipt:
        del operation_id, authority_revision
        self.calls += 1
        raise RuntimeError("SENTINEL_CALLBACK_FAILURE")

    async def reconcile(self, transaction: OperationTransaction) -> OperationReceipt:
        del transaction
        self.calls += 1
        raise RuntimeError("SENTINEL_CALLBACK_FAILURE")


class RecordingPrimeSidecarProcess(PrimeSidecarProcess):
    """Capture the exact body-free JSON envelopes sent to the real sidecar."""

    def __init__(self, options: PrimeSidecarLaunchOptions) -> None:
        super().__init__(options)
        self.recorded_frames: list[str] = []

    async def request(self, envelope: Mapping[str, object]) -> Mapping[str, object]:
        self.recorded_frames.append(
            json.dumps(envelope, sort_keys=True, separators=(",", ":"))
        )
        return await super().request(envelope)


def _bind_operation_journal(
    journal: FileCanonicalJournal, authority: AuthorityEnvelope
) -> None:
    system = journal.append(
        0,
        JournalRecord.system_bound(system_id="research.system", system_version="1.0.0"),
    )
    journal.append(
        system.position,
        JournalRecord.authority_bound(
            authority_id=authority.authority_id,
            authority_revision=authority.revision,
        ),
    )


def _operation_authority() -> AuthorityEnvelope:
    base = _child_envelope()
    return AuthorityEnvelope(
        authority_id=base.authority_id,
        revision=base.revision,
        allowed_portfolio=base.allowed_portfolio,
        allowed_operations=tuple(sorted((*base.allowed_operations, "operation.auth"))),
        budget_limit=base.budget_limit,
        expires_at_ms=base.expires_at_ms,
        max_action_deadline_ms=base.max_action_deadline_ms,
        max_recursion_depth=base.max_recursion_depth,
        max_concurrent_children=base.max_concurrent_children,
        execution_domain=base.execution_domain,
        host_service_grants=tuple(
            sorted((*base.host_service_grants, "operation.auth"))
        ),
        cancelled=base.cancelled,
    )


def _real_transaction(operation_id: str = "operation-1") -> OperationTransaction:
    body = b'{"action":"read","private":"SENTINEL_PRIVATE_BODY"}'
    return OperationTransaction.from_mapping(
        {
            "protocol": "asterion.operation/v1",
            "operation_id": operation_id,
            "request": {
                "protocol": "asterion.operation/v1",
                "request_kind": "operation.auth-request",
                "request_ref": f"request-{operation_id}",
                "request_sha256": hashlib.sha256(body).hexdigest(),
                "media_type": "application/json",
                "byte_count": len(body),
                "purpose": "operation.auth",
                "client_id": "client-1",
                "session_id": "session-1",
                "generation": 1,
                "authority_revision": 1,
            },
            "session_id": "session-1",
            "client_id": "client-1",
            "generation": 1,
            "authority_revision": 1,
            "authority_id": "authority-1",
            "idempotency_key": f"key-{operation_id}",
            "feature_id": "operation.auth",
            "requested_at": "2026-08-10T15:00:00Z",
        }
    )


def _context_with_dispatcher(
    root: Path,
    *,
    daemon_socket: Path,
    authority: AuthorityEnvelope,
    dispatcher: object,
) -> ControlPlaneFactoryContext:
    package_root = (
        Path(__file__).resolve().parents[1] / "packages/typescript/prime-gateway"
    )
    base = make_context(
        root,
        authority=authority,
        node_executable=str(Path(shutil.which("node") or "node")),
        sidecar_entry=str(package_root / "dist/src/main.js"),
        prime_socket_path=str(daemon_socket),
        artifact_lock_path=str(root / "artifact-lock.json"),
        expected_runtime_build_id="fake-build-1",
    )
    services = dict(base.host_services)
    services["operation-dispatcher"] = dispatcher
    return ControlPlaneFactoryContext(
        system_id=base.system_id,
        system_version=base.system_version,
        control_plane_id=base.control_plane_id,
        control_plane_version=base.control_plane_version,
        private_root=base.private_root,
        options=base.options,
        authority=base.authority,
        host_services=services,
    )


class TestPrimeOperationRealProcess(unittest.IsolatedAsyncioTestCase):
    def _assert_zero_prime_effects(self, observations_path: Path) -> None:
        observations = json.loads(observations_path.read_text())
        self.assertEqual(observations["modelProviderOperations"], 0)
        self.assertEqual(observations["applicationOperations"], 0)
        self.assertEqual(observations["skillOperations"], [])
        self.assertEqual(observations["commandCounts"], {})

    async def _build_client(
        self,
        root: Path,
        daemon_socket: Path,
        dispatcher: object,
    ) -> tuple[
        PrimeControlPlaneClient,
        list[RecordingPrimeSidecarProcess],
        Path,
        IO[bytes],
        ControlPlaneFactoryContext,
    ]:
        context = _context_with_dispatcher(
            root,
            daemon_socket=daemon_socket,
            authority=_operation_authority(),
            dispatcher=dispatcher,
        )
        processes: list[RecordingPrimeSidecarProcess] = []
        stderr_sink = cast(IO[bytes], tempfile.TemporaryFile(mode="w+b"))

        def process_factory(options: PrimeSidecarLaunchOptions) -> PrimeSidecarProcess:
            process = RecordingPrimeSidecarProcess(
                replace(options, private_stderr_sink=stderr_sink)
            )
            processes.append(process)
            return process

        client = cast(
            PrimeControlPlaneClient,
            build_prime_control_plane_client(
                context,
                process_factory=process_factory,
            ),
        )
        descriptor = cast(
            Mapping[str, object],
            processes[0]._options.private_descriptor,  # type: ignore[attr-defined]
        )
        operation_host = cast(Mapping[str, str], descriptor["operationHost"])
        return (
            client,
            processes,
            Path(operation_host["socketPath"]),
            stderr_sink,
            context,
        )

    async def test_real_prime_process_round_trip_reaches_one_python_manager_without_body(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="asterion-prime-operation-", dir="/tmp"
        ) as directory:
            root = Path(directory)
            prepare_paths(root)
            for name in ("gateway", "workspace", "agent", "sessions", "prime-source"):
                (root / name).chmod(0o700)
            lock = _write_prime_source(root / "prime-source")
            (root / "artifact-lock.json").write_text(json.dumps(lock))
            daemon, daemon_socket, observations_path = await _start_fake_daemon(
                root, "embedded"
            )
            journal = FileCanonicalJournal.open(root / "operation-journal", "session-1")
            authority = _operation_authority()
            _bind_operation_journal(journal, authority)
            resolver = RealOperationResolver()
            store = Store()
            service = RealOperationService()
            manager = OperationManager(
                authority=AuthorityLedger(authority),
                journal=journal,
                resolver=resolver,
                private_store=store,
                services={"operation.auth": service},
                now_ms=lambda: 1_000,
                session_id="session-1",
                generation=1,
            )
            (
                client,
                processes,
                callback_socket,
                stderr_sink,
                factory_context,
            ) = await self._build_client(root, daemon_socket, manager)
            (root / "applications").mkdir()
            host = build_prime_rlm_control_host(
                session_id="session-1",
                generation=1,
                plan=_prime_plan(root),
                authority=AuthorityLedger(authority),
                journal=journal,
                client=client,
                action_executor=SpyExecutor(),
                clock_ms=lambda: 1_000,
                operation_manager=manager,
            )
            transaction = _real_transaction()
            try:
                self.assertIs(host._operation_manager, manager)
                self.assertIs(
                    factory_context.host_services["operation-dispatcher"], manager
                )
                self.assertFalse(callback_socket.exists())
                receipt = await asyncio.wait_for(
                    client.operation_client.execute(transaction), timeout=10
                )
                self.assertTrue(callback_socket.exists())
                self.assertEqual(receipt, service.receipts[0])
                self.assertEqual(
                    {
                        field: getattr(receipt, field)
                        for field in (
                            "operation_id",
                            "request_ref",
                            "request_sha256",
                            "purpose",
                            "session_id",
                            "client_id",
                            "generation",
                            "authority_revision",
                            "authority_id",
                            "idempotency_key",
                            "feature_id",
                        )
                    },
                    {
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
                    },
                )
                self.assertEqual(resolver.calls, 1)
                self.assertEqual(service.execute_calls, ["operation-1"])
                self.assertTrue(
                    all(value == 0 for value in receipt.effect_counts.values())
                )
                frames = [json.loads(frame) for frame in processes[0].recorded_frames]
                self.assertEqual(len(frames), 1)
                self.assertEqual(frames[0]["type"], "operation.execute")
                self.assertEqual(frames[0]["private"], {})
                self.assertNotIn("SENTINEL_PRIVATE_BODY", json.dumps(frames))
                self.assertNotIn("SENTINEL_PRIVATE_BODY", repr(processes[0]._options))  # type: ignore[attr-defined]
            finally:
                await host.close()
                await _stop_process(daemon)
                journal.close()
                stderr_sink.close()
            self.assertFalse(callback_socket.exists())
            self.assertIsNotNone(processes[0].returncode)
            self._assert_zero_prime_effects(observations_path)

    async def test_uncertain_process_round_trip_reconciles_and_cancels_without_retry(
        self,
    ) -> None:
        for recovery in ("reconcile", "cancel"):
            with (
                self.subTest(recovery=recovery),
                tempfile.TemporaryDirectory(
                    prefix="asterion-prime-operation-", dir="/tmp"
                ) as directory,
            ):
                root = Path(directory)
                prepare_paths(root)
                for name in (
                    "gateway",
                    "workspace",
                    "agent",
                    "sessions",
                    "prime-source",
                ):
                    (root / name).chmod(0o700)
                (root / "artifact-lock.json").write_text(
                    json.dumps(_write_prime_source(root / "prime-source"))
                )
                daemon, daemon_socket, observations_path = await _start_fake_daemon(
                    root, "embedded"
                )
                authority = _operation_authority()
                journal = FileCanonicalJournal.open(
                    root / "operation-journal", "session-1"
                )
                _bind_operation_journal(journal, authority)
                resolver = RealOperationResolver()
                store = Store()
                service = RealOperationService()
                manager = OperationManager(
                    authority=AuthorityLedger(authority),
                    journal=journal,
                    resolver=resolver,
                    private_store=store,
                    services={"operation.auth": service},
                    now_ms=lambda: 1_000,
                    session_id="session-1",
                    generation=1,
                )
                manager.fail_after = "operation.dispatch.started"
                (
                    client,
                    processes,
                    callback_socket,
                    stderr_sink,
                    _,
                ) = await self._build_client(root, daemon_socket, manager)
                try:
                    uncertain = await asyncio.wait_for(
                        client.operation_client.execute(_real_transaction()), timeout=10
                    )
                    self.assertEqual(uncertain.status, "uncertain")
                    self.assertEqual(uncertain.operation_id, "operation-1")
                    self.assertEqual(resolver.calls, 1)
                    self.assertEqual(service.execute_calls, [])
                    self.assertEqual(service.reconcile_calls, [])
                    self.assertEqual(service.cancel_calls, [])
                    self.assertTrue(
                        all(value == 0 for value in uncertain.effect_counts.values())
                    )
                    manager.fail_after = None
                    settled = (
                        await client.operation_client.reconcile(_real_transaction())
                        if recovery == "reconcile"
                        else await client.operation_client.cancel(
                            "operation-1", authority_revision=1
                        )
                    )
                    expected_status = (
                        "succeeded" if recovery == "reconcile" else "cancelled"
                    )
                    self.assertEqual(settled.status, expected_status)
                    self.assertEqual(settled.operation_id, "operation-1")
                    self.assertEqual(resolver.calls, 1)
                    self.assertEqual(service.execute_calls, [])
                    self.assertEqual(
                        service.reconcile_calls,
                        ["operation-1"] if recovery == "reconcile" else [],
                    )
                    self.assertEqual(
                        service.cancel_calls,
                        ["operation-1"] if recovery == "cancel" else [],
                    )
                    self.assertTrue(
                        all(value == 0 for value in settled.effect_counts.values())
                    )
                    frames = [
                        json.loads(frame) for frame in processes[0].recorded_frames
                    ]
                    self.assertEqual(
                        [frame["type"] for frame in frames],
                        ["operation.execute", f"operation.{recovery}"],
                    )
                    self.assertTrue(all(frame["private"] == {} for frame in frames))
                    self.assertNotIn("SENTINEL_PRIVATE_BODY", json.dumps(frames))
                finally:
                    await client.close()
                    await _stop_process(daemon)
                    journal.close()
                    stderr_sink.close()
                self.assertFalse(callback_socket.exists())
                self._assert_zero_prime_effects(observations_path)

    async def test_real_callback_failure_is_safe_and_not_retried(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="asterion-prime-operation-", dir="/tmp"
        ) as directory:
            root = Path(directory)
            prepare_paths(root)
            for name in ("gateway", "workspace", "agent", "sessions", "prime-source"):
                (root / name).chmod(0o700)
            (root / "artifact-lock.json").write_text(
                json.dumps(_write_prime_source(root / "prime-source"))
            )
            daemon, daemon_socket, observations_path = await _start_fake_daemon(
                root, "embedded"
            )
            dispatcher = FailingOperationDispatcher()
            (
                client,
                processes,
                callback_socket,
                stderr_sink,
                _,
            ) = await self._build_client(root, daemon_socket, dispatcher)
            try:
                with self.assertRaisesRegex(
                    PrimeOperationError, "^Prime operation failed$"
                ):
                    await asyncio.wait_for(
                        client.operation_client.execute(_real_transaction()), timeout=10
                    )
            finally:
                await client.close()
                await _stop_process(daemon)
                stderr_sink.close()
            self.assertEqual(dispatcher.calls, 1)
            frames = [json.loads(frame) for frame in processes[0].recorded_frames]
            self.assertEqual([frame["type"] for frame in frames], ["operation.execute"])
            self.assertEqual(frames[0]["private"], {})
            self.assertNotIn("SENTINEL_PRIVATE_BODY", json.dumps(frames))
            self.assertFalse(callback_socket.exists())
            self._assert_zero_prime_effects(observations_path)

    async def test_missing_callback_endpoint_is_safe_and_not_retried(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="asterion-prime-operation-", dir="/tmp"
        ) as directory:
            root = Path(directory)
            prepare_paths(root)
            for name in ("gateway", "workspace", "agent", "sessions", "prime-source"):
                (root / name).chmod(0o700)
            (root / "artifact-lock.json").write_text(
                json.dumps(_write_prime_source(root / "prime-source"))
            )
            daemon, daemon_socket, observations_path = await _start_fake_daemon(
                root, "embedded"
            )
            dispatcher = FailingOperationDispatcher()
            (
                client,
                processes,
                callback_socket,
                stderr_sink,
                _,
            ) = await self._build_client(root, daemon_socket, dispatcher)
            try:
                await asyncio.wait_for(client.rlm_lifecycle(), timeout=10)
                self.assertTrue(callback_socket.exists())
                self.assertIsNotNone(processes[0].pid)
                callback = object.__getattribute__(
                    object.__getattribute__(client, "_process"),
                    "_callback",
                )
                await callback.close()
                self.assertFalse(callback_socket.exists())
                processes[0].recorded_frames.clear()

                with self.assertRaisesRegex(
                    PrimeOperationError, "^Prime operation failed$"
                ) as raised:
                    await asyncio.wait_for(
                        client.operation_client.execute(_real_transaction()), timeout=10
                    )
                self.assertEqual(str(raised.exception), "Prime operation failed")
            finally:
                await client.close()
                await _stop_process(daemon)
                stderr_sink.close()

            self.assertEqual(dispatcher.calls, 0)
            frames = [json.loads(frame) for frame in processes[0].recorded_frames]
            self.assertEqual([frame["type"] for frame in frames], ["operation.execute"])
            self.assertEqual(frames[0]["private"], {})
            public_failure = str(raised.exception)
            self.assertNotIn("SENTINEL_PRIVATE_BODY", json.dumps(frames))
            self.assertNotIn("SENTINEL_CALLBACK_FAILURE", public_failure)
            self.assertNotIn(str(callback_socket), public_failure)
            self.assertFalse(callback_socket.exists())
            self.assertIsNotNone(processes[0].returncode)
            self._assert_zero_prime_effects(observations_path)


if __name__ == "__main__":
    unittest.main()
