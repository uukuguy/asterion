from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from typing import cast

from asterion.capability_packages.payload import open_portable_payload
from asterion.capability_packages.protocol import (
    BenchmarkSuiteRef,
    CapabilityPackageRef,
)


PAYLOAD_ROOT = (
    Path(__file__).resolve().parents[1] / "src/asterion/capabilities/dci/payload"
)
PACKAGE_REF = CapabilityPackageRef("dci", "1.0.0")
SUITE_TASKS = {
    "dci.bcplus.level3": ("bcplus.level3",),
    "dci.github": (
        "bcplus.level3",
        "bcplus.main",
        "bright.biology",
        "bright.earth-science",
        "bright.economics",
        "bright.robotics",
        "qa.2wikimultihopqa",
        "qa.bamboogle.github-sample50",
        "qa.hotpotqa",
        "qa.musique",
        "qa.nq",
        "qa.triviaqa",
    ),
    "dci.paper-main": (
        "bcplus.main",
        "beir.arguana",
        "beir.scifact",
        "bright.biology",
        "bright.earth-science",
        "bright.economics",
        "bright.robotics",
        "qa.2wikimultihopqa",
        "qa.bamboogle.paper-full125",
        "qa.hotpotqa",
        "qa.musique",
        "qa.nq",
        "qa.triviaqa",
    ),
    "dci.qa.bamboogle.github-sample50": (
        "qa.bamboogle.github-sample50",
    ),
    "dci.qa.bamboogle.paper-full125": (
        "qa.bamboogle.paper-full125",
    ),
}
SUITE_TASKS["dci.all"] = tuple(
    sorted(set(SUITE_TASKS["dci.github"]) | set(SUITE_TASKS["dci.paper-main"]))
)


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must contain an object")
    return value


