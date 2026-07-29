from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile


PROJECT = Path(__file__).resolve().parents[1]
BENCHMARK_SOURCE = PROJECT / "src/asterion/benchmarks"
BENCHMARK_SCHEMA = (
    PROJECT / "schemas/benchmark-suite/v1/benchmark-suite.schema.json"
)
PACKAGED_BENCHMARK_SCHEMA = (
    "asterion/schemas/benchmark-suite/v1/benchmark-suite.schema.json"
)


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
                self.assertIn(PACKAGED_BENCHMARK_SCHEMA, members)
                self.assertEqual(
                    wheel.read(PACKAGED_BENCHMARK_SCHEMA),
                    BENCHMARK_SCHEMA.read_bytes(),
                )


if __name__ == "__main__":
    unittest.main()
