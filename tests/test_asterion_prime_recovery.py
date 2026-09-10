from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from asterion.agents.prime.backend import PrimePromptRequest
from asterion.applications.provider import (
    APPLICATION_PROVIDER_PROTOCOL,
    InstalledApplication,
    InstalledApplicationProvider,
    InstalledAssembly,
)
from asterion.assembly.protocol import AssemblyPlan
from asterion.capabilities.composition import CapabilityComposition
from asterion.control.authority import AuthorityLedger
from asterion.control.factory import ControlPlaneFactoryRegistry
from asterion.control.journal import FileCanonicalJournal, JournalCursor
from asterion.control.manager import ControlHost
from asterion.control.providers.asterion_prime import (
    asterion_prime_control_plane_binding,
    build_asterion_prime_control_plane_client,
)
from asterion.control.recovery import recover_control_host_state
from asterion.control.session_context import SessionContextCommand
from asterion.control.system import resolve_agent_system
from tests.test_asterion_prime_control import (
    PrimeBackendHarness,
    authority,
    create_command,
)
from tests.test_control_host import SpyExecutor


def _provider(root: Path) -> InstalledApplicationProvider:
    assembly_path = root / "assembly.json"
    assembly_path.write_text("{}")
    assembly = AssemblyPlan(
        application_id="prime.ipython-coding",
        version="1.0.0",
        runtime_id="asterion.prime",
        capability_package_refs=(),
        capability_refs=(),
        capability_manifests=(),
        composition=CapabilityComposition(
            capability_ids=(),
            provided_capabilities=(),
            emitted_events=(),
            produced_artifacts=(),
        ),
        runtime_capabilities=(),
        host_capabilities=(),
        host_events=(),
        host_artifacts=(),
    )
    application = InstalledApplication(
        application_id="prime.ipython-coding",
        version="1.0.0",
        assembly_paths=(assembly_path,),
        capability_packages=(),
        runtime_ids=("asterion.prime",),
        assemblies=(
            InstalledAssembly(
                runtime_id="asterion.prime",
                path=assembly_path,
                plan=assembly,
            ),
        ),
    )
    return InstalledApplicationProvider(
        protocol=APPLICATION_PROVIDER_PROTOCOL,
        provider_id="prime-applications",
        resource_root=root,
        applications=(application,),
    )


def _plan(root: Path):
    binding = asterion_prime_control_plane_binding()
    manifest = {
        "protocol": "asterion.agent-system/v1",
        "system_id": "prime.ipython-coding",
        "version": "1.0.0",
        "control_plane": {
            "control_plane_id": binding.control_plane_id,
            "version": binding.version,
        },
        "applications": [
            {
                "provider_id": "prime-applications",
                "application_id": "prime.ipython-coding",
                "version": "1.0.0",
                "runtime_id": "asterion.prime",
            }
        ],
        "policies": ["policy.budget"],
        "host_capabilities": ["clock.monotonic", "storage.private"],
        "control_capabilities": list(binding.capabilities),
    }
    return resolve_agent_system(
        manifest,
        application_providers=(_provider(root),),
        control_factories=ControlPlaneFactoryRegistry((binding,)),
        host_capabilities=("clock.monotonic", "storage.private"),
    )


def _compact() -> SessionContextCommand:
    return SessionContextCommand(
        "compact-1",
        "session-1",
        1,
        1,
        "compact-key-1",
        "session.compact",
        {
            "continuation_id": "continuation-1",
            "instructions_ref": None,
            "budget": {
                "controller_tokens": 16_000,
                "application_tokens": 0,
                "child_tokens": 0,
                "aggregate_tokens": 16_000,
                "cost_micros": 125_000,
                "deadline_ms": 100_000,
            },
        },
    )


def _continuation() -> SessionContextCommand:
    return SessionContextCommand(
        "continue-1",
        "session-1",
        1,
        1,
        "continue-key-1",
        "session.continuation.resume",
        {"continuation_id": "continuation-1"},
    )


