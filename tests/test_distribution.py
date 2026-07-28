from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path

from asterion.capabilities.builtin import builtin_capability_sources
from asterion.capability_packages.payload import open_portable_payload


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
DCI_RUNTIME_RESOURCES = {
    "asterion/capabilities/dci/resources/pi/context-extension-manifest.json":
        PROJECT
        / "src/asterion/capabilities/dci/resources/pi/context-extension-manifest.json",
    "asterion/capabilities/dci/resources/pi/dci-context-extension.ts":
        PROJECT
        / "src/asterion/capabilities/dci/resources/pi/dci-context-extension.ts",
}


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

    def test_wheel_contains_builtin_externalization_conformance(self) -> None:
        registrations = builtin_capability_sources()
        with zipfile.ZipFile(self._wheel) as wheel:
            members = frozenset(wheel.namelist())
            for registration in registrations:
                payload_root = registration.payload_root
                source = (
                    payload_root.parent
                    / "conformance"
                    / "externalization.json"
                )
                member = source.relative_to(PROJECT / "src").as_posix()
                with self.subTest(package_ref=registration.package_ref):
                    self.assertIn(member, members)
                    self.assertEqual(wheel.read(member), source.read_bytes())
                    document = json.loads(wheel.read(member))
                    self.assertEqual(
                        set(document),
                        {"case_digests", "case_ids", "profile"},
                    )
                    self.assertEqual(
                        tuple(document["case_ids"]),
                        ("manifest-closure", "portable-identity"),
                    )
                    payload = open_portable_payload(payload_root)
                    self.assertEqual(
                        document["case_digests"],
                        {
                            "manifest-closure": _manifest_closure_sha256(
                                payload_root
                            ),
                            "portable-identity": payload.payload_sha256,
                        },
                    )

    def test_wheel_contains_exact_dci_runtime_resources(self) -> None:
        with zipfile.ZipFile(self._wheel) as wheel:
            members = frozenset(wheel.namelist())
            for member, source in DCI_RUNTIME_RESOURCES.items():
                with self.subTest(member=member):
                    self.assertIn(member, members)
                    self.assertEqual(wheel.read(member), source.read_bytes())

    def test_wheel_artifact_rule_tracks_the_package_owned_runtime_source(
        self,
    ) -> None:
        project = tomllib.loads((PROJECT / "pyproject.toml").read_text())
        self.assertEqual(
            project["tool"]["hatch"]["build"]["targets"]["wheel"]["artifacts"],
            [
                "src/asterion/capabilities/controlled_code/conformance/*.json",
                "src/asterion/capabilities/dci/conformance/*.json",
                "src/asterion/capabilities/dci/resources/pi/*.ts",
            ],
        )


def _manifest_closure_sha256(payload_root: Path) -> str:
    paths = (
        payload_root / "capability-package.json",
        *sorted((payload_root / "capabilities").glob("*.json")),
        *sorted((payload_root / "benchmark-suites").glob("*.json")),
    )
    members = tuple(
        {
            "path": path.relative_to(payload_root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in paths
    )
    canonical = json.dumps(
        members,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


if __name__ == "__main__":
    unittest.main()
