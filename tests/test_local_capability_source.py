from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from asterion.capability_packages.payload import open_portable_payload
from asterion.capability_packages.protocol import (
    CapabilityPackageRef,
    CapabilitySourceDeclaration,
)
from asterion.capability_packages.sources.local import (
    LocalDirectoryCapabilityPackageSource,
    LocalDirectoryCapabilitySourceError,
)


FIXTURE = Path(__file__).parent / "fixtures/extensions/minimal"
PACKAGE_REF = CapabilityPackageRef("example.package", "1.0.0")
SOURCE_ID = "example.local"
PRIVATE_MODULE = "example.provider"
TEMPORARY_MODULE_PREFIX = "_asterion_local_"


def _declaration(
    root: Path,
    *,
    module: str = PRIVATE_MODULE,
    name: str = "create_provider",
    package_ref: CapabilityPackageRef = PACKAGE_REF,
    source_id: str = SOURCE_ID,
    payload_sha256: str | None = None,
) -> CapabilitySourceDeclaration:
    if payload_sha256 is None and root.is_dir() and not root.is_symlink():
        payload_sha256 = open_portable_payload(root / "payload").payload_sha256
    return CapabilitySourceDeclaration(
        source_id=source_id,
        kind="local-directory",
        package_ref=package_ref,
        payload_sha256=payload_sha256,
        locator={"root": str(root)},
        provider_factory={"module": module, "name": name},
    )


class LocalDirectoryCapabilityPackageSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name).resolve() / "SENTINEL_PRIVATE_ROOT"
        shutil.copytree(FIXTURE, self.root)

    def assert_private_values_redacted(
        self,
        caught: BaseException,
        *private_values: object,
    ) -> None:
        rendered = str(caught)
        for value in (self.root, PRIVATE_MODULE, *private_values):
            self.assertNotIn(str(value), rendered)

    def assert_no_temporary_modules(self) -> None:
        self.assertFalse(
            tuple(
                name for name in sys.modules if name.startswith(TEMPORARY_MODULE_PREFIX)
            )
        )

    def test_valid_explicit_root_loads_one_exact_package_without_global_path_changes(
        self,
    ) -> None:
        declaration = _declaration(self.root)
        source = LocalDirectoryCapabilityPackageSource(declaration)
        original_path = tuple(sys.path)

        candidates = source.discover_metadata()
        payload = source.open_payload(candidates[0])
        source.validate_source_identity(candidates[0], payload)
        installed = source.load_provider(candidates[0])

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].package_ref, PACKAGE_REF)
        self.assertEqual(candidates[0].source_id, SOURCE_ID)
        self.assertEqual(candidates[0].source_kind, "local-directory")
        self.assertEqual(
            candidates[0].payload_sha256,
            declaration.payload_sha256,
        )
        self.assertEqual(dict(candidates[0].metadata), {})
        self.assertEqual(installed.package_ref, PACKAGE_REF)
        self.assertEqual(installed.payload_sha256, payload.payload_sha256)
        self.assertEqual(installed.source_id, SOURCE_ID)
        self.assertEqual(installed.source_kind, "local-directory")
        self.assertEqual(tuple(sys.path), original_path)
        self.assert_no_temporary_modules()
        self.assertNotIn(str(self.root), repr(candidates[0]))
        self.assertNotIn(PRIVATE_MODULE, repr(candidates[0]))

    def test_discovery_is_metadata_only_and_does_not_scan_parent_or_sibling(
        self,
    ) -> None:
        sibling = self.root.parent / "adjacent"
        sibling.mkdir()
        (sibling / "provider.py").write_text(
            "raise AssertionError('adjacent provider imported')\n",
            encoding="utf-8",
        )
        declaration = _declaration(self.root)

        with patch.dict(
            os.environ,
            {"ASTERION_TEST_FORBID_LOCAL_PROVIDER_IMPORT": "1"},
            clear=False,
        ):
            candidates = LocalDirectoryCapabilityPackageSource(
                declaration
            ).discover_metadata()

        self.assertEqual(
            tuple(candidate.package_ref for candidate in candidates),
            (PACKAGE_REF,),
        )
        self.assert_no_temporary_modules()

    def test_rejects_root_symlink_without_disclosing_private_values(self) -> None:
        target = self.root
        linked = target.parent / "SENTINEL_PRIVATE_LINK"
        linked.symlink_to(target, target_is_directory=True)
        declaration = CapabilitySourceDeclaration(
            source_id=SOURCE_ID,
            kind="local-directory",
            package_ref=PACKAGE_REF,
            payload_sha256=None,
            locator={"root": str(linked)},
            provider_factory={
                "module": PRIVATE_MODULE,
                "name": "create_provider",
            },
        )

        with self.assertRaises(LocalDirectoryCapabilitySourceError) as caught:
            LocalDirectoryCapabilityPackageSource(declaration)

        self.assert_private_values_redacted(caught.exception, linked)

    def test_rejects_malformed_or_noncanonical_declarations(self) -> None:
        declaration = _declaration(self.root)
        cases = (
            replace(declaration, source_id="invalid:source"),
            replace(declaration, package_ref="invalid"),  # type: ignore[arg-type]
            replace(declaration, payload_sha256="invalid"),
            replace(declaration, kind="builtin"),
            replace(
                declaration,
                locator={"root": str(self.root), "sibling": "private"},
            ),
            replace(
                declaration,
                locator={
                    "root": str(
                        self.root.parent / ".." / self.root.parent.name / self.root.name
                    )
                },
            ),
            replace(
                declaration,
                provider_factory={
                    "module": PRIVATE_MODULE,
                    "name": "create_provider",
                    "fallback": "private",
                },
            ),
        )
        for index, malformed in enumerate(cases):
            with (
                self.subTest(case=index),
                self.assertRaises(LocalDirectoryCapabilitySourceError) as caught,
            ):
                LocalDirectoryCapabilityPackageSource(malformed)
            self.assert_private_values_redacted(caught.exception)

    def test_rejects_descriptor_and_payload_child_symlinks(self) -> None:
        cases = (
            "payload/capability-package.json",
            "payload/capabilities/example-research.json",
        )
        for relative in cases:
            with self.subTest(relative=relative):
                case_root = self.root.parent / relative.replace("/", "-")
                shutil.copytree(FIXTURE, case_root)
                target = case_root / relative
                private_target = case_root.parent / f"SENTINEL_PRIVATE_{target.name}"
                private_target.write_bytes(target.read_bytes())
                target.unlink()
                target.symlink_to(private_target)
                declaration = CapabilitySourceDeclaration(
                    source_id=SOURCE_ID,
                    kind="local-directory",
                    package_ref=PACKAGE_REF,
                    payload_sha256=None,
                    locator={"root": str(case_root)},
                    provider_factory={
                        "module": PRIVATE_MODULE,
                        "name": "create_provider",
                    },
                )
                source = LocalDirectoryCapabilityPackageSource(declaration)
                candidate = source.discover_metadata()[0]

                with self.assertRaises(LocalDirectoryCapabilitySourceError) as caught:
                    source.open_payload(candidate)

                self.assert_private_values_redacted(
                    caught.exception,
                    case_root,
                    private_target,
                )

    def test_rejects_outside_root_or_symlinked_factory(self) -> None:
        outside = self.root.parent / "SENTINEL_PRIVATE_OUTSIDE.py"
        outside.write_text(
            "def create_provider():\n"
            "    raise AssertionError('outside provider imported')\n",
            encoding="utf-8",
        )
        (self.root / "escaped.py").symlink_to(outside)
        cases = (
            ("escaped", "create_provider"),
            ("../SENTINEL_PRIVATE_OUTSIDE", "create_provider"),
        )
        for module, name in cases:
            with self.subTest(module=module):
                declaration = _declaration(
                    self.root,
                    module=module,
                    name=name,
                )
                try:
                    source = LocalDirectoryCapabilityPackageSource(declaration)
                except LocalDirectoryCapabilitySourceError as error:
                    caught = error
                else:
                    with self.assertRaises(
                        LocalDirectoryCapabilitySourceError
                    ) as context:
                        source.load_provider(source.discover_metadata()[0])
                    caught = context.exception

                self.assert_private_values_redacted(
                    caught,
                    outside,
                    module,
                )
                self.assert_no_temporary_modules()

    def test_relative_import_cannot_follow_symlink_outside_root(self) -> None:
        outside = self.root.parent / "SENTINEL_PRIVATE_HELPER.py"
        outside.write_text(
            "VALUE = 'SENTINEL_OUTSIDE_VALUE'\n",
            encoding="utf-8",
        )
        helper = self.root / "example/helper.py"
        helper.symlink_to(outside)
        provider = self.root / "example/provider.py"
        provider.write_text(
            provider.read_text(encoding="utf-8").replace(
                "from __future__ import annotations\n",
                "from __future__ import annotations\n\nfrom .helper import VALUE\n",
                1,
            ),
            encoding="utf-8",
        )
        source = LocalDirectoryCapabilityPackageSource(_declaration(self.root))

        try:
            with self.assertRaises(LocalDirectoryCapabilitySourceError) as caught:
                source.load_provider(source.discover_metadata()[0])
        finally:
            self.assert_no_temporary_modules()

        self.assert_private_values_redacted(
            caught.exception,
            outside,
            helper,
            "SENTINEL_OUTSIDE_VALUE",
        )

    def test_missing_factory_fails_closed_and_cleans_import_state(self) -> None:
        source = LocalDirectoryCapabilityPackageSource(
            _declaration(self.root, name="SENTINEL_MISSING_FACTORY")
        )
        original_path = tuple(sys.path)

        with self.assertRaises(LocalDirectoryCapabilitySourceError) as caught:
            source.load_provider(source.discover_metadata()[0])

        self.assert_private_values_redacted(
            caught.exception,
            "SENTINEL_MISSING_FACTORY",
        )
        self.assertEqual(tuple(sys.path), original_path)
        self.assert_no_temporary_modules()

    def test_factory_failure_is_redacted_and_cleans_import_state(self) -> None:
        source = LocalDirectoryCapabilityPackageSource(_declaration(self.root))
        original_path = tuple(sys.path)

        with (
            patch.dict(
                os.environ,
                {"ASTERION_TEST_LOCAL_FACTORY_FAILURE": "1"},
                clear=False,
            ),
            self.assertRaises(LocalDirectoryCapabilitySourceError) as caught,
        ):
            source.load_provider(source.discover_metadata()[0])

        self.assert_private_values_redacted(
            caught.exception,
            "SENTINEL_LOCAL_FACTORY_FAILURE",
        )
        self.assertEqual(tuple(sys.path), original_path)
        self.assert_no_temporary_modules()

    def test_provider_identity_mismatches_fail_closed(self) -> None:
        for mismatch in ("package", "payload", "source", "source-id"):
            with self.subTest(mismatch=mismatch):
                source = LocalDirectoryCapabilityPackageSource(_declaration(self.root))
                with (
                    patch.dict(
                        os.environ,
                        {"ASTERION_TEST_LOCAL_IDENTITY_MISMATCH": mismatch},
                        clear=False,
                    ),
                    self.assertRaises(LocalDirectoryCapabilitySourceError) as caught,
                ):
                    source.load_provider(source.discover_metadata()[0])

                self.assert_private_values_redacted(
                    caught.exception,
                    "other.package",
                    "other.local",
                )
                self.assert_no_temporary_modules()

    def test_rejects_replaced_root_and_forged_candidate(self) -> None:
        source = LocalDirectoryCapabilityPackageSource(_declaration(self.root))
        candidate = source.discover_metadata()[0]
        original = self.root.parent / "SENTINEL_PRIVATE_ORIGINAL"
        self.root.rename(original)
        shutil.copytree(FIXTURE, self.root)

        with self.assertRaises(LocalDirectoryCapabilitySourceError) as replaced_root:
            source.discover_metadata()
        self.assert_private_values_redacted(
            replaced_root.exception,
            original,
        )

        replacement_source = LocalDirectoryCapabilityPackageSource(
            _declaration(self.root)
        )
        forged = replace(candidate, source_id="forged.local")
        for operation in (
            replacement_source.open_payload,
            replacement_source.load_provider,
        ):
            with (
                self.subTest(operation=operation),
                self.assertRaises(
                    LocalDirectoryCapabilitySourceError
                ) as forged_candidate,
            ):
                operation(forged)
            self.assert_private_values_redacted(
                forged_candidate.exception,
                "forged.local",
            )


if __name__ == "__main__":
    unittest.main()
