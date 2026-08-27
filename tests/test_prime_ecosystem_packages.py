from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from typing import Any

from asterion.capability_packages import (
    CapabilityPackageRef,
    CapabilitySourceDeclaration,
    CapabilitySourceLock,
    CapabilitySourceLockEntry,
    open_portable_payload,
)
from asterion.capability_packages.model import CapabilityPackageCandidate
from asterion.capability_packages.resolution import (
    CapabilitySourceResolutionError,
    resolve_capability_source,
)
from asterion.capability_packages.sources.distribution import (
    DistributionCapabilityPackageSource,
    ENTRY_POINT_GROUP,
)
from asterion.capability_packages.sources.local import (
    LocalDirectoryCapabilityPackageSource,
    LocalDirectoryCapabilitySourceError,
)
from asterion.control.ecosystem import (
    EcosystemPrivateFile,
    EcosystemPrivateResource,
    EcosystemResourceRef,
    EcosystemSourceRef,
    build_ecosystem_portfolio,
)
from asterion.control.ecosystem_materialization import (
    FileEcosystemPrivateSourceStore,
    SealedEcosystemMaterializer,
)
from tests.test_prime_ecosystem_real_process import (
    MODULE_LOCK,
    PINNED_SOURCE,
    REAL_HARNESS,
    _closed_environment,
    _node_22,
)
from tests.test_prime_ecosystem_resources import _committed_artifact_lock
from tools.setup_prime_agent import resolve_prime_ecosystem_module


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests/fixtures/prime_ecosystem/v1/packages/exact-package"
PAYLOAD_ROOT = FIXTURE_ROOT / "payload"
PACKAGE_REF = CapabilityPackageRef("ecosystem.sample", "1.0.0")
LOCAL_SOURCE_ID = "ecosystem.sample.local-directory"
DISTRIBUTION_SOURCE_ID = "ecosystem.sample.python-distribution"
SCENARIO_PACKAGE = "packages"
FEATURE_IDS = ["ecosystem.packages"]
ASSERTION_IDS = [
    "packages.no-install",
    "packages.no-source-fallback",
    "packages.prime-package-manager",
    "packages.selected-source-digest",
]
PUBLIC_KEYS = {
    "assertion_ids",
    "feature_ids",
    "format",
    "model_credential_reads",
    "observation_digest",
    "owned_process_count_after_close",
    "package_count",
    "provider_operations",
    "resource_count",
    "scenario_package",
    "selected_source_digest",
    "status",
}
BODY_SENTINELS = (
    "PACKAGE_BODY_SENTINEL",
    "provider imported during package metadata discovery",
    "REMOTE_PACKAGE_SENTINEL",
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_digest(value: object) -> str:
    return _sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def _copy_fixture(target: Path) -> Path:
    root = target.parent.resolve() / target.name
    shutil.copytree(FIXTURE_ROOT, root)
    return root


def _local_declaration(root: Path, *, payload_sha256: str | None = None) -> CapabilitySourceDeclaration:
    payload_digest = payload_sha256
    if payload_digest is None:
        payload_digest = open_portable_payload(root / "payload").payload_sha256
    return CapabilitySourceDeclaration(
        source_id=LOCAL_SOURCE_ID,
        kind="local-directory",
        package_ref=PACKAGE_REF,
        payload_sha256=payload_digest,
        private_locator={
            "root": root,
            "payload_root": "payload",
            "module_path": "provider.py",
            "factory_name": "create_package",
        },
    )


class _FakeEntryPoint:
    group = ENTRY_POINT_GROUP
    value = "private.module:create"

    def __init__(self) -> None:
        self.name = f"{PACKAGE_REF.package_id}@{PACKAGE_REF.version}"
        self.loaded = False

    def load(self) -> object:
        self.loaded = True
        raise RuntimeError("REMOTE_PACKAGE_SENTINEL")


class _FakePackagePath:
    def __init__(self, relative_path: str, located_path: Path) -> None:
        self._relative_path = relative_path
        self._located_path = located_path

    def __str__(self) -> str:
        return self._relative_path

    def locate(self) -> Path:
        return self._located_path


class _FakeDistribution:
    name = "asterion-ecosystem-sample"
    version = "1.0.0"
    metadata = {"Name": "asterion-ecosystem-sample"}

    def __init__(self, base: Path, entry: _FakeEntryPoint) -> None:
        self._base = base
        self.entry_points = (entry,)
        descriptor = (
            "asterion_capability_packages/"
            f"{PACKAGE_REF.package_id}/{PACKAGE_REF.version}/payload/"
            "capability-package.json"
        )
        self.files = (
            _FakePackagePath(descriptor, base / descriptor),
        )

    def locate_file(self, path: object) -> Path:
        if str(path) in {"", "."}:
            return self._base
        return self._base / PurePosixPath(str(path))


def _install_fake_distribution(base: Path) -> tuple[_FakeDistribution, _FakeEntryPoint]:
    payload_target = (
        base
        / "asterion_capability_packages"
        / PACKAGE_REF.package_id
        / PACKAGE_REF.version
        / "payload"
    )
    shutil.copytree(PAYLOAD_ROOT, payload_target)
    entry = _FakeEntryPoint()
    return _FakeDistribution(base, entry), entry


def _selected_local_payload(root: Path) -> tuple[CapabilityPackageCandidate, str, _FakeEntryPoint]:
    payload_digest = open_portable_payload(root / "payload").payload_sha256
    with tempfile.TemporaryDirectory(prefix="asterion-package-dist-", dir="/tmp") as dist_dir:
        distribution, entry = _install_fake_distribution(Path(dist_dir).resolve())
        local_source = LocalDirectoryCapabilityPackageSource((_local_declaration(root, payload_sha256=payload_digest),))
        distribution_source = DistributionCapabilityPackageSource((distribution,))  # type: ignore[arg-type]
        previous = os.environ.get("ASTERION_TEST_FORBID_PROVIDER_IMPORT")
        os.environ["ASTERION_TEST_FORBID_PROVIDER_IMPORT"] = "1"
        try:
            candidates = (
                *local_source.discover_metadata(),
                *distribution_source.discover_metadata(),
            )
        finally:
            if previous is None:
                os.environ.pop("ASTERION_TEST_FORBID_PROVIDER_IMPORT", None)
            else:
                os.environ["ASTERION_TEST_FORBID_PROVIDER_IMPORT"] = previous
        selected = resolve_capability_source(
            PACKAGE_REF,
            candidates,
            CapabilitySourceLock(
                (
                    CapabilitySourceLockEntry(
                        PACKAGE_REF,
                        payload_digest,
                        LOCAL_SOURCE_ID,
                    ),
                )
            ),
        )
        local_source.open_payload(selected)
        if selected.source_id != LOCAL_SOURCE_ID or entry.loaded:
            raise AssertionError("exact package source selection failed")
        return selected, payload_digest, entry


def _private_resource(payload_root: Path) -> EcosystemPrivateResource:
    files: list[EcosystemPrivateFile] = []
    for path in sorted(item for item in payload_root.rglob("*") if item.is_file()):
        body = path.read_bytes()
        files.append(
            EcosystemPrivateFile(
                path.relative_to(payload_root).as_posix(),
                _sha256(body),
                len(body),
            )
        )
    return EcosystemPrivateResource(
        "exact-package",
        LOCAL_SOURCE_ID,
        tuple(files),
    )


def _portfolio_for(private: EcosystemPrivateResource, selected: CapabilityPackageCandidate):
    files = [
        {
            "relative_path": item.relative_path,
            "sha256": item.sha256,
            "size_bytes": item.size_bytes,
        }
        for item in private.files
    ]
    source_kind = (
        "local-child"
        if selected.source_kind == "local-directory"
        else "installed-distribution"
    )
    resource = EcosystemResourceRef(
        private.resource_id,
        selected.package_ref.version,
        "package",
        "project",
        EcosystemSourceRef(
            selected.source_id,
            source_kind,
            selected.package_ref.version,
            _canonical_digest(
                {
                    "package_id": selected.package_ref.package_id,
                    "payload_sha256": selected.payload_sha256,
                    "source_id": selected.source_id,
                    "source_kind": selected.source_kind,
                    "version": selected.package_ref.version,
                }
            ),
        ),
        _canonical_digest(files),
    )
    return build_ecosystem_portfolio(
        portfolio_id="portfolio-packages",
        authority_id="authority-packages",
        authority_revision=1,
        resources=(resource,),
        registrations=(),
    )


def _command_with_artifact_lock(
    node: Path,
    sealed_root: Path,
    artifact_lock: Path,
) -> tuple[str, ...]:
    return (
        str(node),
        str(REAL_HARNESS),
        "--module-lock",
        str(MODULE_LOCK),
        "--artifact-lock",
        str(artifact_lock),
        "--sealed-root",
        str(sealed_root),
        "--scenario-package",
        SCENARIO_PACKAGE,
    )


def _run_package_harness(node: Path, *, source_root: Path = FIXTURE_ROOT) -> tuple[int, dict[str, object] | None, str]:
    selected, _payload_digest, _entry = _selected_local_payload(source_root)
    private_resource = _private_resource(source_root / "payload")
    portfolio = _portfolio_for(private_resource, selected)
    with tempfile.TemporaryDirectory(prefix="asterion-prime-ecosystem-packages-", dir="/tmp") as temporary:
        parent = Path(temporary).resolve()
        parent.chmod(0o700)
        artifact_lock = parent / "prime-artifact-lock.json"
        artifact_lock.write_bytes(_committed_artifact_lock())
        artifact_lock.chmod(0o600)
        resolved = resolve_prime_ecosystem_module(
            PINNED_SOURCE,
            MODULE_LOCK,
            artifact_lock_path=artifact_lock,
        )
        if resolved.bundle_path.name != "prime-ecosystem-module.mjs":
            raise AssertionError("real Prime ecosystem package harness failed")
        private_home = parent / "home"
        private_home.mkdir(mode=0o700)
        materializer = SealedEcosystemMaterializer(parent / "sealed")
        store = FileEcosystemPrivateSourceStore(
            roots={private_resource.source_id: (source_root / "payload").resolve()},
            resources=(private_resource,),
        )
        projection = materializer.materialize(portfolio, store)
        try:
            completed = subprocess.run(
                _command_with_artifact_lock(node, projection.root, artifact_lock),
                cwd=ROOT,
                env=_closed_environment(private_home),
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        finally:
            materializer.close(projection)
    report = None
    if completed.stdout:
        try:
            value = json.loads(completed.stdout)
        except json.JSONDecodeError:
            value = None
        if isinstance(value, dict):
            report = value
    if str(source_root) in completed.stdout or str(source_root) in completed.stderr:
        raise AssertionError("real Prime ecosystem package harness leaked a source path")
    return completed.returncode, report, completed.stdout + completed.stderr


@unittest.skipUnless(
    PINNED_SOURCE.is_dir(), "external pinned Prime ecosystem source is unavailable"
)
class TestPrimeEcosystemPackages(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.node = _node_22()
        if cls.node is None:
            raise unittest.SkipTest("an offline pinned Node 22 executable is unavailable")

    def test_exact_source_lock_selects_package_without_import_or_fallback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="asterion-package-source-", dir="/tmp") as temporary:
            root = _copy_fixture(Path(temporary) / "local")
            selected, payload_digest, entry = _selected_local_payload(root)

        self.assertEqual(selected.source_id, LOCAL_SOURCE_ID)
        self.assertEqual(selected.payload_sha256, payload_digest)
        self.assertFalse(entry.loaded)

    def test_source_selection_rejects_ambiguous_missing_drift_and_ranges(self) -> None:
        payload_digest = open_portable_payload(PAYLOAD_ROOT).payload_sha256
        local_candidate = CapabilityPackageCandidate(
            PACKAGE_REF,
            LOCAL_SOURCE_ID,
            "local-directory",
            payload_digest,
            {},
        )
        distribution_candidate = CapabilityPackageCandidate(
            PACKAGE_REF,
            DISTRIBUTION_SOURCE_ID,
            "python-distribution",
            payload_digest,
            {},
        )
        cases = {
            "ambiguous-without-lock": (None, (local_candidate, distribution_candidate)),
            "missing-source": (
                CapabilitySourceLock((CapabilitySourceLockEntry(PACKAGE_REF, payload_digest, "missing.source"),)),
                (local_candidate, distribution_candidate),
            ),
            "digest-drift": (
                CapabilitySourceLock((CapabilitySourceLockEntry(PACKAGE_REF, "f" * 64, LOCAL_SOURCE_ID),)),
                (local_candidate, distribution_candidate),
            ),
            "duplicate-selected": (
                CapabilitySourceLock((CapabilitySourceLockEntry(PACKAGE_REF, payload_digest, LOCAL_SOURCE_ID),)),
                (local_candidate, local_candidate),
            ),
        }
        for name, (lock, candidates) in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(CapabilitySourceResolutionError):
                    resolve_capability_source(PACKAGE_REF, candidates, lock)
        with self.assertRaises(CapabilitySourceResolutionError):
            resolve_capability_source(
                PACKAGE_REF,
                (local_candidate,),
                CapabilitySourceLock(
                    (
                        CapabilitySourceLockEntry(
                            CapabilityPackageRef(PACKAGE_REF.package_id, "1.x"),
                            payload_digest,
                            LOCAL_SOURCE_ID,
                        ),
                    )
                ),
            )

    def test_local_source_rejects_remote_symlink_and_undeclared_payload_redacted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="asterion-package-invalid-", dir="/tmp") as temporary:
            base = Path(temporary).resolve()
            valid = _copy_fixture(base / "valid")
            payload_digest = open_portable_payload(valid / "payload").payload_sha256
            root_symlink = base / "root-link"
            root_symlink.symlink_to(valid, target_is_directory=True)
            extra = _copy_fixture(base / "extra")
            (extra / "payload" / "resources" / "undeclared.json").write_text(
                "{\"value\":\"PACKAGE_BODY_SENTINEL\"}\n",
                encoding="utf-8",
            )
            cases = (
                _local_declaration(
                    valid,
                    payload_sha256=payload_digest,
                ),
                CapabilitySourceDeclaration(
                    source_id=LOCAL_SOURCE_ID,
                    kind="local-directory",
                    package_ref=PACKAGE_REF,
                    payload_sha256=payload_digest,
                    private_locator={
                        "root": "https://REMOTE_PACKAGE_SENTINEL.invalid/pkg",
                        "payload_root": "payload",
                        "module_path": "provider.py",
                        "factory_name": "create_package",
                    },
                ),
                _local_declaration(root_symlink, payload_sha256=payload_digest),
                _local_declaration(extra, payload_sha256=payload_digest),
            )
            for declaration in cases[1:]:
                with self.subTest(locator=repr(declaration.public_projection)):
                    source = LocalDirectoryCapabilityPackageSource((declaration,))
                    with self.assertRaises(LocalDirectoryCapabilitySourceError) as raised:
                        source.discover_metadata()
                    rendered = repr(raised.exception)
                    for sentinel in BODY_SENTINELS:
                        self.assertNotIn(sentinel, rendered)

    def test_real_prime_package_receipt_is_safe_exact_and_deterministic(self) -> None:
        first_code, first, first_output = _run_package_harness(self.node)
        second_code, second, second_output = _run_package_harness(self.node)

        self.assertEqual(first_code, 0)
        self.assertEqual(second_code, 0)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None
        assert second is not None
        self.assertEqual(set(first), PUBLIC_KEYS)
        self.assertEqual(first["format"], "asterion.prime-ecosystem-observation/v1")
        self.assertEqual(first["scenario_package"], SCENARIO_PACKAGE)
        self.assertEqual(first["status"], "PASS")
        self.assertEqual(first["feature_ids"], FEATURE_IDS)
        self.assertEqual(first["assertion_ids"], ASSERTION_IDS)
        self.assertEqual(first["package_count"], 1)
        self.assertEqual(first["resource_count"], 1)
        self.assertEqual(first["provider_operations"], 0)
        self.assertEqual(first["model_credential_reads"], 0)
        self.assertEqual(first["owned_process_count_after_close"], 0)
        self.assertEqual(first["observation_digest"], second["observation_digest"])
        self.assertEqual(
            first_output,
            json.dumps(first, sort_keys=True, separators=(",", ":")) + "\n",
        )
        for output in (first_output, second_output):
            for sentinel in BODY_SENTINELS:
                self.assertNotIn(sentinel, output)


if __name__ == "__main__":
    unittest.main()
