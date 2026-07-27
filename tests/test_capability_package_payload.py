from __future__ import annotations

import gc
import hashlib
import json
import os
import shutil
import stat
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import asterion.capability_packages.payload as payload_module
from asterion.capabilities.catalog import CapabilityRef
from asterion.capability_packages.payload import (
    CapabilityPackagePayloadError,
    canonical_payload_sha256,
    open_portable_payload,
)
from asterion.capability_packages.protocol import (
    BenchmarkSuiteRef,
    CapabilityPackageRef,
    ResourceIdentity,
)


FIXTURE = (
    Path(__file__).parent / "fixtures/extensions/minimal/payload"
)
IDENTITY_MEMBERS = (
    "benchmark-suites/example-benchmark.json",
    "capability-package.json",
    "capabilities/example-research.json",
    "conformance/profile.json",
    "resources/public-config.txt",
)


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _write_canonical_json(path: Path, value: object) -> None:
    path.write_bytes(_canonical_json(value))


def _read_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    assert isinstance(value, dict)
    return value


class CapabilityPackagePayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self._copy_payload("payload")

    def _copy_payload(self, name: str) -> Path:
        target = self.base / name
        shutil.copytree(FIXTURE, target)
        return target

    def _direct_snapshot_files(self, root: Path) -> tuple[str, ...]:
        observed: list[str] = []
        for member in root.iterdir():
            if member.is_file():
                observed.append(member.name)
                continue
            self.assertTrue(member.is_dir())
            for child in member.iterdir():
                self.assertTrue(child.is_file())
                observed.append(f"{member.name}/{child.name}")
        return tuple(sorted(observed))

    def test_opens_exact_payload_and_derives_canonical_identity(self) -> None:
        payload = open_portable_payload(self.root)
        snapshot_root = Path(payload.resource_root)

        self.assertEqual(
            payload.manifest.package_ref,
            CapabilityPackageRef("example.package", "1.0.0"),
        )
        self.assertEqual(
            payload.manifest.capabilities,
            (CapabilityRef("example.research", "1.0.0"),),
        )
        self.assertEqual(
            payload.manifest.resources,
            (
                ResourceIdentity(
                    "example.public-config",
                    "text/plain",
                    (
                        "acc3e410bd74fb3717a1d4e8f8d47c2c36c1181d"
                        "05af98aa702f1be8732672c5"
                    ),
                ),
            ),
        )
        self.assertEqual(
            payload.manifest.benchmark_suites,
            (BenchmarkSuiteRef("example.benchmark", "1.0.0"),),
        )
        expected = hashlib.sha256()
        for relative_name in sorted(IDENTITY_MEMBERS):
            content = (self.root / relative_name).read_bytes()
            entry = (
                relative_name.encode("utf-8")
                + b"\0"
                + hashlib.sha256(content).digest()
            )
            expected.update(len(entry).to_bytes(8, "big"))
            expected.update(entry)
        self.assertEqual(payload.payload_sha256, expected.hexdigest())
        self.assertEqual(
            canonical_payload_sha256(self.root, payload.manifest),
            payload.payload_sha256,
        )
        self.assertNotEqual(snapshot_root, self.root)
        self.assertEqual(
            self._direct_snapshot_files(snapshot_root),
            tuple(sorted(IDENTITY_MEMBERS)),
        )
        for relative_name in IDENTITY_MEMBERS:
            with self.subTest(snapshot_member=relative_name):
                snapshot_member = snapshot_root / relative_name
                self.assertEqual(
                    snapshot_member.read_bytes(),
                    (self.root / relative_name).read_bytes(),
                )
                self.assertEqual(
                    stat.S_IMODE(snapshot_member.stat().st_mode),
                    0o600,
                )
        for directory_name in {
            Path(relative_name).parts[0]
            for relative_name in IDENTITY_MEMBERS
            if len(Path(relative_name).parts) == 2
        }:
            with self.subTest(snapshot_directory=directory_name):
                self.assertEqual(
                    stat.S_IMODE(
                        (snapshot_root / directory_name).stat().st_mode
                    ),
                    0o700,
                )
        self.assertEqual(
            stat.S_IMODE(snapshot_root.stat().st_mode),
            0o700,
        )
        self.assertNotIn(str(self.root), repr(payload))
        self.assertNotIn(str(snapshot_root), repr(payload))

    def test_source_mutation_cannot_change_materialized_snapshot(self) -> None:
        payload = open_portable_payload(self.root)
        snapshot_root = Path(payload.resource_root)
        original_resource = (
            snapshot_root / "resources/public-config.txt"
        ).read_bytes()

        (self.root / "resources/public-config.txt").write_text(
            "changed after validation\n",
            encoding="utf-8",
        )
        (self.root / "resources/late-member.txt").write_text(
            "added after validation\n",
            encoding="utf-8",
        )

        self.assertEqual(
            (snapshot_root / "resources/public-config.txt").read_bytes(),
            original_resource,
        )
        self.assertEqual(
            self._direct_snapshot_files(snapshot_root),
            tuple(sorted(IDENTITY_MEMBERS)),
        )

    def test_payload_owns_materialized_snapshot_lifetime(self) -> None:
        payload = open_portable_payload(self.root)
        snapshot_root = Path(payload.resource_root)
        self.assertTrue(snapshot_root.is_dir())

        del payload
        gc.collect()

        self.assertFalse(snapshot_root.exists())


    def test_digest_is_independent_of_location_mtime_and_source_envelope(
        self,
    ) -> None:
        payload = open_portable_payload(self.root)
        copied = self._copy_payload("elsewhere")
        for index, relative_name in enumerate(IDENTITY_MEMBERS, start=1):
            os.utime(copied / relative_name, (index, index))
        (self.base / "capability-source.json").write_text(
            "different private source envelope\n",
            encoding="utf-8",
        )
        wheel_metadata = self.base / "extension.dist-info"
        wheel_metadata.mkdir()
        (wheel_metadata / "RECORD").write_text(
            "container metadata differs\n",
            encoding="utf-8",
        )
        (self.base / "operator-config.json").write_text(
            "private operator configuration differs\n",
            encoding="utf-8",
        )

        copied_payload = open_portable_payload(copied)

        self.assertEqual(copied_payload.payload_sha256, payload.payload_sha256)

    def test_rejects_invalid_payload_closure(self) -> None:
        def missing_declared_member(root: Path) -> None:
            (root / "capabilities/example-research.json").unlink()

        def extra_identity_bearing_member(root: Path) -> None:
            _write_canonical_json(
                root / "capabilities/extra.json",
                {
                    "protocol": "asterion.capability/v1",
                    "capability_id": "example.extra",
                    "version": "1.0.0",
                    "kind": "capability",
                    "provides_capabilities": [],
                    "requires_capabilities": [],
                    "requires_policies": [],
                    "emits_events": [],
                    "consumes_events": [],
                    "produces_artifacts": [],
                    "consumes_artifacts": [],
                },
            )

        def child_path_escape(root: Path) -> None:
            descriptor = _read_object(root / "capability-package.json")
            resources = descriptor["resources"]
            assert isinstance(resources, list)
            resource = resources[0]
            assert isinstance(resource, dict)
            resource["resource_id"] = "../outside"
            _write_canonical_json(root / "capability-package.json", descriptor)

        def resource_digest_mismatch(root: Path) -> None:
            (root / "resources/public-config.txt").write_text(
                "changed public configuration\n",
                encoding="utf-8",
            )

        def non_regular_file(root: Path) -> None:
            resource = root / "resources/public-config.txt"
            resource.unlink()
            os.mkfifo(resource)

        def noncanonical_json(root: Path) -> None:
            document = root / "capabilities/example-research.json"
            document.write_text(
                json.dumps(
                    _read_object(document),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

        cases: tuple[tuple[str, Callable[[Path], None]], ...] = (
            ("missing declared member", missing_declared_member),
            ("extra identity-bearing member", extra_identity_bearing_member),
            ("child path escape", child_path_escape),
            ("resource digest mismatch", resource_digest_mismatch),
            ("non-regular file", non_regular_file),
            ("noncanonical JSON", noncanonical_json),
        )

        for index, (label, mutate) in enumerate(cases):
            with self.subTest(label=label):
                root = self._copy_payload(f"invalid-{index}")
                mutate(root)
                with self.assertRaises(CapabilityPackagePayloadError):
                    open_portable_payload(root)

    def test_rejects_symlinked_root_and_child(self) -> None:
        external = self._copy_payload("external")
        linked_root = self.base / "linked-root"
        linked_root.symlink_to(external, target_is_directory=True)

        external_resource = self.base / "external-resource.txt"
        external_resource.write_text(
            "public configuration\n",
            encoding="utf-8",
        )
        linked_child_root = self._copy_payload("linked-child")
        child = linked_child_root / "resources/public-config.txt"
        child.unlink()
        child.symlink_to(external_resource)

        for label, root in (
            ("symlinked root", linked_root),
            ("symlinked child", linked_child_root),
        ):
            with (
                self.subTest(label=label),
                self.assertRaises(CapabilityPackagePayloadError),
            ):
                open_portable_payload(root)

    def test_rejects_authority_fields_without_disclosing_their_values(
        self,
    ) -> None:
        for index, field in enumerate(("provider", "command")):
            with self.subTest(field=field):
                root = self._copy_payload(f"authority-{index}")
                descriptor = _read_object(
                    root / "capability-package.json"
                )
                sentinel = f"SENTINEL-{field}-authority"
                descriptor[field] = sentinel
                _write_canonical_json(
                    root / "capability-package.json",
                    descriptor,
                )

                with self.assertRaises(
                    CapabilityPackagePayloadError
                ) as caught:
                    open_portable_payload(root)

                self.assertNotIn(sentinel, str(caught.exception))

    def test_rejects_members_added_after_initial_directory_enumeration(
        self,
    ) -> None:
        cases = (
            ("root", Path("."), "late-member"),
            (
                "benchmark-suites",
                Path("benchmark-suites"),
                "late-member.json",
            ),
            ("capabilities", Path("capabilities"), "late-member.json"),
            ("resources", Path("resources"), "late-member.txt"),
            ("conformance", Path("conformance"), "late-member.json"),
        )
        original_listdir = os.listdir

        for index, (label, relative_directory, member_name) in enumerate(
            cases
        ):
            with self.subTest(directory=label):
                root = self._copy_payload(f"late-member-{index}")
                directory = root / relative_directory
                directory_details = directory.stat()
                directory_identity = (
                    directory_details.st_dev,
                    directory_details.st_ino,
                )
                injected = False
                sentinel = f"SENTINEL-late-{label}"

                def inject_after_list(
                    directory_fd: int,
                ) -> list[str]:
                    nonlocal injected
                    members = original_listdir(directory_fd)
                    opened = os.fstat(directory_fd)
                    if (
                        not injected
                        and (opened.st_dev, opened.st_ino)
                        == directory_identity
                    ):
                        (directory / member_name).write_text(
                            sentinel,
                            encoding="utf-8",
                        )
                        injected = True
                    return members

                with (
                    patch.object(
                        payload_module.os,
                        "listdir",
                        side_effect=inject_after_list,
                    ),
                    self.assertRaises(
                        CapabilityPackagePayloadError
                    ) as caught,
                ):
                    open_portable_payload(root)

                self.assertTrue(injected)
                self.assertNotIn(sentinel, str(caught.exception))

    def test_rejects_directory_fingerprint_change_after_enumeration(
        self,
    ) -> None:
        root = self._copy_payload("directory-fingerprint-race")
        target = root / "resources"
        target_details = target.stat()
        target_identity = (target_details.st_dev, target_details.st_ino)
        original_listdir = os.listdir
        injected = False

        def change_timestamp_after_list(directory_fd: int) -> list[str]:
            nonlocal injected
            members = original_listdir(directory_fd)
            opened = os.fstat(directory_fd)
            if (
                not injected
                and (opened.st_dev, opened.st_ino) == target_identity
            ):
                os.utime(
                    target,
                    ns=(
                        target_details.st_atime_ns,
                        target_details.st_mtime_ns + 1_000_000_000,
                    ),
                )
                injected = True
            return members

        with (
            patch.object(
                payload_module.os,
                "listdir",
                side_effect=change_timestamp_after_list,
            ),
            self.assertRaises(CapabilityPackagePayloadError),
        ):
            open_portable_payload(root)

        self.assertTrue(injected)

    def test_rejects_regular_file_changed_after_its_initial_read(
        self,
    ) -> None:
        root = self._copy_payload("post-read-file-race")
        resource = root / "resources/public-config.txt"
        resource_details = resource.parent.stat()
        resource_parent_identity = (
            resource_details.st_dev,
            resource_details.st_ino,
        )
        original_read_regular = payload_module._read_regular
        injected = False
        sentinel = "SENTINEL-post-read-resource"

        def mutate_after_read(
            parent_fd: int,
            name: str,
            *,
            pinned_files: list[object],
        ) -> bytes:
            nonlocal injected
            content = original_read_regular(
                parent_fd,
                name,
                pinned_files=pinned_files,
            )
            opened_parent = os.fstat(parent_fd)
            if (
                not injected
                and name == resource.name
                and (opened_parent.st_dev, opened_parent.st_ino)
                == resource_parent_identity
            ):
                resource.write_text(sentinel, encoding="utf-8")
                injected = True
            return content

        with (
            patch.object(
                payload_module,
                "_read_regular",
                side_effect=mutate_after_read,
            ),
            self.assertRaises(CapabilityPackagePayloadError) as caught,
        ):
            open_portable_payload(root)

        self.assertTrue(injected)
        self.assertNotIn(sentinel, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
