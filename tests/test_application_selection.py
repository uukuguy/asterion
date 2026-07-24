from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from asterion.applications.provider import (
    ApplicationProviderError,
    InstalledApplicationProvider,
)
from asterion.applications.selection import (
    ApplicationSelector,
    parse_application_selector,
    select_installed_application,
)
from tests.test_installed_application_provider import provider


class ApplicationSelectorTests(unittest.TestCase):
    def test_parses_one_exact_application_identity(self) -> None:
        self.assertEqual(
            parse_application_selector("example.research@1.2.3"),
            ApplicationSelector("example.research", "1.2.3"),
        )

    def test_rejects_non_exact_or_noncanonical_selectors(self) -> None:
        for value in (
            "example.research",
            "example.research@1",
            "example.research@1.2",
            "example.research@>=1.2.3",
            "Example.research@1.2.3",
            " example.research@1.2.3",
            "example.research@1.2.3 ",
            "example.research@@1.2.3",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ApplicationProviderError):
                    parse_application_selector(value)

    def test_selects_one_exact_application(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            value = provider(Path(temp_dir))
            application = select_installed_application(
                value, ApplicationSelector("example.research", "1.0.0")
            )
        self.assertEqual(application.application_id, "example.research")

    def test_selects_application_with_multiple_assemblies(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            value = provider(Path(temp_dir))
            application = value.applications[0]
            multiple = replace(
                value,
                applications=(
                    replace(
                        application,
                        assembly_paths=(
                            application.assembly_paths[0],
                            application.assembly_paths[0],
                        ),
                    ),
                ),
            )

            selected = select_installed_application(
                multiple, ApplicationSelector("example.research", "1.0.0")
            )

        self.assertEqual(selected.application_id, "example.research")
        self.assertEqual(len(selected.assembly_paths), 2)

    def test_unknown_and_duplicate_application_matches_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            value = provider(Path(temp_dir))
            application = value.applications[0]
            duplicate = InstalledApplicationProvider(
                protocol=value.protocol,
                provider_id=value.provider_id,
                resource_root=value.resource_root,
                applications=(application, application),
            )
            selector = ApplicationSelector("example.research", "1.0.0")
            for invalid in (duplicate,):
                with self.assertRaises(ApplicationProviderError) as caught:
                    select_installed_application(invalid, selector)
                self.assertNotIn(str(value.resource_root), str(caught.exception))
            with self.assertRaises(ApplicationProviderError):
                select_installed_application(
                    value, ApplicationSelector("missing.research", "1.0.0")
                )


if __name__ == "__main__":
    unittest.main()
