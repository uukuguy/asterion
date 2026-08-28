from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import shutil
from pathlib import Path
from zipfile import ZipFile


PROJECT = Path(__file__).resolve().parents[1]
BENCHMARK_SOURCE = PROJECT / "src/asterion/benchmarks"
DCI_SOURCE = PROJECT / "src/asterion/capabilities/dci"
PACKAGED_SCHEMAS = {
    "schemas/operation/v1/doctor-request.schema.json": (
        "asterion/schemas/operation/v1/doctor-request.schema.json"
    ),
    "schemas/operation/v1/telemetry-usage-request.schema.json": (
        "asterion/schemas/operation/v1/telemetry-usage-request.schema.json"
    ),
    "schemas/operation/v1/settings-keybindings-request.schema.json": (
        "asterion/schemas/operation/v1/settings-keybindings-request.schema.json"
    ),
    "schemas/operation/v1/model-selection-request.schema.json": (
        "asterion/schemas/operation/v1/model-selection-request.schema.json"
    ),
    "schemas/operation/v1/auth-request.schema.json": (
        "asterion/schemas/operation/v1/auth-request.schema.json"
    ),
    "schemas/operation/v1/operation-request-descriptor.schema.json": (
        "asterion/schemas/operation/v1/operation-request-descriptor.schema.json"
    ),
    "schemas/operation/v1/operation-transaction.schema.json": (
        "asterion/schemas/operation/v1/operation-transaction.schema.json"
    ),
    "schemas/operation/v1/operation-receipt.schema.json": (
        "asterion/schemas/operation/v1/operation-receipt.schema.json"
    ),
    "schemas/agent-client/v1/event.schema.json": (
        "asterion/schemas/agent-client/v1/event.schema.json"
    ),
    "schemas/agent-client/v1/intent.schema.json": (
        "asterion/schemas/agent-client/v1/intent.schema.json"
    ),
    "schemas/agent-control/v1/command.schema.json": (
        "asterion/schemas/agent-control/v1/command.schema.json"
    ),
    "schemas/agent-control/v1/event.schema.json": (
        "asterion/schemas/agent-control/v1/event.schema.json"
    ),
    "schemas/agent-system/v1/agent-system.schema.json": (
        "asterion/schemas/agent-system/v1/agent-system.schema.json"
    ),
    "schemas/benchmark-suite/v1/benchmark-suite.schema.json": (
        "asterion/schemas/benchmark-suite/v1/benchmark-suite.schema.json"
    ),
    "schemas/control-plane/v1/control-plane-manifest.schema.json": (
        "asterion/schemas/control-plane/v1/control-plane-manifest.schema.json"
    ),
    "schemas/session-context/v1/command.schema.json": (
        "asterion/schemas/session-context/v1/command.schema.json"
    ),
    "schemas/session-context/v1/receipt.schema.json": (
        "asterion/schemas/session-context/v1/receipt.schema.json"
    ),
}
PRIME_DISTRIBUTION_MEMBERS = {
    "src/asterion/control/providers/prime/resources/control-plane.json": (
        "asterion/control/providers/prime/resources/control-plane.json"
    ),
    "packages/typescript/prime-gateway/resources/prime-artifact-lock.json": (
        "asterion/control/providers/prime/resources/prime-artifact-lock.json"
    ),
    "packages/typescript/prime-gateway/resources/prime-ecosystem-module-lock.json": (
        "asterion/control/providers/prime/resources/prime-ecosystem-module-lock.json"
    ),
    "packages/typescript/prime-gateway/resources/prime-ecosystem-module.mjs": (
        "asterion/control/providers/prime/resources/prime-ecosystem-module.mjs"
    ),
    "packages/typescript/prime-gateway/resources/prime-client-module-lock.json": (
        "asterion/control/providers/prime/resources/prime-client-module-lock.json"
    ),
    "packages/typescript/prime-gateway/resources/prime-client-module.mjs": (
        "asterion/control/providers/prime/resources/prime-client-module.mjs"
    ),
    "src/asterion/control/providers/prime/resources/skills/asterion-control/SKILL.md": (
        "asterion/control/providers/prime/resources/skills/asterion-control/SKILL.md"
    ),
    "src/asterion/control/providers/prime/resources/skills/asterion-control/pyproject.toml": (
        "asterion/control/providers/prime/resources/skills/asterion-control/pyproject.toml"
    ),
}


