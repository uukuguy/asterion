from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from asterion.applications.discovery import (
    APPLICATION_INDEX_ENTRY_POINT_GROUP,
    list_application_providers,
    load_application_provider,
    select_application_provider_id,
)
from asterion.applications.provider import ApplicationProviderError
from asterion.benchmarks.model import ApplicationRef
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

    def test_application_index_selects_provider_without_loading_entry_points(
        self,
    ) -> None:
        provider_entries = (
            FakeEntryPoint(
                name="other-provider",
                factory=lambda: None,
                value="example.other:create_provider",
            ),
            FakeEntryPoint(
                name="example-provider",
                factory=lambda: None,
                value="example.selected:create_provider",
            ),
        )
        index_entries = (
            FakeEntryPoint(
                name="other.application__1.0.0",
                factory=lambda: None,
                group=APPLICATION_INDEX_ENTRY_POINT_GROUP,
                value="example.other:create_provider",
            ),
            FakeEntryPoint(
                name="example.application__1.0.0",
                factory=lambda: None,
                group=APPLICATION_INDEX_ENTRY_POINT_GROUP,
                value="example.selected:create_provider",
            ),
        )

        selected_from_ref = select_application_provider_id(
            ApplicationRef("example.application", "1.0.0"),
            application_entry_points=index_entries,
            provider_entry_points=provider_entries,
        )
        selected_from_text = select_application_provider_id(
            "example.application@1.0.0",
            application_entry_points=index_entries,
            provider_entry_points=provider_entries,
        )

        self.assertEqual(selected_from_ref, "example-provider")
        self.assertEqual(selected_from_text, "example-provider")
        self.assertEqual(
            [entry.loads for entry in (*provider_entries, *index_entries)],
            [0, 0, 0, 0],
        )

    def test_application_index_rejects_missing_and_ambiguous_matches_redacted(
        self,
    ) -> None:
        sentinel = "SECRET-INDEX-TARGET"
        selected_index = FakeEntryPoint(
            name="example.application__1.0.0",
            factory=lambda: None,
            group=APPLICATION_INDEX_ENTRY_POINT_GROUP,
            value=sentinel,
        )
        selected_provider = FakeEntryPoint(
            name="example-provider",
            factory=lambda: None,
            value=sentinel,
        )
        cases = (
            ("missing-index", (), (selected_provider,)),
            (
                "duplicate-index",
                (selected_index, selected_index),
                (selected_provider,),
            ),
            ("missing-provider", (selected_index,), ()),
            (
                "duplicate-provider-target",
                (selected_index,),
                (selected_provider, selected_provider),
            ),
        )

        for name, index_entries, provider_entries in cases:
            with self.subTest(name=name):
                with self.assertRaises(ApplicationProviderError) as raised:
                    select_application_provider_id(
                        "example.application@1.0.0",
                        application_entry_points=index_entries,
                        provider_entry_points=provider_entries,
                    )
                self.assertEqual(
                    str(raised.exception),
                    "installed application index selection is invalid",
                )
                self.assertNotIn(sentinel, str(raised.exception))

    def test_application_index_rejects_noncanonical_selectors(self) -> None:
        for selector in (
            "example.application",
            "example.application@1",
            " example.application@1.0.0",
            object(),
        ):
            with self.subTest(selector=selector):
                with self.assertRaises(ApplicationProviderError):
                    select_application_provider_id(
                        selector,
                        application_entry_points=(),
                        provider_entry_points=(),
                    )

    def test_builtin_application_index_covers_framework_applications(self) -> None:
        self.assertEqual(
            select_application_provider_id("code.quality@1.0.0"),
            "controlled-code",
        )
        self.assertEqual(
            select_application_provider_id("dci.agent-lite@1.0.0"),
            "dci-agent-lite",
        )


if __name__ == "__main__":
    unittest.main()
