"""Public, generic client projection for host-owned operation receipts."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from asterion.client.private import ClientAccess, ClientPrivateValueService, PrivateValueDescriptor
from asterion.client.protocol import ClientEvent, CLIENT_EVENT_TYPES
from asterion.client.protocol import ClientIntent
from asterion.client.session import ClientSessionError, HostClientSessionEndpoint
from asterion.control.authority import AuthorityLedger
from asterion.control.journal import JournalCursor, JournalRecord, MemoryCanonicalJournal
from asterion.control.manager import ControlHost
from asterion.control.system import resolve_agent_system
from asterion.operation.manager import OperationManager
from asterion.operation.protocol import OperationReceipt
from tests.test_control_authority import _envelope
from tests.test_control_host import ScriptedClient, SpyExecutor
from tests.test_control_system import _control_factories, _manifest, _provider
from tests.test_operation_manager import Resolver, Service, Store


class _OperationPrivateBackend:
    def __init__(self) -> None:
        self.body = b'{"action":"read"}'
        self.read_calls = 0
        self.describe_calls = 0

    def describe(self, reference: str) -> PrivateValueDescriptor:
        self.describe_calls += 1
        if reference != "operation-request-1":
            raise KeyError(reference)
        return PrivateValueDescriptor(
            reference=reference, kind="operation.request", media_type="application/json",
            size=len(self.body), sha256=hashlib.sha256(self.body).hexdigest(),
        )

    def read(self, reference: str, *, max_bytes: int) -> bytes:
        self.read_calls += 1
        raise AssertionError("operation client metadata must not read private bytes")


def _operation_intent(
    *, intent_id: str = "intent-operation-1", command_name: str = "operation.auth",
    revision: int = 1, arguments_ref: str = "operation-request-1",
    authority_revision: int = 1,
) -> ClientIntent:
    return ClientIntent(
        protocol="asterion.agent-client/v1", intent_id=intent_id, client_id="client-1",
        session_id="session-1", authority_revision=authority_revision,
        type="command.invoke", payload={
            "arguments_ref": arguments_ref, "command_name": command_name,
            "command_revision": revision,
        },
    )


def _operation_endpoint(
    *, operation_describer: object | None = None, operation_cancellation_signal: object | None = None,
) -> tuple[HostClientSessionEndpoint, Service, _OperationPrivateBackend]:
    with tempfile.TemporaryDirectory() as directory:
        plan = resolve_agent_system(
            _manifest(), application_providers=(_provider(Path(directory)),),
            control_factories=_control_factories([]),
            host_capabilities=("clock.monotonic", "storage.private"),
        )
    journal = MemoryCanonicalJournal("session-1")
    system = journal.append(0, JournalRecord.system_bound(system_id=plan.system_id, system_version=plan.version))
    journal.append(system.position, JournalRecord.authority_bound(authority_id="authority-1", authority_revision=1))
    authority = _envelope(allowed_operations=("operation.auth",), host_service_grants=("operation.auth",))
    service = Service()
    manager = OperationManager(
        authority=AuthorityLedger(authority), journal=journal, resolver=Resolver(), private_store=Store(),
        services={"operation.auth": service}, now_ms=lambda: 1_000,
        session_id="session-1", generation=1,
    )
    host = ControlHost(
        session_id="session-1", generation=1, plan=plan,
        authority=AuthorityLedger(authority), journal=journal,
        client=ScriptedClient(plan.control_binding.manifest), action_executor=SpyExecutor(),
        clock_ms=lambda: 1_000, operation_manager=manager,
    )
    backend = _OperationPrivateBackend()
    private_values = ClientPrivateValueService(
        access=ClientAccess(client_id="client-1", session_id="session-1", authority_revision=1, purposes=("operation.auth",)),
        backend=backend, clock_ms=lambda: 1, authority_revision_source=lambda: host.authority_revision,
    )
    return HostClientSessionEndpoint(
        client_id="client-1", host=host, journal=journal, private_values=private_values,
        operation_describer=operation_describer,  # type: ignore[arg-type]
        operation_cancellation_signal=operation_cancellation_signal,
    ), service, backend


class TestClientOperationProtocol(unittest.TestCase):
    def test_operation_receipt_is_one_closed_public_event(self) -> None:
        self.assertIn("operation.receipted", CLIENT_EVENT_TYPES)
        event = ClientEvent(
            protocol="asterion.agent-client/v1",
            event_id="event-operation-1",
            session_id="session-1",
            generation=1,
            sequence=1,
            emitted_at="2026-08-10T15:00:00Z",
            type="operation.receipted",
            payload={
                "effect_counts": {
                    "credential_value_reads": 0,
                    "external_telemetry_deliveries": 0,
                    "network_operations": 0,
                    "os_process_restart_operations": 0,
                    "package_manager_operations": 0,
                    "provider_model_requests": 0,
                    "uploads": 0,
                },
                "feature_id": "operation.auth",
                "operation_id": "operation-1",
                "reason_code": "operation-succeeded",
                "receipt_ref": "receipt-public-1",
                "status": "succeeded",
            },
        )
        self.assertEqual(
            tuple(event.payload),
            (
                "effect_counts",
                "feature_id",
                "operation_id",
                "reason_code",
                "receipt_ref",
                "status",
            ),
        )


class TestClientOperationEndpoint(unittest.IsolatedAsyncioTestCase):
    async def _reconciled_operation_endpoint(
        self,
    ) -> tuple[HostClientSessionEndpoint, Service, list[ClientEvent]]:
        endpoint, service, _ = _operation_endpoint()
        service.fail_execute = True
        await endpoint.submit(_operation_intent())
        first = [event async for event in endpoint.events()]
        operation_id = first[0].payload["operation_id"]
        manager = endpoint._host._operation_manager  # type: ignore[attr-defined]
        self.assertIsNotNone(manager)
        service.fail_execute = False
        await endpoint._host.reconcile_operation(manager._transactions[operation_id])  # type: ignore[union-attr]
        await endpoint.pump()
        return endpoint, service, [event async for event in endpoint.events()]

    async def test_command_invoke_projects_one_generic_operation_receipt(self) -> None:
        endpoint, service, private_values = _operation_endpoint()
        await endpoint.submit(_operation_intent())
        events = [event async for event in endpoint.events()]
        self.assertEqual(events[-1].type, "operation.receipted")
        self.assertEqual(
            set(events[-1].payload),
            {"effect_counts", "feature_id", "operation_id", "reason_code", "receipt_ref", "status"},
        )
        self.assertNotIn("SENTINEL_SECRET", repr(events[-1]))
        self.assertEqual(service.execute_calls, [events[-1].payload["operation_id"]])
        self.assertEqual(private_values.read_calls, 0)

    async def test_unknown_stale_conflicting_or_duplicate_command_does_not_dispatch(self) -> None:
        endpoint, service, _ = _operation_endpoint()
        self.assertEqual(endpoint.command_registry.names, (
            "operation.auth", "operation.controlled-update-restart", "operation.doctor",
            "operation.model-selection", "operation.settings-keybindings", "operation.telemetry-usage",
        ))
        with self.assertRaises(ClientSessionError):
            endpoint.command_registry.invoke("operation.auth.hidden")
        for intent in (
            _operation_intent(command_name="operation.auth.hidden"),
            _operation_intent(revision=2),
            _operation_intent(authority_revision=2),
        ):
            with self.subTest(intent=intent.payload):
                with self.assertRaises(ClientSessionError):
                    await endpoint.submit(intent)
        await endpoint.submit(_operation_intent())
        with self.assertRaises(ClientSessionError):
            await endpoint.submit(_operation_intent(arguments_ref="operation-request-2"))
        await endpoint.submit(_operation_intent())
        self.assertEqual(len(service.execute_calls), 1)

    async def test_uncertain_receipt_projects_once_then_reconciles_monotonically(self) -> None:
        endpoint, service, events = await self._reconciled_operation_endpoint()
        operation_id = events[0].payload["operation_id"]
        self.assertEqual(
            [event.payload["status"] for event in events], ["uncertain", "succeeded"]
        )
        self.assertEqual(len(service.execute_calls), 1)
        self.assertEqual(service.reconcile_calls, [operation_id])
        position = endpoint._journal.position  # type: ignore[attr-defined]
        restarted = HostClientSessionEndpoint(
            client_id="client-1", host=endpoint._host,  # type: ignore[attr-defined]
            journal=endpoint._journal,  # type: ignore[attr-defined]
            private_values=endpoint.private_values,
        )
        recovered = [event async for event in restarted.events()]
        self.assertEqual(recovered, events)
        self.assertEqual(endpoint._journal.position, position)  # type: ignore[attr-defined]
        self.assertEqual(len(service.execute_calls), 1)

    async def test_restart_rejects_hostile_standalone_operation_receipts(self) -> None:
        async def assert_rejected(mutator) -> None:
            endpoint, _, events = await self._reconciled_operation_endpoint()
            mutator(endpoint, events)
            with self.assertRaises(ClientSessionError):
                HostClientSessionEndpoint(
                    client_id="client-1", host=endpoint._host,  # type: ignore[attr-defined]
                    journal=endpoint._journal,  # type: ignore[attr-defined]
                    private_values=endpoint.private_values,
                )

        def append_orphan(endpoint, events) -> None:
            terminal = events[-1]
            orphan = ClientEvent(
                protocol="asterion.agent-client/v1", event_id="operation-event-orphan",
                session_id="session-1", generation=1, sequence=3,
                emitted_at=terminal.emitted_at, type="operation.receipted",
                payload={
                    **dict(terminal.payload), "operation_id": "operation-orphan",
                    "receipt_ref": "receipt-orphan",
                },
            )
            endpoint._journal.append(  # type: ignore[attr-defined]
                endpoint._journal.position, JournalRecord.client_event_accepted(orphan)  # type: ignore[attr-defined]
            )

        def append_mismatched(endpoint, events) -> None:
            terminal = events[-1]
            mismatched = ClientEvent(
                protocol="asterion.agent-client/v1", event_id="operation-event-mismatch",
                session_id="session-1", generation=1, sequence=3,
                emitted_at=terminal.emitted_at, type="operation.receipted",
                payload={**dict(terminal.payload), "receipt_ref": "receipt-mismatch"},
            )
            endpoint._journal.append(  # type: ignore[attr-defined]
                endpoint._journal.position, JournalRecord.client_event_accepted(mismatched)  # type: ignore[attr-defined]
            )

        def append_terminal_regression(endpoint, events) -> None:
            uncertain_receipt = next(
                OperationReceipt.from_mapping(entry.record.payload["receipt"])
                for entry in endpoint._journal.replay(JournalCursor(0))  # type: ignore[attr-defined]
                if entry.record.kind == "operation.receipted"
                and entry.record.payload["receipt"]["status"] == "uncertain"
            )
            regression = OperationReceipt.from_mapping({
                **dict(uncertain_receipt.to_mapping()), "receipt_id": "receipt-regression",
                "receipt_ref": "receipt-regression",
            })
            endpoint._journal.append(  # type: ignore[attr-defined]
                endpoint._journal.position,
                JournalRecord(
                    "operation-receipt-regression", "operation.receipted",
                    {"receipt": regression.to_mapping()},
                ),  # type: ignore[attr-defined]
            )
            endpoint._journal.append(  # type: ignore[attr-defined]
                endpoint._journal.position,
                JournalRecord.client_event_accepted(endpoint._operation_event(regression)),  # type: ignore[attr-defined]
            )

        def append_conflicting_terminal(endpoint, events) -> None:
            terminal_receipt = next(
                OperationReceipt.from_mapping(entry.record.payload["receipt"])
                for entry in endpoint._journal.replay(JournalCursor(0))  # type: ignore[attr-defined]
                if entry.record.kind == "operation.receipted"
                and entry.record.payload["receipt"]["status"] == "succeeded"
            )
            conflicting = OperationReceipt.from_mapping({
                **dict(terminal_receipt.to_mapping()), "receipt_id": "receipt-conflict",
                "receipt_ref": "receipt-conflict", "status": "failed",
                "reason_code": "operation-failed",
            })
            endpoint._journal.append(  # type: ignore[attr-defined]
                endpoint._journal.position, JournalRecord.operation_receipted(conflicting)  # type: ignore[attr-defined]
            )
            endpoint._journal.append(  # type: ignore[attr-defined]
                endpoint._journal.position,
                JournalRecord.client_event_accepted(endpoint._operation_event(conflicting)),  # type: ignore[attr-defined]
            )

        for mutator in (
            append_orphan, append_mismatched, append_terminal_regression,
            append_conflicting_terminal,
        ):
            with self.subTest(mutator=mutator.__name__):
                await assert_rejected(mutator)

    async def test_cancelled_or_oversized_metadata_never_reads_or_dispatches(self) -> None:
        endpoint, service, private_values = _operation_endpoint()
        private_values.body = b"x" * 4_097
        with self.assertRaises(ClientSessionError):
            await endpoint.submit(_operation_intent())
        self.assertEqual((service.execute_calls, private_values.read_calls), ([], 0))

    async def test_hostile_metadata_or_late_cancellation_cannot_reach_dispatch(self) -> None:
        class HostileMetadata:
            @property
            def request_ref(self) -> str:
                raise AssertionError("metadata property must not be read")

        class HostileDescriber:
            def describe_operation_request(self, *args, **kwargs):
                del args, kwargs
                return HostileMetadata()

        endpoint, service, private_values = _operation_endpoint(
            operation_describer=HostileDescriber(),
        )
        with self.assertRaises(ClientSessionError):
            await endpoint.submit(_operation_intent())
        self.assertEqual((service.execute_calls, private_values.read_calls), ([], 0))

        class ChangingCancellation:
            def __init__(self) -> None:
                self.values = [False, True]

            @property
            def cancelled(self) -> bool:
                return self.values.pop(0)

        endpoint, service, private_values = _operation_endpoint(
            operation_cancellation_signal=ChangingCancellation(),
        )
        with self.assertRaises(ClientSessionError):
            await endpoint.submit(_operation_intent())
        self.assertEqual((service.execute_calls, private_values.read_calls), ([], 0))