class DistributionTests(unittest.TestCase):
    def test_installed_wheel_client_module_requires_explicit_external_prime_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory)
            subprocess.run(("uv", "build", "--wheel", "--out-dir", str(destination), "."), cwd=PROJECT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            wheel = next(destination.glob("*.whl"))
            installed = destination / "installed"
            with ZipFile(wheel) as archive:
                archive.extractall(installed)
            external_root = destination / "external-prime-agent"
            subprocess.run(("git", "clone", "--no-hardlinks", "--no-checkout", str(PROJECT / "3th-party/prime-agent"), str(external_root)), check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            subprocess.run(("git", "checkout", "--detach", "a18809e00ea30638584d87b3afea7285a9d7296c"), cwd=external_root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            shutil.copytree(PROJECT / "3th-party/prime-agent/node_modules", external_root / "node_modules", symlinks=False)
            shutil.copytree(PROJECT / "3th-party/prime-agent/packages/coding-agent/node_modules", external_root / "packages/coding-agent/node_modules", symlinks=False)
            shutil.copytree(PROJECT / "3th-party/prime-agent/packages/coding-agent/dist", external_root / "packages/coding-agent/dist", symlinks=False)
            module = installed / "asterion/control/providers/prime/resources/prime-client-module.mjs"
            lock = installed / "asterion/control/providers/prime/resources/prime-client-module-lock.json"
            artifact = installed / "asterion/control/providers/prime/resources/prime-artifact-lock.json"
            harness = PROJECT / "tests/fixtures/prime_gateway/v1/real-prime-clients.mjs"
            completed = subprocess.run(("node", str(harness), "--package", "core", "--resource-root", str(module.parent), "--prime-root", str(external_root)), cwd=destination, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["package"], "core")
            self.assertFalse((destination / "3th-party").exists())
            escaped_root = destination / "external-prime-link"
            try:
                escaped_root.symlink_to(external_root, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")
            for invalid_root in (destination / "missing", external_root / "packages", external_root.parent, escaped_root):
                with self.subTest(root=invalid_root):
                    rejected = subprocess.run(("node", str(harness), "--package", "core", "--resource-root", str(module.parent), "--prime-root", str(invalid_root)), cwd=destination, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    self.assertNotEqual(rejected.returncode, 0)
            self.assertTrue(lock.is_file())
            self.assertTrue(artifact.is_file())

    def test_wheel_contains_generic_benchmark_modules_and_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory)
            subprocess.run(
                (
                    "uv",
                    "build",
                    "--wheel",
                    "--out-dir",
                    str(destination),
                    ".",
                ),
                cwd=PROJECT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            wheels = tuple(destination.glob("*.whl"))
            self.assertEqual(len(wheels), 1)
            with ZipFile(wheels[0]) as wheel:
                members = frozenset(wheel.namelist())
                expected_modules = frozenset(
                    path.relative_to(PROJECT / "src").as_posix()
                    for path in BENCHMARK_SOURCE.rglob("*.py")
                    if "__pycache__" not in path.parts
                )
                self.assertEqual(expected_modules - members, frozenset())
                expected_dci_members = frozenset(
                    path.relative_to(PROJECT / "src").as_posix()
                    for path in DCI_SOURCE.rglob("*")
                    if path.is_file() and "__pycache__" not in path.parts
                )
                self.assertEqual(expected_dci_members - members, frozenset())
                for relative in expected_dci_members:
                    if relative.endswith(".json"):
                        self.assertEqual(
                            wheel.read(relative),
                            (PROJECT / "src" / relative).read_bytes(),
                        )
                for source, packaged in PACKAGED_SCHEMAS.items():
                    with self.subTest(schema=source):
                        self.assertIn(packaged, members)
                        self.assertEqual(
                            wheel.read(packaged),
                            (PROJECT / source).read_bytes(),
                        )
                for source, packaged in PRIME_DISTRIBUTION_MEMBERS.items():
                    with self.subTest(prime_resource=source):
                        self.assertIn(packaged, members)
                        self.assertEqual(
                            wheel.read(packaged),
                            (PROJECT / source).read_bytes(),
                        )

    def test_wheel_installed_layout_resolves_exact_prime_ecosystem_locks(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory)
            subprocess.run(
                (
                    "uv",
                    "build",
                    "--wheel",
                    "--out-dir",
                    str(destination),
                    ".",
                ),
                cwd=PROJECT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            wheels = tuple(destination.glob("*.whl"))
            self.assertEqual(len(wheels), 1)
            installed = destination / "installed"
            with ZipFile(wheels[0]) as wheel:
                wheel.extractall(installed)

            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(installed)
            completed = subprocess.run(
                (
                    sys.executable,
                    "-c",
                    "from asterion.control.providers.prime.ecosystem import "
                    "_validated_checked_in_lock_contract as validate; "
                    "import json; print(json.dumps(validate(), separators=(',', ':')))",
                ),
                cwd=destination,
                env=environment,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            artifact_lock = (
                PROJECT
                / "packages/typescript/prime-gateway/resources/prime-artifact-lock.json"
            )
            module_lock = (
                PROJECT
                / "packages/typescript/prime-gateway/resources/prime-ecosystem-module-lock.json"
            )
            bundle = (
                PROJECT
                / "packages/typescript/prime-gateway/resources/prime-ecosystem-module.mjs"
            )
            self.assertEqual(
                json.loads(completed.stdout),
                [
                    hashlib.sha256(artifact_lock.read_bytes()).hexdigest(),
                    hashlib.sha256(module_lock.read_bytes()).hexdigest(),
                    hashlib.sha256(bundle.read_bytes()).hexdigest(),
                ],
            )
            self.assertNotIn(str(PROJECT), completed.stdout)


if __name__ == "__main__":
    unittest.main()
