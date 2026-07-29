from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import asterion.capabilities.catalog as capability_catalog
from asterion.capabilities.catalog import (
    CapabilityCatalogError,
    CapabilityRef,
    discover_capabilities,
)
from asterion.capabilities.protocol import validate_capability_manifest


FIXTURES = Path(__file__).parent / "fixtures/capabilities/v1"
VALID_CAPABILITY_FIXTURE = {
    "protocol": "asterion.capability/v1",
    "capability_id": "example.research",
    "version": "1.0.0",
    "kind": "research",
    "provides_capabilities": ["research.local"],
    "requires_capabilities": [],
    "requires_policies": [],
    "emits_events": ["research.completed"],
    "consumes_events": [],
    "produces_artifacts": ["application/vnd.example.research+json"],
    "consumes_artifacts": [],
}
VALIDATED_CAPABILITY_FIXTURE = {
    **VALID_CAPABILITY_FIXTURE,
    "provides_capabilities": ("research.local",),
    "requires_capabilities": (),
    "requires_policies": (),
    "emits_events": ("research.completed",),
    "consumes_events": (),
    "produces_artifacts": ("application/vnd.example.research+json",),
    "consumes_artifacts": (),
}


def manifest(capability_id: str, *, version: str = "1.0.0") -> dict[str, object]:
    return {
        "protocol": "asterion.capability/v1",
        "capability_id": capability_id,
        "version": version,
        "kind": "capability",
        "provides_capabilities": [f"{capability_id}.provided"],
        "requires_capabilities": [],
        "requires_policies": [],
        "emits_events": [],
        "consumes_events": [],
        "produces_artifacts": [],
        "consumes_artifacts": [],
    }


def _file_identity(path: Path) -> tuple[int, int]:
    value = path.stat()
    return value.st_dev, value.st_ino


def _fd_identity(fd: int) -> tuple[int, int]:
    value = os.fstat(fd)
    return value.st_dev, value.st_ino


class CapabilityCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        physical_temporary_root = Path(self.temporary_directory.name).resolve()
        self.root = physical_temporary_root / "capabilitys"
        self.root.mkdir()
        self.write_manifest(self.root / "capability.json", manifest("capability.one"))

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_manifest(self, path: Path, value: dict[str, object]) -> None:
        path.write_text(json.dumps(value))

    def test_rejects_the_removed_package_identity_and_protocol(self) -> None:
        valid = manifest("example.research")
        invalid_values = (
            {**valid, "package_id": valid["capability_id"]},
            {**valid, "protocol": "dci.package/v1"},
        )

        for value in invalid_values:
            with self.subTest(value=value):
                self.write_manifest(self.root / "invalid.json", value)
                with self.assertRaises(CapabilityCatalogError):
                    discover_capabilities((self.root,))

    def test_valid_capability_fixture_uses_the_asterion_identity(self) -> None:
        value = json.loads((FIXTURES / "valid-capability.json").read_text())

        validated = validate_capability_manifest(value)

        self.assertEqual(value, VALID_CAPABILITY_FIXTURE)
        self.assertEqual(validated, VALIDATED_CAPABILITY_FIXTURE)

    def test_validated_manifest_is_a_deep_immutable_snapshot(self) -> None:
        source = manifest("example.research")

        validated = validate_capability_manifest(source)
        source["kind"] = "policy"
        source["provides_capabilities"].append("changed")

        self.assertEqual(validated["kind"], "capability")
        self.assertEqual(
            validated["provides_capabilities"],
            ("example.research.provided",),
        )
        with self.assertRaises(TypeError):
            validated["kind"] = "policy"  # type: ignore[reportIndexIssue]
        with self.assertRaises(AttributeError):
            validated["provides_capabilities"].append(  # type: ignore[reportAttributeAccessIssue]
                "changed"
            )

    def test_capability_ref_has_an_exact_selector(self) -> None:
        self.assertEqual(
            CapabilityRef("example.research", "1.0.0").selector,
            "example.research@1.0.0",
        )

    def test_entry_manifest_is_deeply_immutable(self) -> None:
        catalog = discover_capabilities((self.root,))
        entry = catalog.entries[0]

        with self.assertRaises(TypeError):
            entry.manifest["kind"] = "policy"  # pyright: ignore[reportIndexIssue]
        with self.assertRaises(AttributeError):
            entry.manifest["provides_capabilities"].append(  # pyright: ignore[reportAttributeAccessIssue]
                "changed"
            )

    def test_selected_manifest_is_fresh(self) -> None:
        catalog = discover_capabilities((self.root,))
        ref = catalog.entries[0].ref

        first: dict[str, object] = catalog.select((ref,))[0]
        first["kind"] = "policy"
        first_capabilities = first["provides_capabilities"]
        self.assertIsInstance(first_capabilities, list)
        assert isinstance(first_capabilities, list)
        first_capabilities.append("changed")

        second: dict[str, object] = catalog.select((ref,))[0]

        self.assertEqual(second["kind"], "capability")
        self.assertEqual(
            second["provides_capabilities"], ["capability.one.provided"]
        )

    def test_duplicate_catalog_roots_are_rejected(self) -> None:
        with self.assertRaises(CapabilityCatalogError):
            discover_capabilities((self.root, self.root))

    def test_symlink_catalog_root_is_rejected(self) -> None:
        symlink = self.root.parent / "capabilitys-link"
        symlink.symlink_to(self.root, target_is_directory=True)

        with self.assertRaises(CapabilityCatalogError) as caught:
            discover_capabilities((symlink,))

        self.assertIn("catalog root is a symlink", str(caught.exception))

    def test_intermediate_symlink_catalog_root_is_rejected(self) -> None:
        external_parent = self.root.parent / "external-parent"
        external_root = external_parent / "capabilitys"
        external_root.mkdir(parents=True)
        self.write_manifest(
            external_root / "external.json",
            manifest("sentinel.intermediate-alias"),
        )
        alias = self.root.parent / "alias"
        alias.symlink_to(external_parent, target_is_directory=True)

        with self.assertRaises(CapabilityCatalogError) as caught:
            discover_capabilities((alias / "capabilitys",))

        self.assertNotIn("sentinel.intermediate-alias", str(caught.exception))

    def test_parent_component_catalog_root_is_rejected(self) -> None:
        aliased_root = self.root / ".." / self.root.name

        with self.assertRaises(CapabilityCatalogError) as caught:
            discover_capabilities((aliased_root,))

        self.assertEqual(str(caught.exception), f"catalog root is invalid: {aliased_root}")

    def test_dot_and_empty_roots_use_the_pinned_current_directory(self) -> None:
        current_directory = os.open(".", os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.chdir(self.root)
            for root in (Path("."), Path("")):
                with self.subTest(root=str(root)):
                    catalog = discover_capabilities((root,))
                    self.assertEqual(
                        tuple(entry.ref for entry in catalog.entries),
                        (CapabilityRef("capability.one", "1.0.0"),),
                    )
                    self.assertEqual(
                        catalog.entries[0].source,
                        self.root / "capability.json",
                    )
        finally:
            os.fchdir(current_directory)
            os.close(current_directory)

    def test_symlink_capability_document_is_rejected(self) -> None:
        document = self.root / "linked.json"
        document.symlink_to(self.root / "capability.json")

        with self.assertRaises(CapabilityCatalogError) as caught:
            discover_capabilities((self.root,))

        self.assertIn("capability document is a symlink", str(caught.exception))

    def test_document_replacement_cannot_open_external_manifest(self) -> None:
        document = self.root / "capability.json"
        original_document = self.root / "capability.original"
        external_root = self.root.parent / "external-documents"
        external_root.mkdir()
        external_document = external_root / "external.json"
        self.write_manifest(
            external_document,
            manifest("sentinel.external-document"),
        )
        external_identity = _file_identity(external_document)
        original_is_symlink = Path.is_symlink
        original_open = os.open
        original_fdopen = os.fdopen
        replaced = False

        def replace_document() -> None:
            nonlocal replaced
            if replaced:
                return
            document.rename(original_document)
            document.symlink_to(external_document)
            replaced = True

        def raced_is_symlink(path: Path) -> bool:
            result = original_is_symlink(path)
            if path == document and not result:
                replace_document()
            return result

        def raced_open(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            if dir_fd is not None and os.fsdecode(path) == document.name:
                replace_document()
            return original_open(path, flags, mode, dir_fd=dir_fd)

        def guarded_fdopen(fd: int, *args: object, **kwargs: object):
            self.assertNotEqual(_fd_identity(fd), external_identity)
            return original_fdopen(fd, *args, **kwargs)

        with (
            patch.object(Path, "is_symlink", raced_is_symlink),
            patch.object(os, "open", raced_open),
            patch.object(os, "fdopen", guarded_fdopen),
            self.assertRaises(CapabilityCatalogError) as caught,
        ):
            discover_capabilities((self.root,))

        self.assertNotIn("sentinel.external-document", str(caught.exception))

    def test_root_replacement_cannot_open_external_manifest(self) -> None:
        original_root = self.root.parent / "capabilitys-original"
        external_root = self.root.parent / "external-root"
        external_root.mkdir()
        external_document = external_root / "external.json"
        self.write_manifest(external_document, manifest("sentinel.external-root"))
        external_identity = _file_identity(external_document)
        original_is_symlink = Path.is_symlink
        original_open = os.open
        original_fdopen = os.fdopen
        parent_identity = _file_identity(self.root.parent)
        replaced = False

        def replace_root() -> None:
            nonlocal replaced
            if replaced:
                return
            self.root.rename(original_root)
            self.root.symlink_to(external_root, target_is_directory=True)
            replaced = True

        def raced_is_symlink(path: Path) -> bool:
            result = original_is_symlink(path)
            if path == self.root and not result:
                replace_root()
            return result

        def raced_open(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            whole_root_open = (
                dir_fd is None and Path(os.fsdecode(path)) == self.root
            )
            component_root_open = (
                dir_fd is not None
                and os.fsdecode(path) == self.root.name
                and _fd_identity(dir_fd) == parent_identity
            )
            if whole_root_open or component_root_open:
                replace_root()
            return original_open(path, flags, mode, dir_fd=dir_fd)

        def guarded_fdopen(fd: int, *args: object, **kwargs: object):
            self.assertNotEqual(_fd_identity(fd), external_identity)
            return original_fdopen(fd, *args, **kwargs)

        with (
            patch.object(Path, "is_symlink", raced_is_symlink),
            patch.object(os, "open", raced_open),
            patch.object(os, "fdopen", guarded_fdopen),
            self.assertRaises(CapabilityCatalogError) as caught,
        ):
            discover_capabilities((self.root,))

        self.assertNotIn("sentinel.external-root", str(caught.exception))

    def test_provenance_interrupt_closes_every_open_root_descriptor(self) -> None:
        original_open = os.open
        opened_descriptors: list[int] = []

        def recording_open(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
            opened_descriptors.append(descriptor)
            return descriptor

        with (
            patch.object(os, "open", recording_open),
            patch.object(
                capability_catalog,
                "_path_from_descriptor",
                side_effect=KeyboardInterrupt,
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            discover_capabilities((self.root,))

        leaked: list[int] = []
        for descriptor in opened_descriptors:
            try:
                os.fstat(descriptor)
            except OSError:
                continue
            leaked.append(descriptor)
            os.close(descriptor)
        self.assertEqual(leaked, [])

    def test_discovery_fails_closed_without_pinned_filesystem_primitives(self) -> None:
        with (
            patch.object(
                capability_catalog,
                "_PINNED_DISCOVERY_AVAILABLE",
                False,
                create=True,
            ),
            self.assertRaises(CapabilityCatalogError) as caught,
        ):
            discover_capabilities((self.root,))

        self.assertEqual(
            str(caught.exception),
            "secure capability discovery is unavailable",
        )

    def test_duplicate_capability_identity_is_rejected(self) -> None:
        self.write_manifest(
            self.root / "duplicate.json", manifest("capability.one")
        )

        with self.assertRaises(CapabilityCatalogError):
            discover_capabilities((self.root,))

    def test_unknown_exact_ref_is_rejected(self) -> None:
        catalog = discover_capabilities((self.root,))

        with self.assertRaises(CapabilityCatalogError):
            catalog.select((CapabilityRef("capability.unknown", "1.0.0"),))

    def test_duplicate_selection_is_rejected(self) -> None:
        catalog = discover_capabilities((self.root,))
        ref = catalog.entries[0].ref

        with self.assertRaises(CapabilityCatalogError):
            catalog.select((ref, ref))

    def test_entries_have_stable_source_ordering(self) -> None:
        other_root = self.root.parent / "other-capabilitys"
        other_root.mkdir()
        self.write_manifest(other_root / "z.json", manifest("capability.z"))
        self.write_manifest(self.root / "a.json", manifest("capability.a"))

        catalog = discover_capabilities((other_root, self.root))

        self.assertEqual(
            tuple(entry.ref for entry in catalog.entries),
            (
                CapabilityRef("capability.a", "1.0.0"),
                CapabilityRef("capability.one", "1.0.0"),
                CapabilityRef("capability.z", "1.0.0"),
            ),
        )


if __name__ == "__main__":
    unittest.main()
