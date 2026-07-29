from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from importlib import metadata
from pathlib import Path
from collections.abc import Iterator
from typing import Any, cast

from asterion.capability_packages.protocol import CapabilityPackageRef
from asterion.capability_packages.resolution import resolve_capability_source
from asterion.capability_packages.sources.distribution import (
    DistributionCapabilityPackageSource,
    DistributionCapabilitySourceError,
    ENTRY_POINT_GROUP,
)


FIXTURE_PROJECT = (
    Path(__file__).parent / "fixtures" / "extensions" / "distribution"
)
PACKAGE_REF = CapabilityPackageRef("acme.sample", "1.0.0")
SOURCE_ID = "acme.sample.python-distribution"
SOURCE_KIND = "python-distribution"
DIST_NAME = "asterion-acme-sample-extension"
PAYLOAD_RELATIVE = "asterion_capability_packages/acme.sample/1.0.0/payload"


def assert_stable_error(
    test_case: unittest.TestCase,
    error: BaseException,
    expected: str,
    sentinels: tuple[str, ...] = (),
) -> None:
    test_case.assertEqual(str(error), expected)
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


def build_and_install_fixture(target: Path) -> tuple[metadata.Distribution, ...]:
    target = target.parent.resolve() / target.name
    wheel_dir = target.parent / "wheelhouse"
    wheel_dir.mkdir()
    subprocess.run(
        (
            "uv",
            "build",
            "--wheel",
            "--out-dir",
            str(wheel_dir),
            str(FIXTURE_PROJECT),
        ),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    wheels = tuple(wheel_dir.glob("*.whl"))
    if len(wheels) != 1:
        raise AssertionError(f"expected one fixture wheel, found {len(wheels)}")
    subprocess.run(
        (
            "uv",
            "pip",
            "install",
            "--python",
            sys.executable,
            "--no-deps",
            "--target",
            str(target),
            str(wheels[0]),
        ),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return tuple(metadata.distributions(path=[str(target)]))


@contextmanager
def importable_target(target: Path) -> Iterator[None]:
    target = target.parent.resolve() / target.name
    original = tuple(sys.path)
    sys.path.insert(0, str(target))
    try:
        yield
    finally:
        sys.path[:] = list(original)


class FakeEntryPoint:
    def __init__(
        self,
        *,
        name: str,
        distribution: object,
        value: str = "private.module:create",
    ) -> None:
        self.name = name
        self.group = ENTRY_POINT_GROUP
        self.value = value
        self.dist = distribution
        self.loaded = False

    def load(self) -> object:
        self.loaded = True
        raise RuntimeError("SECRET-ENTRY-POINT-LOAD")


class FakeDistribution:
    name = "secret-fixture-dist"
    version = "9.9.9"
    metadata = {"Name": "secret-fixture-dist"}
    files = ()

    def __init__(
        self,
        entries: tuple[FakeEntryPoint, ...] = (),
        *,
        error: BaseException | None = None,
    ) -> None:
        self._entries = entries
        self._error = error
        for entry in entries:
            entry.dist = self

    @property
    def entry_points(self) -> tuple[FakeEntryPoint, ...]:
        if self._error is not None:
            raise self._error
        return self._entries

    def locate_file(self, path: object) -> Path:
        del path
        return Path("/private/SECRET-payload")


class HostileFilesDistribution(FakeDistribution):
    def __init__(self, entries: tuple[FakeEntryPoint, ...]) -> None:
        super().__init__(entries)
        self.files_accesses = 0

    @property
    def files(self) -> tuple[object, ...]:
        self.files_accesses += 1
        raise RuntimeError("SECRET-FILES-ACCESSED")


class DistributionCapabilitySourceTests(unittest.TestCase):
    def test_discover_and_open_payload_are_metadata_only_for_installed_wheel(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "target"
            distributions = build_and_install_fixture(target)
            source = DistributionCapabilityPackageSource(distributions)

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
        self.assertEqual(
            candidate.metadata,
            {"distribution_name": DIST_NAME, "distribution_version": "1.0.0"},
        )
        self.assertEqual(payload.manifest.package_ref, PACKAGE_REF)

    def test_load_provider_loads_only_selected_entry_after_identity_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "target"
            distributions = build_and_install_fixture(target)
            source = DistributionCapabilityPackageSource(distributions)
            candidate = resolve_capability_source(
                PACKAGE_REF, source.discover_metadata(), None
            )
            payload = source.open_payload(candidate)

            with importable_target(target):
                installed = source.load_provider(candidate)

        self.assertEqual(installed.package_ref, PACKAGE_REF)
        self.assertEqual(installed.payload_sha256, payload.payload_sha256)
        self.assertEqual(installed.source_id, SOURCE_ID)
        self.assertEqual(installed.source_kind, SOURCE_KIND)

    def test_duplicate_entry_point_identities_fail_before_import(self) -> None:
        first = FakeEntryPoint(name="acme.sample@1.0.0", distribution=cast(Any, None))
        second = FakeEntryPoint(name="acme.sample@1.0.0", distribution=cast(Any, None))
        distribution = FakeDistribution((first, second))
        source = DistributionCapabilityPackageSource((cast(Any, distribution),))

        with self.assertRaises(DistributionCapabilitySourceError) as raised:
            source.discover_metadata()

        assert_stable_error(
            self,
            raised.exception,
            "installed capability distribution source is invalid",
            ("SECRET-ENTRY-POINT-LOAD", "private.module", "secret-fixture-dist"),
        )
        self.assertFalse(first.loaded)
        self.assertFalse(second.loaded)

    def test_duplicate_entry_points_are_rejected_before_payload_file_access(self) -> None:
        first = FakeEntryPoint(name="acme.sample@1.0.0", distribution=cast(Any, None))
        second = FakeEntryPoint(name="acme.sample@1.0.0", distribution=cast(Any, None))
        distribution = HostileFilesDistribution((first, second))
        source = DistributionCapabilityPackageSource((cast(Any, distribution),))

        with self.assertRaises(DistributionCapabilitySourceError) as raised:
            source.discover_metadata()

        assert_stable_error(
            self,
            raised.exception,
            "installed capability distribution source is invalid",
            ("SECRET-FILES-ACCESSED",),
        )
        self.assertEqual(distribution.files_accesses, 0)
        self.assertFalse(first.loaded)
        self.assertFalse(second.loaded)

    def test_invalid_entry_point_and_hostile_metadata_errors_are_redacted(self) -> None:
        cases = (
            (
                FakeDistribution(
                    (
                        FakeEntryPoint(
                            name="acme.sample@latest",
                            distribution=cast(Any, None),
                            value="secret.provider:create",
                        ),
                    )
                ),
                ("latest", "secret.provider", "secret-fixture-dist"),
            ),
            (
                FakeDistribution(error=RuntimeError("SECRET-DISTRIBUTION-ERROR")),
                ("SECRET-DISTRIBUTION-ERROR", "secret-fixture-dist"),
            ),
        )
        for distribution, sentinels in cases:
            with self.subTest(sentinels=sentinels):
                source = DistributionCapabilityPackageSource((cast(Any, distribution),))

                with self.assertRaises(DistributionCapabilitySourceError) as raised:
                    source.discover_metadata()

                assert_stable_error(
                    self,
                    raised.exception,
                    "installed capability distribution source is invalid",
                    sentinels,
                )

    def test_base_exception_from_distribution_metadata_is_preserved(self) -> None:
        error = KeyboardInterrupt("SECRET-INTERRUPT")
        distribution = FakeDistribution(error=error)
        source = DistributionCapabilityPackageSource((cast(Any, distribution),))

        with self.assertRaises(KeyboardInterrupt) as raised:
            source.discover_metadata()

        self.assertIs(raised.exception, error)

    def test_selected_load_rejects_digest_mismatch_without_leaking_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "target"
            source = DistributionCapabilityPackageSource(
                build_and_install_fixture(target)
            )
            candidate = source.discover_metadata()[0]
            mismatched = type(candidate)(
                package_ref=candidate.package_ref,
                source_id=candidate.source_id,
                source_kind=candidate.source_kind,
                payload_sha256="0" * 64,
                metadata={"distribution_name": "SECRET-DIST"},
            )

            with self.assertRaises(DistributionCapabilitySourceError) as raised:
                source.load_provider(mismatched)

        assert_stable_error(
            self,
            raised.exception,
            "installed capability distribution source is invalid",
            (PAYLOAD_RELATIVE, DIST_NAME, "SECRET-DIST", str(target)),
        )


if __name__ == "__main__":
    unittest.main()
