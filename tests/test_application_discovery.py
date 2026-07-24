from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from asterion.applications.discovery import (
    list_application_providers,
    load_application_provider,
)
from asterion.applications.provider import ApplicationProviderError
from tests.test_installed_application_provider import provider


@dataclass(frozen=True)
class FakeDistribution:
    name: str
    version: str


class FakeEntryPoint:
    def __init__(
        self,
        *,
        name: str,
        factory,
        group: str = "asterion.applications",
        value: str = "SECRET-MODULE-PATH",
    ) -> None:
        self.name = name
        self.group = group
        self.value = value
        self.dist = FakeDistribution("fixture-dist", "1.2.3")
        self.factory = factory
        self.loads = 0

    def load(self):
        self.loads += 1
        return self.factory


class ApplicationDiscoveryTests(unittest.TestCase):
    def test_list_is_sorted_metadata_only_and_never_loads(self) -> None:
        entries = (
            FakeEntryPoint(name="z-provider", factory=lambda: None),
            FakeEntryPoint(name="a-provider", factory=lambda: None),
            FakeEntryPoint(
                name="ignored", factory=lambda: None, group="other.group"
            ),
        )

        metadata = list_application_providers(entry_points=entries)

        self.assertEqual(
            tuple(item.provider_id for item in metadata),
            ("a-provider", "z-provider"),
        )
        self.assertEqual(metadata[0].distribution_name, "fixture-dist")
        self.assertEqual(metadata[0].distribution_version, "1.2.3")
        self.assertEqual([entry.loads for entry in entries], [0, 0, 0])
        self.assertNotIn("SECRET-MODULE-PATH", repr(metadata))

    def test_load_selects_exactly_one_provider_and_loads_no_adjacent_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            selected = FakeEntryPoint(
                name="example-app", factory=lambda: provider(Path(temp_dir))
            )
            adjacent = FakeEntryPoint(name="other-app", factory=lambda: None)

            loaded = load_application_provider(
                "example-app", entry_points=(adjacent, selected)
            )

        self.assertEqual(loaded.provider_id, "example-app")
        self.assertEqual(selected.loads, 1)
        self.assertEqual(adjacent.loads, 0)

    def test_missing_duplicate_and_factory_failures_are_redacted(self) -> None:
        sentinel = "SECRET-IMPORT-FAILURE"

        def fail():
            raise RuntimeError(sentinel)

        cases = (
            ("missing", ()),
            (
                "duplicate",
                (
                    FakeEntryPoint(name="duplicate", factory=lambda: None),
                    FakeEntryPoint(name="duplicate", factory=lambda: None),
                ),
            ),
            ("failed", (FakeEntryPoint(name="failed", factory=fail),)),
        )
        for selected, entries in cases:
            with self.subTest(selected=selected):
                with self.assertRaises(ApplicationProviderError) as raised:
                    load_application_provider(selected, entry_points=entries)
                self.assertNotIn(sentinel, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
