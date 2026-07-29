from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import asterion.capability_packages.payload as capability_payload
from asterion.capabilities.catalog import CapabilityRef
from asterion.capability_packages.model import PortableCapabilityPayload
from asterion.capability_packages.payload import (
    CapabilityPackagePayloadError,
    canonical_payload_sha256,
    open_portable_payload,
)
from asterion.capability_packages.protocol import (
    BenchmarkSuiteRef,
    CapabilityPackageManifest,
    CapabilityPackageRef,
    ResourceIdentity,
    validate_capability_package_manifest,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "extensions" / "minimal" / "payload"
DCI_PAYLOAD_ROOT = (
    Path(__file__).resolve().parents[1]
    / "src/asterion/capabilities/dci/payload"
)


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _write_canonical_json(path: Path, value: object) -> None:
    path.write_bytes(_canonical_json(value))


def _resource_bytes() -> bytes:
    return b'{"case_id":"example.case","expected":"ok"}\n'


def _resource_digest() -> str:
    return hashlib.sha256(_resource_bytes()).hexdigest()


def _conformance_bytes() -> bytes:
    return b'{"case_ids":["example.case"],"profile_id":"example.conformance"}\n'


def _conformance_digest() -> str:
    return hashlib.sha256(_conformance_bytes()).hexdigest()


def _capability_manifest(capability_id: str = "example.research") -> dict[str, object]:
    return {
        "protocol": "asterion.capability/v1",
        "capability_id": capability_id,
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


def _suite_manifest(suite_id: str = "example.suite") -> dict[str, object]:
    return {
        "protocol": "asterion.benchmark-suite/v1",
        "suite_id": suite_id,
        "version": "1.0.0",
        "owner_package": {"package_id": "example.package", "version": "1.0.0"},
        "tasks": [
            {
                "task_id": "example.task",
                "capability": {"capability_id": "example.research", "version": "1.0.0"},
                "binding_id": "example.task",
                "metric_contract_id": "example.metric/v1",
                "result_contract_id": "example.result/v1",
                "note": "",
            }
        ],
        "artifact_media_types": ["application/json"],
        "default_case_limit": 1,
        "default_concurrency": 1,
    }


def _package_manifest(
    *,
    capabilities: list[dict[str, str]] | None = None,
    suites: list[dict[str, str]] | None = None,
    resources: list[dict[str, str]] | None = None,
    conformance: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "protocol": "asterion.capability-package/v1",
        "package_id": "example.package",
        "version": "1.0.0",
        "capabilities": capabilities
        if capabilities is not None
        else [{"capability_id": "example.research", "version": "1.0.0"}],
        "benchmark_suites": suites
        if suites is not None
        else [{"suite_id": "example.suite", "version": "1.0.0"}],
        "resources": resources
        if resources is not None
        else [
            {
                "resource_id": "example.conformance",
                "media_type": "application/json",
                "sha256": _resource_digest(),
            }
        ],
        "conformance": conformance
        if conformance is not None
        else [
            {
                "resource_id": "externalization.json",
                "media_type": "application/json",
                "sha256": _conformance_digest(),
            }
        ],
    }


def _create_payload(root: Path) -> None:
    (root / "capabilities").mkdir(parents=True)
    (root / "benchmark-suites").mkdir()
    (root / "resources").mkdir()
    (root / "conformance").mkdir()
    _write_canonical_json(root / "capability-package.json", _package_manifest())
    _write_canonical_json(
        root / "capabilities" / "research.json",
        _capability_manifest(),
    )
    _write_canonical_json(
        root / "benchmark-suites" / "suite.json",
        _suite_manifest(),
    )
    (root / "resources" / "example.conformance").write_bytes(_resource_bytes())
    _write_canonical_json(
        root / "conformance" / "externalization.json",
        {"case_ids": ["example.case"], "profile_id": "example.conformance"},
    )


def _file_identity(path: Path) -> tuple[int, int]:
    details = path.stat()
    return details.st_dev, details.st_ino


def _fd_identity(fd: int) -> tuple[int, int]:
    details = os.fstat(fd)
    return details.st_dev, details.st_ino


def _assert_body_free(
    test_case: unittest.TestCase,
    error: BaseException,
    sentinels: tuple[str, ...],
) -> None:
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


class CapabilityPackagePayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name).resolve() / "payload"
        _create_payload(self.root)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_fixture_payload_opens_as_deeply_immutable_model_value(self) -> None:
        payload = open_portable_payload(FIXTURE_ROOT)

        self.assertIsInstance(payload, PortableCapabilityPayload)
        self.assertEqual(
            payload.manifest,
            CapabilityPackageManifest(
                package_ref=CapabilityPackageRef("example.package", "1.0.0"),
                capabilities=(CapabilityRef("example.research", "1.0.0"),),
                benchmark_suites=(BenchmarkSuiteRef("example.suite", "1.0.0"),),
                resources=(
                    ResourceIdentity(
                        "example.conformance",
                        "application/json",
                        _resource_digest(),
                    ),
                ),
                conformance=(
                    ResourceIdentity(
                        "externalization.json",
                        "application/json",
                        _conformance_digest(),
                    ),
                ),
            ),
        )
        self.assertEqual(
            payload.payload_sha256,
            canonical_payload_sha256(FIXTURE_ROOT, payload.manifest),
        )
        self.assertNotIsInstance(payload.resource_root, Path)
        self.assertNotIn(str(FIXTURE_ROOT), repr(payload.resource_root))
        with self.assertRaises(AttributeError):
            setattr(payload.manifest, "resources", ())

    def test_payload_resource_root_is_a_deeply_immutable_snapshot(self) -> None:
        payload = open_portable_payload(self.root)
        capability_bytes = payload.resource_root.joinpath(
            "capabilities",
            "research.json",
        ).read_bytes()
        conformance_bytes = payload.resource_root.joinpath(
            "conformance",
            "externalization.json",
        ).read_bytes()
        shutil.rmtree(self.root)

        self.assertEqual(
            payload.resource_root.joinpath("capabilities", "research.json").read_bytes(),
            capability_bytes,
        )
        self.assertEqual(
            payload.resource_root.joinpath(
                "conformance",
                "externalization.json",
            ).read_bytes(),
            conformance_bytes,
        )
        self.assertNotIn(str(self.root), repr(payload.resource_root))

    def test_payload_digest_is_location_mtime_and_input_manifest_independent(self) -> None:
        payload = open_portable_payload(self.root)
        copied = self.root.parent / "copied" / "payload"
        shutil.copytree(self.root, copied)
        for child in copied.rglob("*"):
            os.utime(child, (1_700_000_000, 1_700_000_000), follow_symlinks=False)
        manifest = validate_capability_package_manifest(_package_manifest())

        self.assertEqual(open_portable_payload(copied).payload_sha256, payload.payload_sha256)
        self.assertEqual(canonical_payload_sha256(copied, manifest), payload.payload_sha256)

    def test_missing_empty_benchmark_suite_directory_matches_wheel_materialization(
        self,
    ) -> None:
        copied = self.root.parent / "wheel-like" / "payload"
        shutil.copytree(self.root, copied)
        descriptor_path = copied / "capability-package.json"
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        descriptor["benchmark_suites"] = []
        descriptor_path.write_bytes(_canonical_json(descriptor))
        for suite_path in (copied / "benchmark-suites").glob("*.json"):
            suite_path.unlink()
        source_payload = open_portable_payload(copied)
        (copied / "benchmark-suites").rmdir()

        materialized = open_portable_payload(copied)

        self.assertEqual(materialized.manifest.benchmark_suites, ())
        self.assertEqual(materialized.payload_sha256, source_payload.payload_sha256)

    def test_rejects_declared_closure_violations_with_body_free_errors(self) -> None:
        def add_nested_declared_child(root: Path) -> None:
            nested = root / "capabilities" / "nested"
            nested.mkdir()
            _write_canonical_json(nested / "research.json", _capability_manifest())

        cases = {
            "missing declared member": lambda root: (root / "capabilities" / "research.json").unlink(),
            "extra identity-bearing member": lambda root: _write_canonical_json(
                root / "capabilities" / "extra.json",
                _capability_manifest("example.extra"),
            ),
            "child path escape": add_nested_declared_child,
            "resource digest mismatch": lambda root: (
                root / "resources" / "example.conformance"
            ).write_bytes(b"SECRET-RESOURCE-BODY"),
            "missing declared conformance member": lambda root: (
                root / "conformance" / "externalization.json"
            ).unlink(),
            "extra identity-bearing conformance member": lambda root: _write_canonical_json(
                root / "conformance" / "extra.json",
                {"case_ids": ["example.case"], "profile_id": "example.extra"},
            ),
            "conformance digest mismatch": lambda root: (
                root / "conformance" / "externalization.json"
            ).write_text(
                '{"case_ids":["example.case"],"profile_id":"SECRET-CONFORMANCE"}\n',
                encoding="utf-8",
            ),
            "non-regular file": lambda root: (
                (root / "resources" / "example.conformance").unlink(),
                (root / "resources" / "example.conformance").mkdir(),
            ),
            "noncanonical JSON": lambda root: (root / "capability-package.json").write_text(
                json.dumps(_package_manifest(), indent=2),
                encoding="utf-8",
            ),
            "provider field in manifest": lambda root: _write_canonical_json(
                root / "capability-package.json",
                {**_package_manifest(), "provider": "SECRET-PROVIDER"},
            ),
            "command field in manifest": lambda root: _write_canonical_json(
                root / "capability-package.json",
                {**_package_manifest(), "command": "SECRET-COMMAND"},
            ),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                root = self.root.parent / name.replace(" ", "-")
                shutil.copytree(self.root, root)
                mutate(root)

                with self.assertRaises(CapabilityPackagePayloadError) as raised:
                    open_portable_payload(root)

                _assert_body_free(
                    self,
                    raised.exception,
                    (
                        str(root),
                        "research.json",
                        "extra.json",
                        "nested",
                        "SECRET-RESOURCE-BODY",
                        "SECRET-CONFORMANCE",
                        "SECRET-PROVIDER",
                        "SECRET-COMMAND",
                    ),
                )

    def test_rejects_nonfinite_json_constants_body_free(self) -> None:
        for constant in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(constant=constant):
                root = self.root.parent / f"nonfinite-{constant.lower()}"
                shutil.copytree(self.root, root)
                (root / "conformance" / "externalization.json").write_text(
                    f'{{"case_ids":["example.case"],"profile_id":{constant}}}\n',
                    encoding="utf-8",
                )

                with self.assertRaises(CapabilityPackagePayloadError) as raised:
                    open_portable_payload(root)

                _assert_body_free(self, raised.exception, (constant, str(root)))

    def test_rejects_symlinked_roots_and_children_without_following_them(self) -> None:
        external_root = self.root.parent / "external"
        _create_payload(external_root)
        external_resource = external_root / "resources" / "example.conformance"
        external_resource.write_bytes(b"SECRET-EXTERNAL-BODY")
        cases = {
            "symlinked root": lambda root: (
                shutil.rmtree(root),
                root.symlink_to(external_root, target_is_directory=True),
            ),
            "symlinked intermediate root component": lambda root: (
                shutil.rmtree(root.parent),
                (root.parent.parent / "real-parent").mkdir(),
                shutil.copytree(self.root, root.parent.parent / "real-parent" / "payload"),
                root.parent.symlink_to(
                    root.parent.parent / "real-parent",
                    target_is_directory=True,
                ),
            ),
            "symlinked child": lambda root: (
                (root / "resources" / "example.conformance").unlink(),
                (root / "resources" / "example.conformance").symlink_to(external_resource),
            ),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                root = self.root.parent / "parent" / "payload"
                if root.parent.is_symlink():
                    root.parent.unlink()
                else:
                    shutil.rmtree(root.parent, ignore_errors=True)
                root.parent.mkdir()
                shutil.copytree(self.root, root)
                mutate(root)

                with self.assertRaises(CapabilityPackagePayloadError) as raised:
                    open_portable_payload(root)

                _assert_body_free(
                    self,
                    raised.exception,
                    (str(root), str(external_root), "SECRET-EXTERNAL-BODY"),
                )

    def test_descriptor_replacement_cannot_open_external_payload_member(self) -> None:
        document = self.root / "capabilities" / "research.json"
        original_document = self.root / "capabilities" / "research.original"
        external_root = self.root.parent / "external-documents"
        external_root.mkdir()
        external_document = external_root / "external.json"
        _write_canonical_json(external_document, _capability_manifest("sentinel.external"))
        original_open = os.open
        replaced = False

        def replace_document() -> None:
            nonlocal replaced
            if replaced:
                return
            document.rename(original_document)
            document.symlink_to(external_document)
            replaced = True

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

        with (
            patch.object(os, "open", raced_open),
            self.assertRaises(CapabilityPackagePayloadError) as raised,
        ):
            open_portable_payload(self.root)

        _assert_body_free(self, raised.exception, ("sentinel.external", str(external_root)))

    def test_root_replacement_cannot_open_external_payload_member(self) -> None:
        original_root = self.root.parent / "payload-original"
        external_root = self.root.parent / "external-root"
        _create_payload(external_root)
        external_document = external_root / "capabilities" / "research.json"
        _write_canonical_json(external_document, _capability_manifest("sentinel.external"))
        original_open = os.open
        parent_identity = _file_identity(self.root.parent)
        replaced = False

        def replace_root() -> None:
            nonlocal replaced
            if replaced:
                return
            self.root.rename(original_root)
            self.root.symlink_to(external_root, target_is_directory=True)
            replaced = True

        def raced_open(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            component_root_open = (
                dir_fd is not None
                and os.fsdecode(path) == self.root.name
                and _fd_identity(dir_fd) == parent_identity
            )
            if component_root_open:
                replace_root()
            return original_open(path, flags, mode, dir_fd=dir_fd)

        with (
            patch.object(os, "open", raced_open),
            self.assertRaises(CapabilityPackagePayloadError) as raised,
        ):
            open_portable_payload(self.root)

        _assert_body_free(self, raised.exception, ("sentinel.external", str(external_root)))

    def test_hostile_filesystem_and_json_failures_are_redacted_but_interrupts_pass(self) -> None:
        with (
            patch.object(os, "listdir", side_effect=OSError("SECRET-OS-PATH")),
            self.assertRaises(CapabilityPackagePayloadError) as raised,
        ):
            open_portable_payload(self.root)
        _assert_body_free(self, raised.exception, ("SECRET-OS-PATH", str(self.root)))

        with (
            patch.object(json, "loads", side_effect=ValueError("SECRET-JSON-BODY")),
            self.assertRaises(CapabilityPackagePayloadError) as raised,
        ):
            open_portable_payload(self.root)
        _assert_body_free(self, raised.exception, ("SECRET-JSON-BODY", str(self.root)))

        with patch.object(json, "loads", side_effect=KeyboardInterrupt("SECRET-INTERRUPT")):
            with self.assertRaises(KeyboardInterrupt):
                open_portable_payload(self.root)

    def test_fails_closed_without_descriptor_relative_filesystem_primitives(self) -> None:
        with (
            patch.object(capability_payload, "_PINNED_PAYLOAD_AVAILABLE", False),
            self.assertRaises(CapabilityPackagePayloadError) as raised,
        ):
            open_portable_payload(self.root)

        self.assertEqual(str(raised.exception), "secure capability payload access is unavailable")


if __name__ == "__main__":
    unittest.main()
