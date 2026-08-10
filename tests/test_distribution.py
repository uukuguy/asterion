from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile


PROJECT = Path(__file__).resolve().parents[1]
BENCHMARK_SOURCE = PROJECT / "src/asterion/benchmarks"
DCI_SOURCE = PROJECT / "src/asterion/capabilities/dci"
PACKAGED_SCHEMAS = {
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
    "src/asterion/control/providers/prime/resources/skills/asterion-control/SKILL.md": (
        "asterion/control/providers/prime/resources/skills/asterion-control/SKILL.md"
    ),
    "src/asterion/control/providers/prime/resources/skills/asterion-control/pyproject.toml": (
        "asterion/control/providers/prime/resources/skills/asterion-control/pyproject.toml"
    ),
}


class DistributionTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
