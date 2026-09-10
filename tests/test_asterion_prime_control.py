from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import socket
import tempfile
import unittest
from typing import Any, cast
from unittest.mock import patch

from asterion.agents.prime.backend import PrimeSessionBackend
from asterion.agents.prime.compaction_budget import ModelPrice
from asterion.agents.prime.context import PrimeContextWitnessSession
from asterion.agents.prime.session import AsterionPrimeLimits
from asterion.agents.prime.state import PrimeBackendIdentity
from asterion.agents.prime.store import FilePrimeSessionStore, private_root_identity
from asterion.control.authority import (
    AuthorityEnvelope,
    BudgetLimit,
    PortfolioGrant,
    RemainingBudget,
)
from asterion.control.factory import (
    ControlPlaneFactoryContext,
    ControlPlaneFactoryError,
    ControlPlaneFactoryRegistry,
    bind_selected_session_context_client,
)
from asterion.control.host import ControlCommand, EventCursor
from asterion.control.protocol import CONTROL_COMMAND_TYPES, CONTROL_EVENT_TYPES
from asterion.control.providers.asterion_prime import (
    ASTERION_PRIME_CONTROL_PLANE_ID,
    ASTERION_PRIME_CONTROL_PLANE_VERSION,
    ASTERION_PRIME_SESSION_BACKEND_SERVICE,
    AsterionPrimeControlError,
    asterion_prime_control_plane_binding,
    build_asterion_prime_control_plane_client,
)
from asterion.control.providers.asterion_prime import factory as provider_factory
from asterion.control.session_context import (
    SESSION_CONTEXT_CAPABILITY,
    SessionContextCommand,
    SessionContextReceipt,
)
from asterion.runtimes.pi_extensions import PiExtensionBinding
from asterion.runtimes.pi_rpc import PiRpcConfig, PiRpcSession
from tests.test_asterion_prime_backend import FakeReusablePi, FakeToolExecutor
from tests.test_asterion_prime_context import LAUNCH


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def authority() -> AuthorityEnvelope:
    return AuthorityEnvelope(
        authority_id="authority-1",
        revision=1,
        allowed_portfolio=(
            PortfolioGrant(
                provider_id="prime-applications",
                application_id="prime.ipython-coding",
                version="1.0.0",
                runtime_id="asterion.prime",
            ),
        ),
        allowed_operations=(
            "session.compact",
            "session.continuation.resume",
            "session.describe",
        ),
        budget_limit=BudgetLimit(64_000, 64_000, 0, 64_000, 500_000),
        expires_at_ms=601_000,
        max_action_deadline_ms=600_000,
        max_recursion_depth=0,
        max_concurrent_children=0,
        execution_domain="restricted",
        host_service_grants=(ASTERION_PRIME_SESSION_BACKEND_SERVICE,),
    )


def remaining_budget() -> RemainingBudget:
    return RemainingBudget(64_000, 64_000, 0, 64_000, 500_000, 600_000)


