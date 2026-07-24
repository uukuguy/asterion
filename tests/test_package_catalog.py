from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from asterion.packages.catalog import (
    PackageCatalogError,
    PackageRef,
    discover_packages,
)


def manifest(package_id: str, *, version: str = "1.0.0") -> dict[str, object]:
    return {
        "protocol": "dci.package/v1",
        "package_id": package_id,
        "version": version,
        "kind": "capability",
        "provides_capabilities": [f"{package_id}.provided"],
        "requires_capabilities": [],
        "requires_policies": [],
        "emits_events": [],
        "consumes_events": [],
        "produces_artifacts": [],
        "consumes_artifacts": [],
    }


class PackageCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name) / "packages"
        self.root.mkdir()
        self.write_manifest(self.root / "capability.json", manifest("capability.one"))

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_manifest(self, path: Path, value: dict[str, object]) -> None:
        path.write_text(json.dumps(value))

    def test_entry_manifest_is_deeply_immutable(self) -> None:
        catalog = discover_packages((self.root,))
        entry = catalog.entries[0]

        with self.assertRaises(TypeError):
            entry.manifest["kind"] = "policy"
        with self.assertRaises(AttributeError):
            entry.manifest["provides_capabilities"].append("changed")

    def test_selected_manifest_is_fresh(self) -> None:
        catalog = discover_packages((self.root,))

        first = catalog.select((catalog.entries[0].ref,))[0]
        first["kind"] = "policy"
        second = catalog.select((catalog.entries[0].ref,))[0]

        self.assertEqual(second["kind"], "capability")

    def test_duplicate_catalog_roots_are_rejected(self) -> None:
        with self.assertRaises(PackageCatalogError):
            discover_packages((self.root, self.root))

    def test_symlink_catalog_root_is_rejected(self) -> None:
        symlink = self.root.parent / "packages-link"
        symlink.symlink_to(self.root, target_is_directory=True)

        with self.assertRaises(PackageCatalogError):
            discover_packages((symlink,))

    def test_symlink_package_document_is_rejected(self) -> None:
        document = self.root / "linked.json"
        document.symlink_to(self.root / "capability.json")

        with self.assertRaises(PackageCatalogError):
            discover_packages((self.root,))

    def test_duplicate_package_identity_is_rejected(self) -> None:
        self.write_manifest(
            self.root / "duplicate.json", manifest("capability.one")
        )

        with self.assertRaises(PackageCatalogError):
            discover_packages((self.root,))

    def test_unknown_exact_ref_is_rejected(self) -> None:
        catalog = discover_packages((self.root,))

        with self.assertRaises(PackageCatalogError):
            catalog.select((PackageRef("capability.unknown", "1.0.0"),))

    def test_duplicate_selection_is_rejected(self) -> None:
        catalog = discover_packages((self.root,))
        ref = catalog.entries[0].ref

        with self.assertRaises(PackageCatalogError):
            catalog.select((ref, ref))

    def test_entries_have_stable_source_ordering(self) -> None:
        other_root = self.root.parent / "other-packages"
        other_root.mkdir()
        self.write_manifest(other_root / "z.json", manifest("capability.z"))
        self.write_manifest(self.root / "a.json", manifest("capability.a"))

        catalog = discover_packages((other_root, self.root))

        self.assertEqual(
            tuple(entry.ref for entry in catalog.entries),
            (
                PackageRef("capability.a", "1.0.0"),
                PackageRef("capability.one", "1.0.0"),
                PackageRef("capability.z", "1.0.0"),
            ),
        )


if __name__ == "__main__":
    unittest.main()
