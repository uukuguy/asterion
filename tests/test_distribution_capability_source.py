from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from importlib import import_module
from importlib import metadata
from pathlib import Path
from typing import cast
from unittest.mock import patch

import asterion.capability_packages.sources.distribution as distribution_module
from asterion.capability_packages.model import CapabilityPackageCandidate
from asterion.capability_packages.protocol import CapabilityPackageRef
from asterion.capability_packages.protocol import IDENTIFIER
from asterion.capability_packages.sources.distribution import (
    DistributionCapabilityPackageSource,
    DistributionCapabilitySourceError,
)


FIXTURE = Path(__file__).parent / "fixtures/extensions/distribution"
PACKAGE_REF = CapabilityPackageRef("acme.sample", "1.0.0")
PROVIDER_MODULE = "acme_capability_sample.provider"


class _DuplicateEntryPoint:
    group = "asterion.capability_packages"

    def __init__(self, name: str) -> None:
        self.name = name
        self.loads = 0

    def load(self):
        self.loads += 1
        raise AssertionError("duplicate provider was loaded")


class _DuplicateDistribution:
    def __init__(self, installed: metadata.Distribution) -> None:
        self.name = installed.name
        self.version = installed.version
        self.files = installed.files
        self._installed = installed
        self.entry_points = (
            _DuplicateEntryPoint("acme.sample@1.0.0"),
            _DuplicateEntryPoint("acme.sample@1.0.0"),
        )

    def locate_file(self, path):
        return self._installed.locate_file(path)


class _MalformedEntryPoint:
    group = "asterion.capability_packages"

    def __init__(self) -> None:
        self.name = "acme.sample"
        self.loads = 0

    def load(self):
        self.loads += 1
        return import_module(PROVIDER_MODULE).create_package


class _MalformedDistribution:
    def __init__(
        self,
        installed: metadata.Distribution,
        entry_point: _MalformedEntryPoint,
    ) -> None:
        self.name = installed.name
        self.version = installed.version
        self.files = installed.files
        self.entry_points = (entry_point,)
        self._installed = installed

    def locate_file(self, path):
        return self._installed.locate_file(path)


class _MetadataEntryPoint:
    group = "asterion.capability_packages"

    def __init__(self, name: str) -> None:
        self.name = name


class _MetadataDistribution:
    def __init__(
        self,
        installed: metadata.Distribution,
        entry_point: _MetadataEntryPoint,
        *,
        name: str | None = None,
        version: str | None = None,
    ) -> None:
        self.name = name or installed.name
        self.version = version or installed.version
        self.files = installed.files
        self.entry_points = (entry_point,)
        self._installed = installed

    def locate_file(self, path):
        return self._installed.locate_file(path)


class DistributionCapabilityPackageSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._temporary.cleanup)
        temporary = Path(cls._temporary.name)
        wheel_dir = temporary / "wheel"
        target = temporary / "target"
        subprocess.run(
            [
                "uv",
                "build",
                "--wheel",
                "--out-dir",
                str(wheel_dir),
                str(FIXTURE),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        wheel = next(wheel_dir.glob("*.whl"))
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--target",
                str(target),
                "--no-deps",
                str(wheel),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        cls._target = target
        cls._distribution = next(
            distribution
            for distribution in metadata.distributions(path=[str(target)])
            if distribution.name == "acme-capability-sample"
        )

    def setUp(self) -> None:
        sys.modules.pop(PROVIDER_MODULE, None)

    def _source(self) -> DistributionCapabilityPackageSource:
        return DistributionCapabilityPackageSource((self._distribution,))

    def test_discovers_installed_wheel_metadata_without_importing_provider(
        self,
    ) -> None:
        with (
            patch.dict(
                os.environ,
                {"ASTERION_TEST_FORBID_PROVIDER_IMPORT": "1"},
                clear=False,
            ),
            _target_on_path(self._target),
        ):
            candidates = DistributionCapabilityPackageSource().discover_metadata()

        matching = tuple(
            candidate
            for candidate in candidates
            if candidate.package_ref == PACKAGE_REF
        )
        self.assertEqual(len(matching), 1)
        candidate = matching[0]
        self.assertEqual(candidate.package_ref, PACKAGE_REF)
        self.assertEqual(candidate.source_kind, "python-distribution")
        self.assertIsNone(candidate.payload_sha256)
        self.assertEqual(
            candidate.source_id,
            "python-distribution.acme-capability-sample.1-0-0.acme.sample.1.0.0.sha-cff21202bedd",
        )
        self.assertIsNotNone(IDENTIFIER.fullmatch(candidate.source_id))
        self.assertEqual(
            dict(candidate.metadata),
            {
                "distribution_name": "acme-capability-sample",
                "distribution_version": "1.0.0",
            },
        )
        self.assertNotIn(PROVIDER_MODULE, sys.modules)

    def test_discovers_metadata_entry_point_without_direct_distribution_owner(
        self,
    ) -> None:
        entry_point = _MetadataEntryPoint("acme.sample@1.0.0")
        distribution = _MetadataDistribution(self._distribution, entry_point)
        with (
            patch.object(
                distribution_module.metadata,
                "entry_points",
                return_value=(entry_point,),
            ),
            patch.object(
                distribution_module.metadata,
                "distributions",
                return_value=(distribution,),
            ),
        ):
            candidates = DistributionCapabilityPackageSource().discover_metadata()

        self.assertEqual(
            tuple(candidate.package_ref for candidate in candidates),
            (PACKAGE_REF,),
        )

    def test_distribution_source_ids_are_collision_resistant_identifiers(
        self,
    ) -> None:
        first = _MetadataDistribution(
            self._distribution,
            _MetadataEntryPoint("acme.sample@1.0.0"),
            name="Acme Capability Sample",
        )
        second = _MetadataDistribution(
            self._distribution,
            _MetadataEntryPoint("acme.sample@1.0.0"),
            name="acme-capability-sample",
        )

        candidates = DistributionCapabilityPackageSource(
            (cast(metadata.Distribution, first), cast(metadata.Distribution, second))
        ).discover_metadata()

        self.assertEqual(len(candidates), 2)
        source_ids = tuple(candidate.source_id for candidate in candidates)
        self.assertEqual(len(set(source_ids)), 2)
        self.assertTrue(
            all(IDENTIFIER.fullmatch(source_id) is not None for source_id in source_ids)
        )

    def test_opening_selected_payload_does_not_import_provider(self) -> None:
        source = self._source()
        candidate = source.discover_metadata()[0]
        with patch.dict(
            os.environ,
            {"ASTERION_TEST_FORBID_PROVIDER_IMPORT": "1"},
            clear=False,
        ):
            payload = source.open_payload(candidate)

        self.assertEqual(payload.manifest.package_ref, PACKAGE_REF)
        self.assertNotIn(PROVIDER_MODULE, sys.modules)

    def test_selected_provider_load_binds_candidate_and_validated_payload(
        self,
    ) -> None:
        source = self._source()
        candidate = source.discover_metadata()[0]
        payload = source.open_payload(candidate)

        with _target_on_path(self._target):
            installed = source.load_provider(candidate)

        self.assertEqual(installed.package_ref, candidate.package_ref)
        self.assertEqual(installed.payload_sha256, payload.payload_sha256)
        self.assertEqual(installed.source_id, candidate.source_id)
        self.assertEqual(installed.source_kind, "python-distribution")

    def test_provider_identity_mismatches_fail_closed(self) -> None:
        for mismatch in ("package", "payload", "source", "source-id"):
            with self.subTest(mismatch=mismatch):
                sys.modules.pop(PROVIDER_MODULE, None)
                source = self._source()
                candidate = source.discover_metadata()[0]
                with (
                    _target_on_path(self._target),
                    patch.dict(
                        os.environ,
                        {"ASTERION_TEST_PROVIDER_IDENTITY_MISMATCH": mismatch},
                        clear=False,
                    ),
                    self.assertRaises(DistributionCapabilitySourceError),
                ):
                    source.load_provider(candidate)

    def test_duplicate_entry_point_names_fail_before_any_provider_import(self) -> None:
        duplicate = _DuplicateDistribution(self._distribution)
        source = DistributionCapabilityPackageSource(
            (cast(metadata.Distribution, duplicate),)
        )
        candidate = source.discover_metadata()[0]

        with self.assertRaises(DistributionCapabilitySourceError):
            source.load_provider(candidate)

        self.assertEqual(tuple(entry.loads for entry in duplicate.entry_points), (0, 0))

    def test_malformed_entry_point_name_fails_before_any_provider_import(
        self,
    ) -> None:
        entry_point = _MalformedEntryPoint()
        source = DistributionCapabilityPackageSource(
            (
                cast(
                    metadata.Distribution,
                    _MalformedDistribution(self._distribution, entry_point),
                ),
            )
        )
        candidate = CapabilityPackageCandidate(
            package_ref=PACKAGE_REF,
            source_id=(
                "python-distribution.acme-capability-sample.1-0-0.acme.sample.1.0.0.sha-cff21202bedd"
            ),
            source_kind="python-distribution",
            payload_sha256=None,
            metadata={
                "distribution_name": "acme-capability-sample",
                "distribution_version": "1.0.0",
            },
        )

        with patch.dict(
            os.environ,
            {"ASTERION_TEST_FORBID_PROVIDER_IMPORT": "1"},
            clear=False,
        ):
            for operation in (
                source.discover_metadata,
                lambda: source.open_payload(candidate),
                lambda: source.load_provider(candidate),
            ):
                with (
                    self.subTest(operation=operation),
                    self.assertRaises(DistributionCapabilitySourceError),
                ):
                    operation()

        self.assertEqual(entry_point.loads, 0)
        self.assertNotIn(PROVIDER_MODULE, sys.modules)


class _target_on_path:
    def __init__(self, target: Path) -> None:
        self._target = str(target)

    def __enter__(self) -> None:
        sys.path.insert(0, self._target)

    def __exit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback
        sys.path.remove(self._target)


if __name__ == "__main__":
    unittest.main()
