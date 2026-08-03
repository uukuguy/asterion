from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile


PROJECT = Path(__file__).resolve().parents[1]
MODULE_NAME = "asterion.capabilities.dci.implementation.research.pathlight_observation"
RESOLVER_SPEC = importlib.util.find_spec(MODULE_NAME)
SOURCE_NAME = "dci-pathlight-observation.ts"
MANIFEST_NAME = "pathlight-observation-manifest.json"
MANIFEST_SCHEMA = "dci.pathlight-observation-extension-manifest/v1"
EXTENSION_VERSION = "0.3.0"
CONTRACT_VERSION = "dci.pathlight-provider-request-capture/v1"
SOURCE = (
    PROJECT
    / "packages/typescript/dci-context-extension/src/dci-pathlight-observation.ts"
).read_bytes()


def manifest_for(source: bytes = SOURCE) -> dict[str, object]:
    return {
        "schema": MANIFEST_SCHEMA,
        "extension_version": EXTENSION_VERSION,
        "contract_version": CONTRACT_VERSION,
        "resource": SOURCE_NAME,
        "byte_length": len(source),
        "sha256": hashlib.sha256(source).hexdigest(),
    }


def write_fixture(root: Path, *, source: bytes = SOURCE) -> None:
    root.mkdir(exist_ok=True)
    root.joinpath(SOURCE_NAME).write_bytes(source)
    root.joinpath(MANIFEST_NAME).write_text(
        f"{json.dumps(manifest_for(source), indent=2)}\n",
        encoding="utf-8",
    )


class PathlightObservationExtensionAvailabilityTests(unittest.TestCase):
    def test_integrity_resolver_is_implemented(self) -> None:
        self.assertIsNotNone(RESOLVER_SPEC)