class PrimeBackendHarness:
    def __init__(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        extension = self.root / "extension.mjs"
        extension.write_text("export default function extension() {}\n")
        self.binding = PiExtensionBinding(
            "prime.ipython", extension, ("prime.tool.ipython",), (), {}
        )
        self.lease = self.binding.preflight()
        self.limits = AsterionPrimeLimits(8, 4, 600_000)
        config = PiRpcConfig(
            command=("pi", "--mode", "rpc", *self.lease.command_args()),
            cwd=self.root,
            environment=dict(self.lease.environment),
            inherited_fds=self.lease.inherited_fds,
            deadline_seconds=600,
        )
        self.rpc = FakeReusablePi(config)
        host, self.peer = socket.socketpair()
        self.peer.setblocking(False)
        cast(Any, self.rpc).peer = self.peer
        self.witness = PrimeContextWitnessSession(
            host,
            launch_nonce=LAUNCH,
            timeout_seconds=0.2,
            mark_uncertain=lambda: None,
        )
        self.private = self.root / "private"
        self.private.mkdir(mode=0o700)
        self.identity = PrimeBackendIdentity(
            "session-1",
            1,
            "prime-applications",
            "prime.ipython-coding",
            "1.0.0",
            "asterion.prime",
            _digest(config.command),
            self.binding.binding_fingerprint,
            "a" * 64,
            "continuation-1",
            private_root_identity(self.private),
            _digest(
                {
                    **asdict(self.limits),
                    "aggregate_tokens": 64_000,
                    "cost_micros": 500_000,
                }
            ),
        )
        self.store = FilePrimeSessionStore(self.private, self.identity)
        self.worker = FakeToolExecutor()
        self.backend = PrimeSessionBackend(
            identity=self.identity,
            store=self.store,
            rpc_session=cast(PiRpcSession, self.rpc),
            extension_binding=self.binding,
            extension_lease=self.lease,
            approved_command=config.command,
            limits=self.limits,
            aggregate_tokens=64_000,
            cost_micros=500_000,
            model_price=ModelPrice(1_000_000, 1_000_000),
            witness=self.witness,
            tool_executor=self.worker,
            authority_id="authority-1",
        )
        self.backend.sync_authority_snapshot(remaining_budget(), authority_revision=1)

    def context(self, **changes: object) -> ControlPlaneFactoryContext:
        values: dict[str, object] = {
            "system_id": "prime.ipython-coding",
            "system_version": "1.0.0",
            "control_plane_id": ASTERION_PRIME_CONTROL_PLANE_ID,
            "control_plane_version": ASTERION_PRIME_CONTROL_PLANE_VERSION,
            "private_root": self.private,
            "options": {"generation": "1", "session_id": "session-1"},
            "authority": authority(),
            "host_services": {
                ASTERION_PRIME_SESSION_BACKEND_SERVICE: self.backend,
            },
        }
        values.update(changes)
        return ControlPlaneFactoryContext(**values)  # type: ignore[arg-type]

    async def close(self) -> None:
        await self.backend.close()
        self.peer.close()
        self.temp.cleanup()


def create_command(command_id: str = "create-1") -> ControlCommand:
    return ControlCommand(
        command_id=command_id,
        session_id="session-1",
        authority_revision=1,
        type="session.create",
        payload={
            "system_id": "prime.ipython-coding",
            "system_version": "1.0.0",
            "goal_id": "goal-1",
            "goal_ref": "goal-ref-1",
        },
    )


class TestAsterionPrimeControlFactory(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.fixture = PrimeBackendHarness()

    async def asyncTearDown(self) -> None:
        await self.fixture.close()

    def test_binding_is_exact_sorted_and_closed(self) -> None:
        binding = asterion_prime_control_plane_binding()

        self.assertEqual(binding.control_plane_id, "asterion.prime-control")
        self.assertEqual(binding.version, "1.0.0")
        self.assertEqual(binding.commands, tuple(sorted(CONTROL_COMMAND_TYPES)))
        self.assertEqual(binding.events, tuple(sorted(CONTROL_EVENT_TYPES)))
        self.assertEqual(
            binding.capabilities,
            (
                "checkpointing",
                "event-replay",
                "session-lifecycle",
                SESSION_CONTEXT_CAPABILITY,
            ),
        )
        self.assertEqual(
            binding.compatibility_ids,
            ("asterion.agent-control/v1", "asterion.session-context/v1"),
        )

    async def test_registry_selection_is_metadata_only_until_exact_factory_call(
        self,
    ) -> None:
        registry = ControlPlaneFactoryRegistry(
            (asterion_prime_control_plane_binding(),)
        )
        binding = registry.select("asterion.prime-control", "1.0.0")

        self.assertEqual(self.fixture.backend._attachment_generation, 0)
        client = binding.factory(self.fixture.context())
        self.assertEqual(self.fixture.backend._attachment_generation, 1)
        self.assertIs(bind_selected_session_context_client(client), client)
        await client.close()

    def test_factory_requires_exact_backend_session_generation_and_authority(
        self,
    ) -> None:
        cases = (
            {"host_services": {}},
            {"options": {"generation": "2", "session_id": "session-1"}},
            {"options": {"generation": "1", "session_id": "other-session"}},
            {"system_id": "prime.arc-agi-3-solving"},
            {"authority": replace(authority(), revision=2)},
            {
                "authority": replace(
                    authority(),
                    host_service_grants=("prime.private-trace",),
                )
            },
        )
        for changes in cases:
            with (
                self.subTest(changes=tuple(changes)),
                self.assertRaises(ControlPlaneFactoryError) as raised,
            ):
                build_asterion_prime_control_plane_client(
                    self.fixture.context(**changes)
                )
            self.assertEqual(
                str(raised.exception), "Asterion Prime control plane is unavailable"
            )

    def test_manifest_failure_is_redacted_and_does_not_attach(self) -> None:
        secret = "SENTINEL_PRIVATE_MANIFEST_PATH"
        with patch.object(
            provider_factory,
            "_packaged_manifest",
            side_effect=OSError(secret),
        ):
            with self.assertRaises(ControlPlaneFactoryError) as raised:
                build_asterion_prime_control_plane_client(self.fixture.context())

        self.assertEqual(self.fixture.backend._attachment_generation, 0)
        self.assertIsNone(raised.exception.__context__)
        self.assertIsNone(raised.exception.__cause__)
        self.assertNotIn(secret, repr(raised.exception))


class TestAsterionPrimeControlClient(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.fixture = PrimeBackendHarness()
        self.client = build_asterion_prime_control_plane_client(self.fixture.context())

    async def asyncTearDown(self) -> None:
        await self.client.close()
        await self.fixture.close()

    async def test_control_replay_validates_generation_and_closed_events(self) -> None:
        await self.client.send(create_command())
        events = [event async for event in self.client.events()]

        self.assertEqual([event.sequence for event in events], [1, 2])
        self.assertEqual(
            [event.type for event in events], ["session.created", "session.running"]
        )
        suffix = [event async for event in self.client.events(EventCursor(1, 1))]
        self.assertEqual(suffix, events[1:])
        for event in events:
            self.assertEqual(event.session_id, "session-1")
            self.assertEqual(event.generation, 1)
            self.assertEqual(type(event).from_mapping(event.to_mapping()), event)
        with self.assertRaises(AsterionPrimeControlError):
            [event async for event in self.client.events(EventCursor(2, 0))]

    async def test_client_pushes_every_authority_snapshot_without_debit(self) -> None:
        before = self.fixture.backend.usage
        position = self.fixture.store.position

        await self.client.sync_authority_snapshot(remaining_budget())
        await self.client.sync_authority_snapshot(remaining_budget())

        self.assertEqual(self.fixture.backend.snapshot().authority_revision, 1)
        self.assertEqual(self.fixture.backend.usage, before)
        self.assertEqual(self.fixture.store.position, position + 2)

    async def test_context_receipt_is_closed_correlated_and_unknown_count_rejected(
        self,
    ) -> None:
        await self.client.send(create_command())
        command = SessionContextCommand(
            "describe-1",
            "session-1",
            1,
            1,
            "describe-key-1",
            "session.describe",
            {},
        )

        receipt = await self.client.execute_session_context(command)

        self.assertIsInstance(receipt, SessionContextReceipt)
        self.assertEqual(receipt.command_id, command.command_id)
        self.assertEqual(receipt.session_id, command.session_id)
        self.assertEqual(receipt.generation, command.generation)
        self.assertEqual(receipt.operation, command.operation)
        self.assertEqual(receipt.status, "rejected")
        self.assertEqual(receipt.reason_code, "context-count-unavailable")
        self.assertEqual(
            SessionContextReceipt.from_mapping(receipt.to_mapping()), receipt
        )

    async def test_internal_errors_and_representations_are_redacted(self) -> None:
        secret = "SENTINEL_PRIVATE_PATH_AND_PROVIDER_PAYLOAD"
        attachment = self.client._attachment
        with patch.object(
            attachment,
            "accept_control",
            side_effect=RuntimeError(secret),
        ):
            with self.assertRaises(AsterionPrimeControlError) as raised:
                await self.client.send(create_command())
        rendered = repr((self.client, raised.exception))
        self.assertIsNone(raised.exception.__context__)
        self.assertIsNone(raised.exception.__cause__)
        self.assertNotIn(secret, rendered)
        self.assertNotIn(str(self.fixture.private), rendered)

    async def test_close_only_detaches_and_is_idempotent(self) -> None:
        await self.client.close()
        await self.client.close()

        self.assertEqual(self.fixture.rpc.closes, 0)
        self.assertIsNone(self.fixture.backend._cleanup)
        with self.assertRaises(AsterionPrimeControlError):
            await self.client.send(create_command())


if __name__ == "__main__":
    unittest.main()
