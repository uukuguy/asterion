from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from asterion.capabilities.catalog import CapabilityRef
from asterion.capability_packages.protocol import (
    BENCHMARK_SUITE_PROTOCOL_VERSION,
    BenchmarkSuiteManifest,
    BenchmarkSuiteProtocolError,
    BenchmarkSuiteRef,
    BenchmarkTaskManifest,
    CapabilityPackageRef,
    validate_benchmark_suite_manifest,
)


PROJECT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures/benchmark_suite/v1"
SCHEMA = PROJECT / "schemas/benchmark-suite/v1/benchmark-suite.schema.json"


def fixture(name: str) -> dict[str, object]:
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


VALID = fixture("valid-minimal.json")


class BenchmarkSuiteProtocolTests(unittest.TestCase):
    def test_accepts_the_closed_portable_suite_fixture(self) -> None:
        manifest = validate_benchmark_suite_manifest(VALID)

        self.assertEqual(
            BENCHMARK_SUITE_PROTOCOL_VERSION,
            "asterion.benchmark-suite/v1",
        )
        self.assertEqual(
            manifest,
            BenchmarkSuiteManifest(
                suite_ref=BenchmarkSuiteRef("example.suite", "1.0.0"),
                owner_package=CapabilityPackageRef(
                    "example.package",
                    "1.0.0",
                ),
                tasks=(
                    BenchmarkTaskManifest(
                        task_id="example.alpha",
                        capability=CapabilityRef(
                            "example.benchmark",
                            "1.0.0",
                        ),
                        binding_id="example.alpha",
                        metric_contract_id="example.metric/v1",
                        result_contract_id="example.result/v1",
                        note="",
                    ),
                    BenchmarkTaskManifest(
                        task_id="example.task",
                        capability=CapabilityRef(
                            "example.benchmark",
                            "1.0.0",
                        ),
                        binding_id="example.task",
                        metric_contract_id="example.metric/v1",
                        result_contract_id="example.result/v1",
                        note="Public synthetic task.",
                    ),
                ),
                artifact_media_types=("application/json", "text/plain"),
                default_case_limit=10,
                default_concurrency=1,
            ),
        )

    def test_returns_an_immutable_snapshot_detached_from_the_caller(self) -> None:
        value = fixture("valid-minimal.json")
        manifest = validate_benchmark_suite_manifest(value)

        value["suite_id"] = "changed.suite"
        tasks = value["tasks"]
        assert isinstance(tasks, list)
        tasks[0]["task_id"] = "changed.task"
        artifacts = value["artifact_media_types"]
        assert isinstance(artifacts, list)
        artifacts.append("changed/type")

        self.assertEqual(manifest.suite_ref.suite_id, "example.suite")
        self.assertEqual(manifest.tasks[0].task_id, "example.alpha")
        self.assertEqual(
            manifest.artifact_media_types,
            ("application/json", "text/plain"),
        )
        self.assertFalse(hasattr(manifest, "__dict__"))
        self.assertFalse(hasattr(manifest.tasks[0], "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            manifest.default_case_limit = 20  # type: ignore[misc]

    def test_rejects_shared_invalid_fixtures(self) -> None:
        for name in ("invalid-command.json", "invalid-task-order.json"):
            with (
                self.subTest(name=name),
                self.assertRaises(BenchmarkSuiteProtocolError),
            ):
                validate_benchmark_suite_manifest(fixture(name))

    def test_rejects_authority_fields_without_echoing_values(self) -> None:
        sentinel = "SECRET-AUTHORITY-VALUE"
        for forbidden in (
            "command",
            "dataset_path",
            "corpus_path",
            "provider",
            "environment",
        ):
            value = fixture("valid-minimal.json")
            tasks = value["tasks"]
            assert isinstance(tasks, list)
            tasks[0][forbidden] = sentinel
            with (
                self.subTest(forbidden=forbidden),
                self.assertRaises(BenchmarkSuiteProtocolError) as caught,
            ):
                validate_benchmark_suite_manifest(value)
            self.assertNotIn(sentinel, str(caught.exception))

    def test_rejects_invalid_nested_values_and_unbounded_defaults(self) -> None:
        cases = {
            "legacy-protocol": {
                **VALID,
                "protocol": "dci.benchmark-suite/v1",
            },
            "unknown-top-level-field": {**VALID, "provider": "SECRET"},
            "invalid-owner": {
                **VALID,
                "owner_package": {
                    "package_id": "Example Package",
                    "version": "1.0.0",
                },
            },
            "duplicate-task-id": {
                **VALID,
                "tasks": [
                    {
                        **VALID["tasks"][0],
                    },
                    {
                        **VALID["tasks"][0],
                    },
                ],
            },
            "invalid-capability-ref": {
                **VALID,
                "tasks": [
                    {
                        **VALID["tasks"][0],
                        "capability": {
                            "capability_id": "Example Capability",
                            "version": "1.0.0",
                        },
                    }
                ],
            },
            "invalid-contract": {
                **VALID,
                "tasks": [
                    {
                        **VALID["tasks"][0],
                        "metric_contract_id": "",
                    }
                ],
            },
            "unsorted-artifacts": {
                **VALID,
                "artifact_media_types": ["text/plain", "application/json"],
            },
            "zero-case-limit": {**VALID, "default_case_limit": 0},
            "zero-concurrency": {**VALID, "default_concurrency": 0},
        }

        for label, value in cases.items():
            with (
                self.subTest(label=label),
                self.assertRaises(BenchmarkSuiteProtocolError),
            ):
                validate_benchmark_suite_manifest(value)

    def test_canonical_schema_is_closed_and_authority_free(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            set(schema["required"]),
            {
                "protocol",
                "suite_id",
                "version",
                "owner_package",
                "tasks",
                "artifact_media_types",
                "default_case_limit",
                "default_concurrency",
            },
        )
        self.assertEqual(
            schema["properties"]["protocol"]["const"],
            BENCHMARK_SUITE_PROTOCOL_VERSION,
        )
        self.assertEqual(
            schema["properties"]["tasks"]["x-asterion-sorted-unique"],
            ["task_id"],
        )
        self.assertTrue(
            schema["properties"]["artifact_media_types"][
                "x-asterion-sorted-unique"
            ]
        )
        task = schema["$defs"]["task"]
        self.assertFalse(task["additionalProperties"])
        self.assertEqual(
            set(task["required"]),
            {
                "task_id",
                "capability",
                "binding_id",
                "metric_contract_id",
                "result_contract_id",
                "note",
            },
        )
        text = SCHEMA.read_text(encoding="utf-8")
        for forbidden in (
            "command",
            "dataset_path",
            "corpus_path",
            "provider",
            "environment",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(f'"{forbidden}"', text)


if __name__ == "__main__":
    unittest.main()
