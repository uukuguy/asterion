from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tarfile
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile


PROJECT = Path(__file__).resolve().parents[1]
PACKAGE = "packages/typescript/asterion-prime-extension"
BUNDLE = "src/asterion/applications/prime/resources/ipython-extension.mjs"
ATTESTATION = ".asterion-prime-extension-build.json"
INPUTS = tuple(sorted((
    "hatch_build.py",
    "pyproject.toml",
    *(f"{PACKAGE}/{name}" for name in (
        "package.json", "package-lock.json", "tsconfig.json",
        "tsconfig.contract.json", "test/pi-contract.ts",
        "src/ipython-extension.ts", "src/context-counter.ts",
        "src/context-projection.ts", "src/context-witness.ts",
    )),
)))


class _HookInterface:
    def __init__(self, root: str, target_name: str) -> None:
        self.root = root
        self.target_name = target_name
        self.metadata = SimpleNamespace(version="0.1.0")


def _hook(root: Path, target: str):
    # Hatch itself is an isolated build dependency, not a core test dependency.
    interface = ModuleType("hatchling.builders.hooks.plugin.interface")
    interface.BuildHookInterface = _HookInterface  # type: ignore[attr-defined]
    with patch.dict("sys.modules", {interface.__name__: interface}):
        namespace = runpy.run_path(str(PROJECT / "hatch_build.py"))
    return namespace["CustomBuildHook"](str(root), target)


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _expected_attestation(root: Path, bundle: bytes | None = None) -> bytes:
    return _canonical({
        "contract": "asterion.prime-extension-build/v1",
        "inputs": [
            {"path": name, "sha256": hashlib.sha256((root / name).read_bytes()).hexdigest()}
            for name in INPUTS
        ],
        "output": {
            "path": BUNDLE,
            "sha256": hashlib.sha256((root / BUNDLE).read_bytes() if bundle is None else bundle).hexdigest(),
        },
    })