@unittest.skipIf(RESOLVER_SPEC is None, "resolver not implemented yet")
class PathlightObservationExtensionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from asterion.capabilities.dci.implementation.research import (
            pathlight_observation,
        )

        cls.module = pathlight_observation

    def resolve_from(self, root: Path):
        return patch.object(self.module.resources, "files", return_value=root)

    def test_resolves_closed_identity_without_a_path_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_fixture(root)
            with (
                self.resolve_from(root),
                self.module.resolve_pathlight_observation_extension() as resolved,
            ):
                self.assertEqual(resolved.path, root / SOURCE_NAME)
                self.assertEqual(resolved.version, EXTENSION_VERSION)
                self.assertEqual(resolved.contract_version, CONTRACT_VERSION)
                self.assertEqual(resolved.sha256, hashlib.sha256(SOURCE).hexdigest())
                self.assertEqual(resolved.path.read_bytes(), SOURCE)
                self.assertNotIn(str(PROJECT), repr(resolved))

        with self.assertRaises(TypeError):
            self.module.resolve_pathlight_observation_extension(Path("override"))

    def test_missing_resource_fails_closed_and_redacts_paths(self) -> None:
        for missing in (SOURCE_NAME, MANIFEST_NAME):
            with (
                self.subTest(missing=missing),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                write_fixture(root)
                root.joinpath(missing).unlink()
                with (
                    self.resolve_from(root),
                    self.assertRaises(
                        self.module.PathlightObservationExtensionError
                    ) as raised,
                ):
                    with self.module.resolve_pathlight_observation_extension():
                        pass
                self.assertEqual(
                    str(raised.exception),
                    "DCI Pathlight observation extension is invalid",
                )
                self.assertNotIn(str(root), str(raised.exception))

    def test_symlink_and_non_regular_resources_fail_closed(self) -> None:
        for unsafe_name, unsafe_kind in (
            (SOURCE_NAME, "symlink"),
            (MANIFEST_NAME, "symlink"),
            (SOURCE_NAME, "directory"),
            (MANIFEST_NAME, "directory"),
        ):
            with (
                self.subTest(resource=unsafe_name, kind=unsafe_kind),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                write_fixture(root)
                unsafe = root / unsafe_name
                unsafe.unlink()
                if unsafe_kind == "symlink":
                    target = root / f"{unsafe_name}.target"
                    target.write_bytes(SOURCE if unsafe_name == SOURCE_NAME else b"{}")
                    unsafe.symlink_to(target)
                else:
                    unsafe.mkdir()
                with (
                    self.resolve_from(root),
                    self.assertRaises(self.module.PathlightObservationExtensionError),
                ):
                    with self.module.resolve_pathlight_observation_extension():
                        pass

    def test_world_writable_source_or_manifest_fails_closed(self) -> None:
        for mutable_name in (SOURCE_NAME, MANIFEST_NAME):
            with (
                self.subTest(resource=mutable_name),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                write_fixture(root)
                mutable = root / mutable_name
                mutable.chmod(mutable.stat().st_mode | stat.S_IWOTH)
                try:
                    with (
                        self.resolve_from(root),
                        self.assertRaises(
                            self.module.PathlightObservationExtensionError
                        ),
                    ):
                        with self.module.resolve_pathlight_observation_extension():
                            pass
                finally:
                    mutable.chmod(0o644)

    def test_manifest_schema_version_contract_size_and_digest_are_exact(self) -> None:
        mutations = {
            "schema": "dci.pathlight-observation-extension-manifest/v2",
            "extension_version": "0.3.1",
            "contract_version": "dci.pathlight-provider-request-capture/v2",
            "resource": "other.ts",
            "byte_length": len(SOURCE) + 1,
            "sha256": "0" * 64,
        }
        for key, value in mutations.items():
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                write_fixture(root)
                manifest = manifest_for()
                manifest[key] = value
                root.joinpath(MANIFEST_NAME).write_text(
                    json.dumps(manifest), encoding="utf-8"
                )
                with (
                    self.resolve_from(root),
                    self.assertRaises(self.module.PathlightObservationExtensionError),
                ):
                    with self.module.resolve_pathlight_observation_extension():
                        pass

        for transform in (
            lambda value: {**value, "private_path": "/SENTINEL_PRIVATE"},
            lambda value: {key: item for key, item in value.items() if key != "sha256"},
        ):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                write_fixture(root)
                root.joinpath(MANIFEST_NAME).write_text(
                    json.dumps(transform(manifest_for())), encoding="utf-8"
                )
                with (
                    self.resolve_from(root),
                    self.assertRaises(self.module.PathlightObservationExtensionError),
                ):
                    with self.module.resolve_pathlight_observation_extension():
                        pass

    def test_source_allows_only_the_supported_hook_and_runtime_imports(self) -> None:
        mutations = (
            SOURCE + b'\nimport "node:child_process";\n',
            SOURCE + b'\nconst sentinel = import("node:child_process");\n',
            SOURCE.replace(
                b'pi.on("before_provider_request",',
                b'pi.on("before_provider_request",\n  () => undefined);\n  pi.on("before_provider_request",',
                1,
            ),
            SOURCE + b'\npi.registerProvider("sentinel", {});\n',
            SOURCE + b'\npi.registerTool({ name: "sentinel" });\n',
            SOURCE + b'\npi.registerCommand("sentinel", () => undefined);\n',
        )
        for index, source in enumerate(mutations):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                write_fixture(root, source=source)
                with (
                    self.resolve_from(root),
                    self.assertRaises(self.module.PathlightObservationExtensionError),
                ):
                    with self.module.resolve_pathlight_observation_extension():
                        pass

    def test_checked_in_source_has_one_supported_hook_and_no_registration(self) -> None:
        with self.module.resolve_pathlight_observation_extension() as resolved:
            text = resolved.path.read_text(encoding="utf-8")
        self.assertEqual(text.count('pi.on("before_provider_request"'), 1)
        self.assertNotIn("registerProvider", text)
        self.assertNotIn("registerTool", text)
        self.assertNotIn("registerCommand", text)

    def test_check_mode_is_exact_and_non_mutating(self) -> None:
        resource_root = PROJECT / "src/asterion/capabilities/dci/resources/pi"
        paths = (
            resource_root / "dci-context-extension.ts",
            resource_root / "context-extension-manifest.json",
            resource_root / SOURCE_NAME,
            resource_root / MANIFEST_NAME,
        )
        before = tuple((path.read_bytes(), path.stat().st_mtime_ns) for path in paths)
        checked = subprocess.run(
            (
                "npm",
                "run",
                "check-resource",
                "--prefix",
                "packages/typescript/dci-context-extension",
            ),
            cwd=PROJECT,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(
            tuple((path.read_bytes(), path.stat().st_mtime_ns) for path in paths),
            before,
        )

    def test_installed_wheel_resolves_the_packaged_resource(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheelhouse = root / "wheelhouse"
            wheelhouse.mkdir()
            built = subprocess.run(
                ("uv", "build", "--wheel", "--out-dir", str(wheelhouse), str(PROJECT)),
                cwd=root,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(built.returncode, 0, built.stderr)
            wheel = next(wheelhouse.glob("asterion-*.whl"))
            target = root / "installed"
            with ZipFile(wheel) as archive:
                archive.extractall(target)
            script = (
                "import json,sys;"
                f"sys.path.insert(0,{str(target)!r});"
                f"from {MODULE_NAME} import resolve_pathlight_observation_extension;"
                "\nwith resolve_pathlight_observation_extension() as value:"
                "\n print(json.dumps({'name': value.path.name, 'version': value.version, "
                "'sha256': value.sha256, 'contract_version': value.contract_version}, sort_keys=True))"
            )
            resolved = subprocess.run(
                (sys.executable, "-I", "-S", "-c", script),
                cwd=root,
                env={"PATH": os.environ.get("PATH", "")},
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(resolved.returncode, 0, resolved.stderr)
            value = json.loads(resolved.stdout)
            self.assertEqual(value["name"], SOURCE_NAME)
            self.assertEqual(value["version"], EXTENSION_VERSION)
            self.assertEqual(value["contract_version"], CONTRACT_VERSION)
            self.assertEqual(value["sha256"], hashlib.sha256(SOURCE).hexdigest())
            self.assertNotIn(str(PROJECT), resolved.stdout + resolved.stderr)

    def test_provenance_hashes_both_packaged_observation_resources(self) -> None:
        from asterion.capabilities.dci.implementation import _provenance
        from asterion.capabilities.dci.implementation.reproduction import provenance

        expected = {
            f"capabilities/dci/resources/pi/{SOURCE_NAME}",
            f"capabilities/dci/resources/pi/{MANIFEST_NAME}",
        }
        self.assertLessEqual(
            expected, set(_provenance.DCI_COMPLETE_IMPLEMENTATION_RESOURCES)
        )
        self.assertEqual(
            _provenance.DCI_COMPLETE_IMPLEMENTATION_RESOURCES,
            provenance.DCI_COMPLETE_IMPLEMENTATION_RESOURCES,
        )


if __name__ == "__main__":
    unittest.main()
