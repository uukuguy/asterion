from __future__ import annotations

import json
import unittest
from collections.abc import Mapping
from pathlib import Path

from asterion.control.protocol import (
    AGENT_SYSTEM_PROTOCOL,
    CONTROL_PLANE_PROTOCOL,
    ControlProtocolError,
    validate_agent_system_manifest,
    validate_control_plane_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
SYSTEM_FIXTURES = ROOT / "tests" / "fixtures" / "agent_system" / "v1"
CONTROL_FIXTURES = ROOT / "tests" / "fixtures" / "control_plane" / "v1"
SYSTEM_SCHEMA = ROOT / "schemas" / "agent-system" / "v1" / "agent-system.schema.json"
CONTROL_SCHEMA = (
    ROOT
    / "schemas"
    / "control-plane"
    / "v1"
    / "control-plane-manifest.schema.json"
)


def _fixture(root: Path, name: str) -> dict[str, object]:
    value = json.loads((root / name).read_text())
    assert isinstance(value, dict)
    return value


class TestAgentSystemProtocol(unittest.TestCase):
    def test_protocol_identities_are_asterion_owned(self) -> None:
        self.assertEqual(AGENT_SYSTEM_PROTOCOL, "asterion.agent-system/v1")
        self.assertEqual(CONTROL_PLANE_PROTOCOL, "asterion.control-plane/v1")

    def test_valid_system_is_canonical_and_recursively_immutable(self) -> None:
        source = _fixture(SYSTEM_FIXTURES, "valid-system.json")

        manifest = validate_agent_system_manifest(source)

        self.assertEqual(manifest["system_id"], "research.system")
        applications = manifest["applications"]
        self.assertIsInstance(applications, tuple)
        assert isinstance(applications, tuple)
        first = applications[0]
        self.assertIsInstance(first, Mapping)
        assert isinstance(first, Mapping)
        self.assertEqual(first["application_id"], "alpha")
        with self.assertRaises(TypeError):
            manifest["system_id"] = "changed"  # type: ignore[index]
        with self.assertRaises(TypeError):
            first["application_id"] = "changed"  # type: ignore[index]

        source["system_id"] = "changed"
        source_applications = source["applications"]
        assert isinstance(source_applications, list)
        source_applications[0]["application_id"] = "changed"  # type: ignore[index]
        self.assertEqual(manifest["system_id"], "research.system")
        self.assertEqual(first["application_id"], "alpha")

    def test_valid_control_plane_is_canonical_and_recursively_immutable(self) -> None:
        source = _fixture(CONTROL_FIXTURES, "valid-manifest.json")

        manifest = validate_control_plane_manifest(source)

        self.assertEqual(manifest["control_plane_id"], "fake.control")
        self.assertEqual(
            manifest["commands"],
            (
                "action.resolve",
                "checkpoint.request",
                "input.submit",
                "session.attach",
                "session.cancel",
                "session.create",
                "session.pause",
                "session.resume",
            ),
        )
        with self.assertRaises(TypeError):
            manifest["commands"][0] = "changed"  # type: ignore[index]

    def test_rejects_invalid_static_contract_fixtures(self) -> None:
        cases = (
            (
                validate_agent_system_manifest,
                SYSTEM_FIXTURES,
                "invalid-unknown-field.json",
            ),
            (
                validate_agent_system_manifest,
                SYSTEM_FIXTURES,
                "invalid-unsorted-portfolio.json",
            ),
            (
                validate_control_plane_manifest,
                CONTROL_FIXTURES,
                "invalid-command-family.json",
            ),
            (
                validate_control_plane_manifest,
                CONTROL_FIXTURES,
                "invalid-secret-field.json",
            ),
        )
        for validator, root, name in cases:
            with self.subTest(name=name), self.assertRaises(ControlProtocolError):
                validator(_fixture(root, name))

    def test_rejects_noncanonical_scalar_arrays_and_exact_references(self) -> None:
        system = _fixture(SYSTEM_FIXTURES, "valid-system.json")
        control = _fixture(CONTROL_FIXTURES, "valid-manifest.json")
        system_cases = (
            {**system, "policies": ["policy.safe", "policy.budget"]},
            {**system, "control_capabilities": ["checkpointing", "checkpointing"]},
            {
                **system,
                "control_plane": {
                    "control_plane_id": "fake.control",
                    "version": "latest",
                },
            },
        )
        control_cases = (
            {**control, "capabilities": ["session-lifecycle", "checkpointing"]},
            {**control, "compatibility_ids": ["same/v1", "same/v1"]},
            {**control, "continuation_media_type": "not a media type"},
        )
        for value in system_cases:
            with self.subTest(value=value), self.assertRaises(ControlProtocolError):
                validate_agent_system_manifest(value)
        for value in control_cases:
            with self.subTest(value=value), self.assertRaises(ControlProtocolError):
                validate_control_plane_manifest(value)

    def test_errors_do_not_render_manifest_bodies(self) -> None:
        value = _fixture(CONTROL_FIXTURES, "valid-manifest.json")
        value["credentials"] = "SENTINEL_SECRET"

        with self.assertRaises(ControlProtocolError) as raised:
            validate_control_plane_manifest(value)

        self.assertNotIn("SENTINEL_SECRET", str(raised.exception))

    def test_canonical_schemas_are_closed_and_portable(self) -> None:
        system_schema = json.loads(SYSTEM_SCHEMA.read_text())
        control_schema = json.loads(CONTROL_SCHEMA.read_text())

        self.assertFalse(system_schema["additionalProperties"])
        self.assertFalse(control_schema["additionalProperties"])
        self.assertEqual(
            system_schema["properties"]["protocol"]["const"],
            AGENT_SYSTEM_PROTOCOL,
        )
        self.assertEqual(
            control_schema["properties"]["protocol"]["const"],
            CONTROL_PLANE_PROTOCOL,
        )
        rendered = json.dumps((system_schema, control_schema), sort_keys=True)
        for forbidden in (
            "prompt",
            "credentials",
            "executable_path",
            "environment",
            "private_root",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(f'"{forbidden}"', rendered)


if __name__ == "__main__":
    unittest.main()