class TestPrimeExtensionBuild(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in INPUTS:
            destination = self.root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PROJECT / name, destination)
        self.bundle = self.root / BUNDLE
        self.bundle.parent.mkdir(parents=True, exist_ok=True)
        self.compiled = b"export default function register() {}\n"

    def _compile(self, command, **kwargs) -> None:
        self.assertEqual(command[:3], ("npm", "run", "build"))
        self.assertEqual(kwargs["cwd"], self.root / PACKAGE)
        source = (
            Path(command[-1].removeprefix("--outfile="))
            if len(command) > 3 else self.root / PACKAGE / "dist/ipython-extension.mjs"
        )
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(self.compiled)

    def _sdist(self) -> None:
        (self.root / "PKG-INFO").write_text("Metadata-Version: 2.4\nName: asterion\nVersion: 0.1.0\n")
        self.bundle.write_bytes(self.compiled)
        (self.root / ATTESTATION).write_bytes(_expected_attestation(self.root))

    def test_source_targets_compile_and_attest_before_collection(self) -> None:
        for target in ("wheel", "sdist"):
            with self.subTest(target=target):
                hook = _hook(self.root, target)
                self.addCleanup(hook.finalize, "standard", {}, "unused")
                data = {}
                with patch("subprocess.run", side_effect=self._compile) as compiler:
                    hook.initialize("standard", data)
                compiler.assert_called_once()
                self.assertFalse(self.bundle.exists(), "build must not write source bundle")
                bundle = self._mapped(data, BUNDLE if target == "sdist" else BUNDLE.removeprefix("src/"))
                self.assertEqual(bundle.read_bytes(), self.compiled)
                if target == "sdist":
                    self.assertEqual(self._mapped(data, ATTESTATION).read_bytes(), _expected_attestation(self.root, self.compiled))
                hook.finalize("standard", {}, "unused")
                self.assertFalse(bundle.exists())
                self.assertFalse((self.root / ATTESTATION).exists())

    def _mapped(self, data, destination: str) -> Path:
        self.assertIn("force_include", data, "build must stage forced resources")
        sources = [Path(source) for source, target in data["force_include"].items() if target == destination]
        self.assertEqual(len(sources), 1)
        return sources[0]

    def test_sdist_wheel_reuses_verified_bundle_without_node(self) -> None:
        self._sdist()
        self.assertFalse((self.root / PACKAGE / "node_modules").exists())
        hook = _hook(self.root, "wheel")
        with patch("subprocess.run", side_effect=AssertionError("sdist must not run npm")):
            hook.initialize("standard", {})
            hook.finalize("standard", {}, "unused")
        self.assertEqual(self.bundle.read_bytes(), self.compiled)
        self.assertEqual((self.root / ATTESTATION).read_bytes(), _expected_attestation(self.root))

    def test_source_build_never_overwrites_preexisting_or_replaced_files(self) -> None:
        self.bundle.write_bytes(b"preexisting bundle")
        attestation = self.root / ATTESTATION
        attestation.write_bytes(b"preexisting attestation")
        hook = _hook(self.root, "wheel")
        self.addCleanup(hook.finalize, "standard", {}, "unused")
        with patch("subprocess.run", side_effect=self._compile) as compiler:
            hook.initialize("standard", {})
        compiler.assert_called_once()
        self.assertEqual(self.bundle.read_bytes(), b"preexisting bundle")
        self.bundle.write_bytes(b"user replacement")
        attestation.write_bytes(b"user attestation")
        hook.finalize("standard", {}, "unused")
        self.assertTrue(self.bundle.exists(), "preexisting bundle was removed")
        self.assertEqual(self.bundle.read_bytes(), b"user replacement")
        self.assertEqual(attestation.read_bytes(), b"user attestation")

    def test_overlapping_builds_have_independent_outputs_and_cleanup(self) -> None:
        first, second = _hook(self.root, "wheel"), _hook(self.root, "wheel")
        for hook in (first, second):
            self.addCleanup(hook.finalize, "standard", {}, "unused")
        one, two = {}, {}
        with patch("subprocess.run", side_effect=self._compile) as compiler:
            first.initialize("standard", one)
            second.initialize("standard", two)
        self.assertEqual(compiler.call_count, 2)
        self.assertNotEqual(compiler.call_args_list[0].args[0], compiler.call_args_list[1].args[0])
        first_bundle = self._mapped(one, BUNDLE.removeprefix("src/"))
        second_bundle = self._mapped(two, BUNDLE.removeprefix("src/"))
        self.assertNotEqual(first_bundle.parent, second_bundle.parent)
        first.finalize("standard", {}, "unused")
        self.assertEqual(second_bundle.read_bytes(), self.compiled)
        self.assertFalse((self.root / PACKAGE / "dist/ipython-extension.mjs").exists())

    def test_input_change_during_compile_rolls_back_only_its_staging(self) -> None:
        outputs = []

        def changing_compile(command, **kwargs):
            self._compile(command, **kwargs)
            outputs.append(Path(command[-1].removeprefix("--outfile=")))
            (self.root / PACKAGE / "src/context-counter.ts").write_text("changed during compile")

        with patch("subprocess.run", side_effect=changing_compile):
            with self.assertRaisesRegex(ValueError, "extension build closure is invalid"):
                _hook(self.root, "wheel").initialize("standard", {})
        self.assertFalse(self.bundle.exists())
        self.assertTrue(all(not path.exists() for path in outputs))

    def test_sdist_marker_identity_and_regular_file_fail_closed(self) -> None:
        for damage in ("name", "version", "duplicate", "directory", "symlink"):
            with self.subTest(damage=damage):
                self._sdist()
                marker = self.root / "PKG-INFO"
                if damage in {"directory", "symlink"}:
                    marker.unlink()
                    if damage == "directory":
                        marker.mkdir()
                    else:
                        marker.symlink_to(self.root / "pyproject.toml")
                else:
                    marker.write_text({
                        "name": "Name: other\nVersion: 0.1.0\n",
                        "version": "Name: asterion\nVersion: 0.2.0\n",
                        "duplicate": "Name: asterion\nName: other\nVersion: 0.1.0\n",
                    }[damage])
                try:
                    with patch("subprocess.run", side_effect=AssertionError("fake marker must not run npm")):
                        with self.assertRaisesRegex(ValueError, "extension build closure is invalid"):
                            _hook(self.root, "wheel").initialize("standard", {})
                finally:
                    if marker.is_dir() and not marker.is_symlink():
                        marker.rmdir()
                    else:
                        marker.unlink()

    def test_sdist_missing_or_drifted_closure_fails_before_subprocess(self) -> None:
        for damage in ("bundle-missing", "attestation-missing", "bundle-drift",
                       "attestation-drift", "input-drift", "noncanonical",
                       "output-path", "digest-type", "extra-input"):
            with self.subTest(damage=damage):
                self._sdist()
                attestation = self.root / ATTESTATION
                if damage == "bundle-missing":
                    self.bundle.unlink()
                elif damage == "attestation-missing":
                    attestation.unlink()
                elif damage == "bundle-drift":
                    self.bundle.write_bytes(b"modified")
                elif damage == "attestation-drift":
                    value = json.loads(attestation.read_bytes())
                    value["contract"] = "different/v1"
                    attestation.write_bytes(_canonical(value))
                elif damage == "input-drift":
                    (self.root / PACKAGE / "src/context-counter.ts").write_text("modified")
                elif damage == "noncanonical":
                    attestation.write_bytes(attestation.read_bytes() + b"\n")
                else:
                    value = json.loads(attestation.read_bytes())
                    if damage == "output-path":
                        value["output"]["path"] = "../outside.mjs"
                    elif damage == "digest-type":
                        value["output"]["sha256"] = [value["output"]["sha256"]]
                    else:
                        value["inputs"].append({"path": "extra.ts", "sha256": "0" * 64})
                    attestation.write_bytes(_canonical(value))
                with patch("subprocess.run", side_effect=AssertionError("invalid sdist must not run npm")) as compiler:
                    with self.assertRaisesRegex(ValueError, "extension build closure is invalid"):
                        _hook(self.root, "wheel").initialize("standard", {})
                compiler.assert_not_called()


