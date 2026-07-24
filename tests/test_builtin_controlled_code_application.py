from __future__ import annotations

import unittest
from importlib import metadata
from pathlib import Path

from asterion.applications.discovery import (
    list_application_providers,
    load_application_provider,
)
from asterion.packages.catalog import PackageRef


PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "src/asterion"


class BuiltinControlledCodeApplicationTests(unittest.TestCase):
    def test_distribution_registers_two_independent_builtin_providers(self) -> None:
        entries = tuple(metadata.entry_points(group="asterion.applications"))
        values = list_application_providers(entry_points=entries)
        self.assertEqual(
            [value.provider_id for value in values],
            ["controlled-code", "dci-agent-lite"],
        )

    def test_controlled_code_provider_binds_exact_application_and_packages(self) -> None:
        provider = load_application_provider("controlled-code")
        self.assertEqual(provider.resource_root, SOURCE.resolve())
        self.assertEqual(len(provider.applications), 1)
        application = provider.applications[0]
        self.assertEqual((application.application_id, application.version), ("code.quality", "1.0.0"))
        self.assertEqual(application.runtime_ids, ("pi.reference",))
        self.assertEqual(
            {ref for ref, _ in application.implementations},
            {
                PackageRef("evaluation.code-quality", "1.0.0"),
                PackageRef("observability.execution-audit", "1.0.0"),
                PackageRef("workflow.code-quality", "1.0.0"),
            },
        )
        self.assertTrue(application.assembly_paths[0].is_relative_to(provider.resource_root))
        self.assertTrue(application.catalog_roots[0].is_relative_to(provider.resource_root))


if __name__ == "__main__":
    unittest.main()
