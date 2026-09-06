from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from contextlib import contextmanager
from collections.abc import Iterator, MutableMapping
from pathlib import Path
from typing import cast

from asterion.capability_packages import (
    CapabilityPackageRef,
    CapabilitySourceDeclaration,
    load_prepared_capability_source,
    open_portable_payload,
    prepare_capability_source,
)
from asterion.capability_packages.resolution import resolve_capability_source
from asterion.capability_packages.sources.local import (
    LocalDirectoryCapabilityPackageSource,
    LocalDirectoryCapabilitySourceError,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "extensions" / "minimal"
PACKAGE_REF = CapabilityPackageRef("example.package", "1.0.0")
SOURCE_ID = "example.package.local-directory"
SOURCE_KIND = "local-directory"
ERROR_MESSAGE = "local capability source is invalid"
MODULE_PREFIX = "_asterion_local_capability_"


def assert_stable_error(
    test_case: unittest.TestCase,
    error: BaseException,
    sentinels: tuple[str, ...] = (),
) -> None:
    test_case.assertEqual(str(error), ERROR_MESSAGE)
    cursor: BaseException | None = error
    seen: set[int] = set()
    while cursor is not None:
        if id(cursor) in seen:
            test_case.fail("exception chain contains a cycle")
        seen.add(id(cursor))
        rendered = repr(cursor)
        for sentinel in sentinels:
            test_case.assertNotIn(sentinel, rendered)
        cursor = cursor.__cause__ or cursor.__context__
    test_case.assertIsNone(error.__cause__)
    test_case.assertIsNone(error.__context__)


def copy_fixture(target: Path) -> Path:
    target = target.parent.resolve() / target.name
    root = target / "minimal"
    shutil.copytree(FIXTURE_ROOT, root)
    return root


def declaration(root: Path, **overrides: object) -> CapabilitySourceDeclaration:
    payload_sha256 = cast(str | None, overrides.pop("payload_sha256", None))
    if payload_sha256 is None:
        payload_sha256 = open_portable_payload(root / "payload").payload_sha256
    locator_override = cast(dict[str, object], overrides.pop("locator", {}))
    locator: dict[str, object] = {
        "root": root,
        "payload_root": "payload",
        "module_path": "provider.py",
        "factory_name": "create_package",
    }
    locator.update(locator_override)
    return CapabilitySourceDeclaration(
        source_id=cast(str, overrides.pop("source_id", SOURCE_ID)),
        kind=cast(str, overrides.pop("kind", SOURCE_KIND)),
        package_ref=cast(
            CapabilityPackageRef, overrides.pop("package_ref", PACKAGE_REF)
        ),
        payload_sha256=payload_sha256,
        private_locator=locator,
    )


@contextmanager
def chdir(path: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def scoped_module_name(root: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    digest.update(SOURCE_ID.encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(root / "provider.py").encode("utf-8"))
    return MODULE_PREFIX + digest.hexdigest()


class LocalDirectoryCapabilitySourceTests(unittest.TestCase):
    def test_discover_and_open_payload_validate_metadata_without_provider_import(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = copy_fixture(Path(temp_dir))
            source = LocalDirectoryCapabilityPackageSource((declaration(root),))

            previous = os.environ.get("ASTERION_TEST_FORBID_PROVIDER_IMPORT")
            os.environ["ASTERION_TEST_FORBID_PROVIDER_IMPORT"] = "1"
            try:
                candidates = source.discover_metadata()
                candidate = resolve_capability_source(PACKAGE_REF, candidates, None)
                payload = source.open_payload(candidate)
            finally:
                if previous is None:
                    os.environ.pop("ASTERION_TEST_FORBID_PROVIDER_IMPORT", None)
                else:
                    os.environ["ASTERION_TEST_FORBID_PROVIDER_IMPORT"] = previous

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidate.package_ref, PACKAGE_REF)
        self.assertEqual(candidate.source_id, SOURCE_ID)
        self.assertEqual(candidate.source_kind, SOURCE_KIND)
        self.assertEqual(candidate.payload_sha256, payload.payload_sha256)
        self.assertEqual(candidate.metadata, {})
        self.assertEqual(payload.manifest.package_ref, PACKAGE_REF)

    def test_load_provider_imports_only_exact_selected_module_after_identity_validation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = copy_fixture(Path(temp_dir))
            source = LocalDirectoryCapabilityPackageSource((declaration(root),))
            previous = os.environ.get("ASTERION_TEST_FORBID_PROVIDER_IMPORT")
            os.environ["ASTERION_TEST_FORBID_PROVIDER_IMPORT"] = "1"
            try:
                prepared = prepare_capability_source(PACKAGE_REF, (source,), None)
            finally:
                if previous is None:
                    os.environ.pop("ASTERION_TEST_FORBID_PROVIDER_IMPORT", None)
                else:
                    os.environ["ASTERION_TEST_FORBID_PROVIDER_IMPORT"] = previous
            before_path = tuple(sys.path)
            before_modules = set(sys.modules)

            installed = load_prepared_capability_source(prepared)

        self.assertEqual(tuple(sys.path), before_path)
        self.assertEqual(installed.package_ref, PACKAGE_REF)
        self.assertEqual(installed.payload_sha256, prepared.payload.payload_sha256)
        self.assertEqual(installed.source_id, SOURCE_ID)
        self.assertEqual(installed.source_kind, SOURCE_KIND)
        self.assertFalse(
            any(
                name.startswith("_asterion_local_capability_")
                for name in set(sys.modules) - before_modules
            )
        )

    def test_rejects_symlinks_and_path_escapes_before_provider_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            valid = copy_fixture(base / "valid")
            external = copy_fixture(base / "external")
            valid_digest = open_portable_payload(valid / "payload").payload_sha256
            cases: list[tuple[str, Path, dict[str, object]]] = []

            root_symlink = base / "root-link"
            root_symlink.symlink_to(valid, target_is_directory=True)
            cases.append(("root", root_symlink, {"payload_sha256": valid_digest}))

            intermediate_parent = base / "intermediate"
            intermediate_parent.mkdir()
            (intermediate_parent / "link").symlink_to(valid, target_is_directory=True)
            cases.append(
                (
                    "intermediate",
                    intermediate_parent / "link",
                    {"payload_sha256": valid_digest},
                )
            )

            descriptor = copy_fixture(base / "descriptor")
            (descriptor / "payload" / "capability-package.json").unlink()
            (descriptor / "payload" / "capability-package.json").symlink_to(
                valid / "payload" / "capability-package.json"
            )
            cases.append(("descriptor", descriptor, {"payload_sha256": valid_digest}))

            child = copy_fixture(base / "child")
            shutil.rmtree(child / "payload" / "resources")
            (child / "payload" / "resources").symlink_to(
                valid / "payload" / "resources",
                target_is_directory=True,
            )
            cases.append(("child", child, {"payload_sha256": valid_digest}))

            cases.extend(
                [
                    (
                        "outside-payload",
                        valid,
                        {
                            "payload_sha256": valid_digest,
                            "locator": {"payload_root": external / "payload"},
                        },
                    ),
                    (
                        "outside-module",
                        valid,
                        {
                            "payload_sha256": valid_digest,
                            "locator": {"module_path": external / "provider.py"},
                        },
                    ),
                ]
            )

            for name, root, overrides in cases:
                with self.subTest(name=name):
                    source = LocalDirectoryCapabilityPackageSource(
                        (declaration(root, **overrides),)
                    )
                    with self.assertRaises(
                        LocalDirectoryCapabilitySourceError
                    ) as raised:
                        source.discover_metadata()
                    assert_stable_error(
                        self,
                        raised.exception,
                        (
                            str(base),
                            "provider imported during local metadata discovery",
                        ),
                    )

    def test_rejects_relative_and_noncanonical_roots_without_cwd_rebinding(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir).resolve()
            root = copy_fixture(base / "valid")
            payload_sha256 = open_portable_payload(root / "payload").payload_sha256
            source = LocalDirectoryCapabilityPackageSource(
                (
                    declaration(
                        root,
                        payload_sha256=payload_sha256,
                        locator={"root": Path("valid/minimal")},
                    ),
                )
            )

            with chdir(base):
                with self.assertRaises(LocalDirectoryCapabilitySourceError) as raised:
                    source.discover_metadata()

            assert_stable_error(self, raised.exception, (str(base), "valid/minimal"))

            rebound = copy_fixture(base / "rebound")
            rebound_source = LocalDirectoryCapabilityPackageSource(
                (
                    declaration(
                        root,
                        payload_sha256=payload_sha256,
                        locator={"root": rebound / ".." / "valid" / "minimal"},
                    ),
                )
            )

            with self.assertRaises(
                LocalDirectoryCapabilitySourceError
            ) as rebound_error:
                rebound_source.discover_metadata()

            assert_stable_error(self, rebound_error.exception, (str(base), ".."))

    def test_rejects_missing_non_callable_and_mismatched_factory_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            missing = copy_fixture(base / "missing")
            non_callable = copy_fixture(base / "non-callable")
            mismatch = copy_fixture(base / "mismatch")
            interrupt = copy_fixture(base / "interrupt")
            (non_callable / "provider.py").write_text("create_package = 42\n")
            (mismatch / "provider.py").write_text(
                "from asterion.capability_packages.model import InstalledCapabilityPackage\n"
                "from asterion.capability_packages.protocol import CapabilityPackageRef\n"
                "def create_package():\n"
                "    return InstalledCapabilityPackage(\n"
                "        package_ref=CapabilityPackageRef('wrong.package','1.0.0'),\n"
                "        payload_sha256='0'*64,\n"
                "        source_id='wrong.source',\n"
                "        source_kind='local-directory',\n"
                "        catalog_roots=(), benchmark_suite_paths=(),\n"
                "        implementations=(), benchmark_bindings=())\n"
            )
            (interrupt / "provider.py").write_text(
                "def create_package():\n"
                "    raise KeyboardInterrupt('SECRET-INTERRUPT')\n"
            )
            cases = (
                (missing, {"locator": {"factory_name": "missing_factory"}}),
                (non_callable, {}),
                (mismatch, {}),
            )
            for root, overrides in cases:
                with self.subTest(root=root.name):
                    source = LocalDirectoryCapabilityPackageSource(
                        (declaration(root, **overrides),)
                    )
                    candidate = source.discover_metadata()[0]
                    before = set(sys.modules)
                    with self.assertRaises(
                        LocalDirectoryCapabilitySourceError
                    ) as raised:
                        source.load_provider(candidate)
                    assert_stable_error(
                        self, raised.exception, (str(base), "wrong.package")
                    )
                    self.assertEqual(
                        {
                            name
                            for name in set(sys.modules) - before
                            if name.startswith("_asterion_local_capability_")
                        },
                        set(),
                    )

            source = LocalDirectoryCapabilityPackageSource((declaration(interrupt),))
            with self.assertRaises(KeyboardInterrupt) as raised:
                source.load_provider(source.discover_metadata()[0])
            self.assertEqual(str(raised.exception), "SECRET-INTERRUPT")

    def test_scoped_import_restores_preexisting_none_and_object_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = copy_fixture(Path(temp_dir))
            source = LocalDirectoryCapabilityPackageSource((declaration(root),))
            candidate = source.discover_metadata()[0]
            module_name = scoped_module_name(root)
            module_cache = cast(MutableMapping[str, object], sys.modules)
            previous = module_cache.get(module_name, None)
            had_previous = module_name in module_cache
            try:
                module_cache[module_name] = None
                installed = source.load_provider(candidate)
                self.assertEqual(installed.package_ref, PACKAGE_REF)
                self.assertIn(module_name, module_cache)
                self.assertIsNone(module_cache[module_name])

                marker = object()
                module_cache[module_name] = marker
                source.load_provider(candidate)
                self.assertIs(module_cache[module_name], marker)

                interrupt_root = copy_fixture(Path(temp_dir) / "interrupt")
                (interrupt_root / "provider.py").write_text(
                    "def create_package():\n"
                    "    raise KeyboardInterrupt('SECRET-INTERRUPT')\n"
                )
                interrupt_source = LocalDirectoryCapabilityPackageSource(
                    (declaration(interrupt_root),)
                )
                interrupt_candidate = interrupt_source.discover_metadata()[0]
                interrupt_name = scoped_module_name(interrupt_root)
                interrupt_marker = object()
                interrupt_previous = module_cache.get(interrupt_name, None)
                interrupt_had_previous = interrupt_name in module_cache
                try:
                    module_cache[interrupt_name] = interrupt_marker
                    with self.assertRaises(KeyboardInterrupt):
                        interrupt_source.load_provider(interrupt_candidate)
                    self.assertIs(module_cache[interrupt_name], interrupt_marker)
                finally:
                    if interrupt_had_previous:
                        module_cache[interrupt_name] = interrupt_previous
                    else:
                        module_cache.pop(interrupt_name, None)
            finally:
                if had_previous:
                    module_cache[module_name] = previous
                else:
                    module_cache.pop(module_name, None)

    def test_rejects_identity_digest_and_replacement_races_without_context_leaks(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = copy_fixture(Path(temp_dir))
            source = LocalDirectoryCapabilityPackageSource(
                (
                    declaration(
                        root,
                        payload_sha256="0" * 64,
                        locator={"factory_name": "SECRET_FACTORY"},
                    ),
                )
            )

            with self.assertRaises(LocalDirectoryCapabilitySourceError) as raised:
                source.discover_metadata()

            assert_stable_error(self, raised.exception, (str(root), "SECRET_FACTORY"))

            valid_source = LocalDirectoryCapabilityPackageSource((declaration(root),))
            candidate = valid_source.discover_metadata()[0]
            (root / "provider.py").unlink()
            (root / "provider.py").mkdir()

            with self.assertRaises(LocalDirectoryCapabilitySourceError) as race:
                valid_source.load_provider(candidate)

            assert_stable_error(self, race.exception, (str(root), "provider.py"))

    def test_does_not_scan_parent_or_sibling_for_provider_module(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = copy_fixture(base)
            (base / "provider.py").write_text(
                "raise RuntimeError('SECRET-PARENT-SCAN')\n"
            )
            sibling = base / "sibling"
            sibling.mkdir()
            (sibling / "provider.py").write_text(
                "raise RuntimeError('SECRET-SIBLING-SCAN')\n"
            )
            (root / "provider.py").unlink()
            source = LocalDirectoryCapabilityPackageSource((declaration(root),))

            with self.assertRaises(LocalDirectoryCapabilitySourceError) as raised:
                source.load_provider(source.discover_metadata()[0])

        assert_stable_error(
            self,
            raised.exception,
            ("SECRET-PARENT-SCAN", "SECRET-SIBLING-SCAN", str(base)),
        )

    def test_rejects_duplicate_declarations_before_payload_or_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = copy_fixture(Path(temp_dir))
            source = LocalDirectoryCapabilityPackageSource(
                (declaration(root), declaration(root))
            )

            with self.assertRaises(LocalDirectoryCapabilitySourceError) as raised:
                source.discover_metadata()

        assert_stable_error(self, raised.exception, (str(root),))

    def test_invalid_declaration_errors_are_body_free(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = copy_fixture(Path(temp_dir))
            for source in (
                LocalDirectoryCapabilityPackageSource(()),
                LocalDirectoryCapabilityPackageSource(
                    (declaration(root, kind="python-distribution"),)
                ),
                LocalDirectoryCapabilityPackageSource(
                    (
                        declaration(
                            root,
                            locator={
                                "root": root,
                                "payload_root": "payload",
                                "module_path": "provider.py",
                                "factory_name": "create_package",
                                "extra": "SECRET",
                            },
                        ),
                    )
                ),
            ):
                with self.subTest(source=repr(source)):
                    with self.assertRaises(
                        LocalDirectoryCapabilitySourceError
                    ) as raised:
                        source.discover_metadata()
                    assert_stable_error(self, raised.exception, (str(root), "SECRET"))


if __name__ == "__main__":
    unittest.main()