def _walk_keys(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _object_list(value: dict[str, object], field: str) -> list[dict[str, object]]:
    items = value[field]
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise AssertionError(f"{field} must contain objects")
    return cast(list[dict[str, object]], items)


class TestDciCapabilityPayload(unittest.TestCase):
    def test_complete_payload_passes_the_generic_portable_validator(self) -> None:
        payload = open_portable_payload(PAYLOAD_ROOT)

        self.assertEqual(payload.manifest.package_ref, PACKAGE_REF)
        self.assertEqual(
            payload.manifest.benchmark_suites,
            (
                BenchmarkSuiteRef("dci.all", "1.0.0"),
                BenchmarkSuiteRef("dci.bcplus.level3", "1.0.0"),
                BenchmarkSuiteRef("dci.github", "1.0.0"),
                BenchmarkSuiteRef("dci.paper-main", "1.0.0"),
                BenchmarkSuiteRef(
                    "dci.qa.bamboogle.github-sample50",
                    "1.0.0",
                ),
                BenchmarkSuiteRef(
                    "dci.qa.bamboogle.paper-full125",
                    "1.0.0",
                ),
            ),
        )

    def test_descriptor_declares_each_payload_asset_exactly_once(self) -> None:
        descriptor = _load_json(PAYLOAD_ROOT / "capability-package.json")

        expected_capabilities = sorted(
            path.name for path in (PAYLOAD_ROOT / "capabilities").glob("*.json")
        )
        declared_capabilities = _object_list(descriptor, "capabilities")
        self.assertEqual(len(declared_capabilities), len(expected_capabilities))
        self.assertEqual(
            [item["capability_id"] for item in declared_capabilities],
            sorted(cast(str, item["capability_id"]) for item in declared_capabilities),
        )
        self.assertEqual(
            len({(item["capability_id"], item["version"]) for item in declared_capabilities}),
            len(declared_capabilities),
        )

        self.assertEqual(
            descriptor["benchmark_suites"],
            [
                {"suite_id": "dci.all", "version": "1.0.0"},
                {"suite_id": "dci.bcplus.level3", "version": "1.0.0"},
                {"suite_id": "dci.github", "version": "1.0.0"},
                {"suite_id": "dci.paper-main", "version": "1.0.0"},
                {
                    "suite_id": "dci.qa.bamboogle.github-sample50",
                    "version": "1.0.0",
                },
                {
                    "suite_id": "dci.qa.bamboogle.paper-full125",
                    "version": "1.0.0",
                },
            ],
        )
        for field, directory in (
            ("resources", "resources"),
            ("conformance", "conformance"),
        ):
            declarations = _object_list(descriptor, field)
            self.assertEqual(
                [item["resource_id"] for item in declarations],
                sorted(path.name for path in (PAYLOAD_ROOT / directory).iterdir()),
            )
            self.assertEqual(
                len({item["resource_id"] for item in declarations}),
                len(declarations),
            )
            for item in declarations:
                content = (
                    PAYLOAD_ROOT / directory / cast(str, item["resource_id"])
                ).read_bytes()
                self.assertEqual(item["sha256"], hashlib.sha256(content).hexdigest())

    def test_suites_own_the_exact_canonical_task_sets(self) -> None:
        for suite_id, expected_tasks in SUITE_TASKS.items():
            with self.subTest(suite_id=suite_id):
                suite = _load_json(
                    PAYLOAD_ROOT
                    / "benchmark-suites"
                    / (
                        f"{suite_id.removeprefix('dci.').replace('.', '-')}"
                        ".json"
                    )
                )
                self.assertEqual(suite["protocol"], "asterion.benchmark-suite/v1")
                self.assertEqual(suite["suite_id"], suite_id)
                self.assertEqual(
                    suite["owner_package"],
                    {"package_id": "dci", "version": "1.0.0"},
                )
                tasks = _object_list(suite, "tasks")
                self.assertEqual(tuple(task["task_id"] for task in tasks), expected_tasks)
                self.assertEqual(
                    tuple(task["binding_id"] for task in tasks),
                    expected_tasks,
                )
                self.assertTrue(
                    all(
                        task["capability"]
                        == {"capability_id": "dci.benchmark", "version": "1.0.0"}
                        for task in tasks
                    )
                )

    def test_bamboogle_variants_have_distinct_public_contract_notes(self) -> None:
        tasks: dict[str, dict[str, object]] = {}
        for suite_name in ("github", "paper-main"):
            suite = _load_json(
                PAYLOAD_ROOT / "benchmark-suites" / f"{suite_name}.json"
            )
            tasks.update(
                {
                    cast(str, task["task_id"]): task
                    for task in _object_list(suite, "tasks")
                }
            )

        github = tasks["qa.bamboogle.github-sample50"]
        paper = tasks["qa.bamboogle.paper-full125"]
        self.assertNotEqual(github["task_id"], paper["task_id"])
        self.assertNotEqual(github["binding_id"], paper["binding_id"])
        self.assertIn("50-case", cast(str, github["note"]))
        self.assertIn("125-case", cast(str, paper["note"]))
        self.assertNotEqual(github["note"], paper["note"])

    def test_manifests_exclude_operator_and_private_state(self) -> None:
        forbidden_keys = {
            "api_key",
            "command",
            "commands",
            "corpus_path",
            "credential",
            "credential_path",
            "credentials",
            "dataset_path",
            "environment",
            "executable",
            "mutable_state",
            "private_state",
            "prompt",
            "provider",
            "secret",
        }
        forbidden_text = (
            "scripts/",
            ".sh",
            ".env",
            "/private/sentinel",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
        )

        manifest_paths = sorted(PAYLOAD_ROOT.rglob("*.json"))
        for path in manifest_paths:
            with self.subTest(path=path.name):
                value = _load_json(path)
                self.assertTrue(forbidden_keys.isdisjoint(_walk_keys(value)))
                rendered = json.dumps(value, sort_keys=True)
                for forbidden in forbidden_text:
                    self.assertNotIn(forbidden, rendered)


if __name__ == "__main__":
    unittest.main()