class TestPrimeExtensionBuildDistribution(unittest.TestCase):
    def test_real_sdist_wheel_is_node_free_and_byte_identical_to_direct_wheel(self) -> None:
        uv = shutil.which("uv")
        self.assertIsNotNone(uv)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source_build = subprocess.run(
                [str(uv), "build", "--sdist", str(PROJECT), "--out-dir", str(root / "sdist")],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(source_build.returncode, 0, source_build.stderr)
            with tarfile.open(next((root / "sdist").glob("*.tar.gz"))) as archive:
                names = archive.getnames()
                self.assertFalse(any("node_modules" in Path(name).parts for name in names))
                prefix = names[0].split("/", 1)[0]
                self.assertTrue(f"{prefix}/{ATTESTATION}" in names, "sdist lacks build attestation")
                # Locally produced archive; reject traversal before extracting.
                for member in archive.getmembers():
                    self.assertFalse(member.issym() or member.islnk())
                    self.assertTrue((root / member.name).resolve().is_relative_to(root))
                archive.extractall(root)
            extracted = root / prefix
            attestation = json.loads((extracted / ATTESTATION).read_bytes())
            bundle = (extracted / BUNDLE).read_bytes()
            self.assertEqual(attestation["output"]["sha256"], hashlib.sha256(bundle).hexdigest())
            no_commands = root / "no-commands"
            no_commands.mkdir()
            wheel_build = subprocess.run(
                [str(uv), "build", "--offline", "--python", sys.executable, "--wheel", str(extracted),
                 "--out-dir", str(root / "rebuilt")],
                env={**os.environ, "PATH": str(no_commands)},
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(wheel_build.returncode, 0, wheel_build.stderr)
            def direct_build(target):
                return subprocess.run(
                    [str(uv), "build", "--wheel", str(PROJECT), "--out-dir", str(root / target)],
                    capture_output=True, text=True, check=False,
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                builds = tuple(pool.map(direct_build, ("direct-one", "direct-two")))
            for build in builds:
                self.assertEqual(build.returncode, 0, build.stderr)
            wheel_resource = BUNDLE.removeprefix("src/")
            for target in ("rebuilt", "direct-one", "direct-two"):
                with ZipFile(next((root / target).glob("*.whl"))) as archive:
                    self.assertEqual(archive.read(wheel_resource), bundle)


if __name__ == "__main__":
    unittest.main()