class TestAsterionPrimeRecovery(unittest.IsolatedAsyncioTestCase):
    async def test_file_journal_reconstructs_clean_attachment_without_replay(
        self,
    ) -> None:
        fixture = PrimeBackendHarness()
        journal_temp = tempfile.TemporaryDirectory()
        journal_root = Path(journal_temp.name) / "journal"
        plan = _plan(Path(journal_temp.name))
        envelope = authority()
        backend_closed = False
        try:
            client1 = build_asterion_prime_control_plane_client(fixture.context())
            host1 = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=AuthorityLedger(envelope),
                journal=FileCanonicalJournal.open(journal_root, "session-1"),
                client=client1,
                session_context_client=client1,
                action_executor=SpyExecutor(),
                clock_ms=lambda: 1_000,
            )
            await host1.dispatch(create_command())
            await host1.pump()
            await fixture.backend.execute_prompt(
                PrimePromptRequest(
                    "stage-one", "session-1", 1, "SENTINEL_PRIVATE_STAGE_ONE"
                )
            )
            context1 = host1.session_context_manager
            assert context1 is not None
            compact_receipt = await context1.execute(_compact())
            self.assertEqual(compact_receipt.status, "succeeded")
            recovered_checkpoint = fixture.store.recover_checkpoint()
            assert recovered_checkpoint is not None
            first_checkpoint = recovered_checkpoint.checkpoint
            first_cursor = fixture.backend.snapshot().cursor
            first_attachment_generation = client1._attachment.generation
            journal_position = host1.snapshot().journal_position
            await host1.close()

            reopened = FileCanonicalJournal.open(journal_root, "session-1")
            recovered = recover_control_host_state(
                reopened.replay(JournalCursor(0)),
                envelope,
                expected_session_id="session-1",
                expected_generation=1,
            )
            self.assertEqual(recovered.journal_position, journal_position)
            self.assertEqual(recovered.state.generation, 1)
            self.assertEqual(recovered.state.authority_revision, 1)
            self.assertEqual(recovered.authority.usage.aggregate_tokens, 16_000)

            client2 = build_asterion_prime_control_plane_client(fixture.context())
            host2 = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=AuthorityLedger(envelope),
                journal=reopened,
                client=client2,
                session_context_client=client2,
                action_executor=SpyExecutor(),
                clock_ms=lambda: 1_000,
            )
            self.assertEqual(
                client2._attachment.generation, first_attachment_generation + 1
            )
            self.assertEqual(client2._attachment.snapshot().identity.generation, 1)
            await host2.pump()
            self.assertEqual(host2.snapshot().state.next_sequence - 1, first_cursor)
            reopened_checkpoint = fixture.store.recover_checkpoint()
            assert reopened_checkpoint is not None
            self.assertEqual(reopened_checkpoint.checkpoint, first_checkpoint)
            before = (fixture.rpc.calls, fixture.rpc.compacts)
            context2 = host2.session_context_manager
            assert context2 is not None
            continuation_receipt = await context2.execute(_continuation())
            self.assertEqual(continuation_receipt.status, "succeeded")
            self.assertEqual((fixture.rpc.calls, fixture.rpc.compacts), before)

            await fixture.backend.execute_prompt(
                PrimePromptRequest(
                    "stage-two", "session-1", 1, "SENTINEL_PRIVATE_STAGE_TWO"
                )
            )
            self.assertEqual((fixture.rpc.calls, fixture.rpc.compacts), (2, 1))
            await host2.close()
            self.assertEqual(fixture.rpc.closes, 0)
            await fixture.backend.close()
            backend_closed = True
            self.assertEqual(fixture.rpc.closes, 1)
            self.assertTrue(fixture.worker.closed)
        finally:
            if not backend_closed:
                await fixture.backend.close()
            fixture.peer.close()
            fixture.temp.cleanup()
            journal_temp.cleanup()

    async def test_recovery_rejects_crossed_authority_before_attachment(self) -> None:
        fixture = PrimeBackendHarness()
        try:
            with self.assertRaises(Exception) as raised:
                build_asterion_prime_control_plane_client(
                    fixture.context(authority=replace(authority(), revision=2))
                )
            self.assertNotIn(str(fixture.private), str(raised.exception))
        finally:
            await fixture.close()


if __name__ == "__main__":
    unittest.main()
