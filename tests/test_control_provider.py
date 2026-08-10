from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import cast


from asterion.control.factory import (
    ControlPlaneFactory,
    ControlPlaneFactoryBinding,
    ControlPlaneFactoryContext,
    ControlPlaneFactoryError,
    ControlPlaneFactoryRegistry,
    bind_selected_session_context_client,
)
from asterion.control.host import (
    ControlCommand,
    ControlEvent,
    ControlPlaneManifest,
    EventCursor,
)


ROOT = Path(__file__).resolve().parents[1]
CONTROL_FIXTURES = ROOT / "tests" / "fixtures" / "control_plane" / "v1"
WIRE_FIXTURES = ROOT / "tests" / "fixtures" / "agent_control" / "v1"


def _fixture(root: Path, name: str) -> dict[str, object]:
    value = json.loads((root / name).read_text())
    assert isinstance(value, dict)
    return value


class TestControlProvider(unittest.TestCase):
    def _binding(
        self,
        *,
        version: str = "1.0.0",
        factory: object | None = None,
    ) -> ControlPlaneFactoryBinding:
        return ControlPlaneFactoryBinding(
            control_plane_id="fake.control",
            version=version,
            commands=(
                "action.resolve",
                "checkpoint.request",
                "input.submit",
                "session.attach",
                "session.cancel",
                "session.create",
                "session.pause",
                "session.resume",
            ),
            events=(
                "action.proposed",
                "budget.reported",
                "checkpoint.created",
                "fault.raised",
                "goal.updated",
                "session.budget-limited",
                "session.cancelled",
                "session.completed",
                "session.created",
                "session.failed",
                "session.paused",
                "session.recovery-required",
                "session.running",
            ),
            capabilities=(
                "action-proposals",
                "checkpointing",
                "event-replay",
                "session-lifecycle",
            ),
            continuation_media_type="application/vnd.asterion.control-capsule",
            checkpoint_version="1.0.0",
            compatibility_ids=("asterion.agent-control/v1", "fake-control/v1"),
            factory=cast(
                ControlPlaneFactory,
                factory if factory is not None else (lambda context: context),
            ),
        )

    def test_host_values_validate_round_trip_and_copy_payloads(self) -> None:
        manifest_source = _fixture(CONTROL_FIXTURES, "valid-manifest.json")
        command_source = _fixture(
            WIRE_FIXTURES, "valid-command-session-create.json"
        )
        event_source = _fixture(WIRE_FIXTURES, "valid-event-action-proposed.json")

        manifest = ControlPlaneManifest.from_mapping(manifest_source)
        command = ControlCommand.from_mapping(command_source)
        event = ControlEvent.from_mapping(event_source)

        self.assertEqual(dict(manifest.to_mapping()), manifest_source)
        self.assertEqual(dict(command.to_mapping()), command_source)
        self.assertEqual(dict(event.to_mapping()), event_source)
        command_source["command_id"] = "changed"
        event_payload = event_source["payload"]
        assert isinstance(event_payload, dict)
        event_payload["action_id"] = "changed"
        self.assertEqual(command.command_id, "command-1")
        self.assertEqual(event.payload["action_id"], "action-1")
        with self.assertRaises(TypeError):
            command.payload["goal_ref"] = "changed"  # type: ignore[index]

    def test_event_cursor_is_immutable_and_validates_boundaries(self) -> None:
        cursor = EventCursor(generation=1, sequence=0)

        self.assertEqual(dict(cursor.to_mapping()), {"generation": 1, "sequence": 0})
        with self.assertRaises(AttributeError):
            cursor.sequence = 2  # type: ignore[misc]
        for generation, sequence in ((0, 0), (1, -1), (True, 0)):
            with self.subTest(generation=generation, sequence=sequence), self.assertRaises(
                ValueError
            ):
                EventCursor(generation=generation, sequence=sequence)

    def test_factory_registry_selects_exact_id_and_version(self) -> None:
        constructed: list[object] = []

        def construct(context: object) -> object:
            constructed.append(context)
            return context

        binding_v1 = self._binding(version="1.0.0", factory=construct)
        binding_v2 = self._binding(version="2.0.0", factory=construct)
        registry = ControlPlaneFactoryRegistry((binding_v2, binding_v1))

        self.assertIs(registry.select("fake.control", "1.0.0"), binding_v1)
        self.assertIs(registry.select("fake.control", "2.0.0"), binding_v2)
        self.assertEqual(constructed, [])
        with self.assertRaises(ControlPlaneFactoryError):
            registry.select("fake.control", "1.1.0")

    def test_session_context_extension_requires_manifest_and_implementation_agreement(
        self,
    ) -> None:
        plain_manifest = self._binding().manifest
        extension_manifest = ControlPlaneManifest(
            **{
                **plain_manifest.__dict__,
                "capabilities": (*plain_manifest.capabilities, "session.context-v1"),
                "compatibility_ids": (
                    "asterion.agent-control/v1",
                    "asterion.session-context/v1",
                    "fake-control/v1",
                ),
            }
        )

        async def execute_session_context(command):
            return command

        async def cancel_session_context(command_id):
            return command_id

        implementation = SimpleNamespace(
            manifest=extension_manifest,
            execute_session_context=execute_session_context,
            cancel_session_context=cancel_session_context,
        )
        plain = SimpleNamespace(manifest=plain_manifest)
        declared_without_implementation = SimpleNamespace(manifest=extension_manifest)
        implementation_without_declaration = SimpleNamespace(
            manifest=plain_manifest,
            execute_session_context=execute_session_context,
            cancel_session_context=cancel_session_context,
        )

        self.assertIs(
            bind_selected_session_context_client(implementation), implementation
        )
        self.assertIsNone(bind_selected_session_context_client(plain))
        for client in (
            declared_without_implementation,
            implementation_without_declaration,
        ):
            with self.subTest(client=client), self.assertRaises(
                ControlPlaneFactoryError
            ):
                bind_selected_session_context_client(client)

    def test_factory_registry_rejects_duplicates_and_invalid_bindings(self) -> None:
        binding = self._binding()
        with self.assertRaises(ControlPlaneFactoryError):
            ControlPlaneFactoryRegistry((binding, binding))
        with self.assertRaises(ControlPlaneFactoryError):
            ControlPlaneFactoryRegistry(
                (
                    self._binding(
                        factory="not-callable",
                    ),
                )
            )
        with self.assertRaises(ControlPlaneFactoryError):
            ControlPlaneFactoryRegistry(
                (
                    ControlPlaneFactoryBinding(
                        **{
                            **binding.__dict__,
                            "capabilities": (
                                "session-lifecycle",
                                "checkpointing",
                            ),
                        }
                    ),
                )
            )

    def test_factory_context_copies_and_redacts_private_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private_root = Path(directory)
            options = {"api_token": "SENTINEL_SECRET"}
            services = {"private.service": object()}

            context = ControlPlaneFactoryContext(
                system_id="research.system",
                system_version="1.0.0",
                control_plane_id="fake.control",
                control_plane_version="1.0.0",
                private_root=private_root,
                options=options,
                host_services=services,
            )

            options["api_token"] = "changed"
            services.clear()
            self.assertEqual(context.options["api_token"], "SENTINEL_SECRET")
            self.assertIn("private.service", context.host_services)
            rendered = repr(context)
            self.assertNotIn("SENTINEL_SECRET", rendered)
            self.assertNotIn(str(private_root), rendered)
            with self.assertRaises(TypeError):
                context.options["new"] = "value"  # type: ignore[index]

    def test_factory_context_rejects_missing_or_non_directory_private_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            file_path = Path(directory) / "capsule.txt"
            file_path.write_text("private")
            for private_root in (Path(directory) / "missing", file_path):
                with self.subTest(private_root=private_root), self.assertRaises(
                    ControlPlaneFactoryError
                ):
                    ControlPlaneFactoryContext(
                        system_id="research.system",
                        system_version="1.0.0",
                        control_plane_id="fake.control",
                        control_plane_version="1.0.0",
                        private_root=private_root,
                        options={},
                    )


if __name__ == "__main__":
    unittest.main()
