from __future__ import annotations

import json
import unittest
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


FIXTURES = Path(__file__).parent / "fixtures" / "benchmark_suite" / "v1"
SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "schemas"
    / "benchmark-suite"
    / "v1"
    / "benchmark-suite.schema.json"
)


def fixture(name: str) -> dict[str, object]:
    value = json.loads((FIXTURES / name).read_text())
    assert isinstance(value, dict)
    return value


VALID = fixture("valid-minimal.json")


class BenchmarkSuiteProtocolTests(unittest.TestCase):
    def test_validates_an_exact_declarative_immutable_suite(self) -> None:
        value = fixture("valid-minimal.json")
        manifest = validate_benchmark_suite_manifest(value)

        self.assertEqual(BENCHMARK_SUITE_PROTOCOL_VERSION, "asterion.benchmark-suite/v1")
        self.assertEqual(
            manifest,
            BenchmarkSuiteManifest(
                suite_ref=BenchmarkSuiteRef("example.suite", "1.0.0"),
                owner_package=CapabilityPackageRef("example.package", "1.0.0"),
                tasks=(
                    BenchmarkTaskManifest(
                        task_id="example.task",
                        capability=CapabilityRef("example.benchmark", "1.0.0"),
                        binding_id="example.task",
                        metric_contract_id="example.metric/v1",
                        result_contract_id="example.result/v1",
                        note="",
                    ),
                ),
                artifact_media_types=("application/json",),
                default_case_limit=1,
                default_concurrency=1,
            ),
        )
        task = value["tasks"]
        assert isinstance(task, list)
        first = task[0]
        assert isinstance(first, dict)
        first["binding_id"] = "changed"
        self.assertEqual(manifest.tasks[0].binding_id, "example.task")
        with self.assertRaises(AttributeError):
            manifest.tasks += manifest.tasks

    def test_rejects_safe_declarative_boundary_violations(self) -> None:
        with self.assertRaises(BenchmarkSuiteProtocolError):
            validate_benchmark_suite_manifest(fixture("invalid-command.json"))

        task = fixture("valid-minimal.json")["tasks"]
        assert isinstance(task, list)
        base_task = task[0]
        assert isinstance(base_task, dict)
        for forbidden in (
            "command",
            "dataset_path",
            "corpus_path",
            "provider",
            "environment",
        ):
            with self.subTest(forbidden=forbidden), self.assertRaises(
                BenchmarkSuiteProtocolError
            ):
                validate_benchmark_suite_manifest(
                    {**VALID, "tasks": [{**base_task, forbidden: "SECRET"}]}
                )

    def test_rejects_noncanonical_or_duplicate_tasks(self) -> None:
        with self.assertRaises(BenchmarkSuiteProtocolError):
            validate_benchmark_suite_manifest(fixture("invalid-task-order.json"))
        task = fixture("valid-minimal.json")["tasks"]
        assert isinstance(task, list)
        with self.assertRaises(BenchmarkSuiteProtocolError):
            validate_benchmark_suite_manifest({**VALID, "tasks": task * 2})

    def test_rejects_noncanonical_artifact_media_types(self) -> None:
        for values in (
            ["text/plain", "application/json"],
            ["application/json", "application/json"],
        ):
            with self.subTest(values=values), self.assertRaises(
                BenchmarkSuiteProtocolError
            ):
                validate_benchmark_suite_manifest(
                    {**VALID, "artifact_media_types": values}
                )

    def test_rejects_malformed_bounds_contracts_and_unknown_fields(self) -> None:
        invalid_values = (
            {**VALID, "default_case_limit": 0},
            {**VALID, "default_concurrency": 0},
            {**VALID, "default_concurrency": 257},
            {
                **VALID,
                "tasks": [
                    {
                        **VALID["tasks"][0],  # type: ignore[index]
                        "metric_contract_id": "latest",
                    }
                ],
            },
            {**VALID, "prompt": "SECRET"},
        )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(
                BenchmarkSuiteProtocolError
            ):
                validate_benchmark_suite_manifest(value)

    def test_errors_are_body_free(self) -> None:
        with self.assertRaises(BenchmarkSuiteProtocolError) as raised:
            validate_benchmark_suite_manifest({**VALID, "prompt": "SECRET"})

        self.assertNotIn("SECRET", str(raised.exception))

    def test_schema_is_closed_and_declares_semantic_ordering(self) -> None:
        schema = json.loads(SCHEMA.read_text())

        self.assertFalse(schema["additionalProperties"])
        self.assertIn("Unicode scalar", schema["$comment"])
        self.assertFalse(schema["$defs"]["task"]["additionalProperties"])
        task_properties = schema["$defs"]["task"]["properties"]
        for forbidden in (
            "command",
            "dataset_path",
            "corpus_path",
            "provider",
            "environment",
        ):
            self.assertNotIn(forbidden, task_properties)


if __name__ == "__main__":
    unittest.main()
