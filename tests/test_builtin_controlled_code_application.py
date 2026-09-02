from __future__ import annotations

import unittest
from importlib import metadata
from pathlib import Path

from asterion.applications.discovery import (
    list_application_providers,
    load_application_provider,
)
from asterion.capability_packages import CapabilityPackageRef


PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "src/asterion"


class BuiltinControlledCodeApplicationTests(unittest.TestCase):
    def test_distribution_registers_exact_global_builtin_provider_inventory(self) -> None:
        entries = tuple(metadata.entry_points(group="asterion.applications"))
        values = list_application_providers(entry_points=entries)
        self.assertEqual(
            [value.provider_id for value in values],
            ["controlled-code", "dci-agent-lite", "prime-agent"],
        )

    def test_controlled_code_provider_binds_exact_application_and_packages(self) -> None:
        provider = load_application_provider("controlled-code")
        self.assertEqual(provider.resource_root, SOURCE.resolve())
        self.assertEqual(len(provider.applications), 1)
        application = provider.applications[0]
        self.assertEqual((application.application_id, application.version), ("code.quality", "1.0.0"))
        self.assertEqual(application.runtime_ids, ("pi.reference",))
        self.assertEqual(
            application.capability_packages,
            (CapabilityPackageRef("controlled-code", "1.0.0"),),
        )
        self.assertTrue(application.assembly_paths[0].is_relative_to(provider.resource_root))
        self.assertEqual(application.catalog_roots, ())
        self.assertEqual(application.implementations, ())


if __name__ == "__main__":
    unittest.main()
