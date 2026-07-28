from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
BENCHMARK_SOURCE = PROJECT / "src/asterion/benchmarks"
BENCHMARK_MODULES = frozenset(
    f"asterion/benchmarks/{path.name}"
    for path in BENCHMARK_SOURCE.glob("*.py")
)
BENCHMARK_SCHEMA = (
    "asterion/schemas/benchmark-suite/v1/benchmark-suite.schema.json"
)
BENCHMARK_SCHEMA_SOURCE = (
    PROJECT / "schemas/benchmark-suite/v1/benchmark-suite.schema.json"
)


class AsterionDistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._temporary.cleanup)
        output = Path(cls._temporary.name)
        subprocess.run(
            [
                "uv",
                "build",
                "--wheel",
                "--out-dir",
                str(output),
                str(PROJECT),
            ],
            cwd=PROJECT,
            check=True,
            capture_output=True,
            text=True,
        )
        cls._wheel = next(output.glob("asterion-*.whl"))

    def test_wheel_contains_complete_generic_benchmark_subsystem(self) -> None:
        with zipfile.ZipFile(self._wheel) as wheel:
            members = frozenset(wheel.namelist())
        self.assertEqual(BENCHMARK_MODULES - members, frozenset())

    def test_wheel_contains_canonical_benchmark_suite_schema(self) -> None:
        with zipfile.ZipFile(self._wheel) as wheel:
            members = frozenset(wheel.namelist())
            self.assertIn(BENCHMARK_SCHEMA, members)
            schema_bytes = wheel.read(BENCHMARK_SCHEMA)
        self.assertEqual(schema_bytes, BENCHMARK_SCHEMA_SOURCE.read_bytes())
        schema = json.loads(schema_bytes)
        self.assertEqual(
            schema["properties"]["protocol"]["const"],
            "asterion.benchmark-suite/v1",
        )


if __name__ == "__main__":
    unittest.main()
